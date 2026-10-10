"""Virenprüfung hochgeladener Dokumente mit ClamAV (M0: „Inhaltsprüfung + Virenscan, Status quarantined bis geprüft").

* Protokoll: clamd ``INSTREAM`` über TCP — keine zusätzliche Bibliothek. Antwort ``stream: OK`` oder
  ``stream: <Signatur> FOUND``; alles andere ist ein Fehler (Dokument bleibt in Quarantäne).
* Ablauf: ``ichq documents-scan`` (Dienst ``scanner`` in Compose) nimmt je Firma die ältesten Dokumente in
  ``quarantined`` (``FOR UPDATE SKIP LOCKED`` — mehrere Scanner kollidieren nicht), prüft sie und setzt
  ``clean`` oder ``infected``. Ist ClamAV nicht erreichbar (z. B. lädt noch Signaturen), bleibt alles in Quarantäne
  und der nächste Lauf versucht es erneut — **nie** wird ungeprüft freigegeben.
* Je Firma eine eigene Mandanten-Transaktion als ``ichq_worker`` (Migration 0007: die Web-App darf das Ergebnis nicht
  schreiben), Fehler je Firma isoliert, Ergebnis im Mandanten-Audit.
"""
from __future__ import annotations

import logging
import socket
import struct
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text, update

from ichq.audit.service import record as audit
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.documents.models import Document
from ichq.objects.models import ObjectRow
from ichq.storage import Storage

log = logging.getLogger("ichq.jobs.documents_scan")
CHUNK = 64 * 1024


class ScannerUnavailable(Exception):
    """ClamAV nicht erreichbar oder unverständliche Antwort — Dokument bleibt in Quarantäne."""


@dataclass(frozen=True)
class Verdict:
    clean: bool
    signature: str | None = None


class ClamdClient:
    def __init__(self, host: str, port: int = 3310, timeout: float = 60.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    def _frage(self, befehl: bytes, daten: bytes | None = None) -> str:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as s:
                s.sendall(befehl)
                if daten is not None:
                    for i in range(0, len(daten), CHUNK):
                        teil = daten[i:i + CHUNK]
                        s.sendall(struct.pack("!L", len(teil)) + teil)
                    s.sendall(struct.pack("!L", 0))
                antwort = b""
                while not antwort.endswith(b"\0"):
                    stueck = s.recv(4096)
                    if not stueck:
                        break
                    antwort += stueck
        except OSError as e:
            raise ScannerUnavailable(f"clamd nicht erreichbar: {e.__class__.__name__}") from None
        return antwort.rstrip(b"\0").decode("utf-8", "replace").strip()

    def ping(self) -> bool:
        try:
            return self._frage(b"zPING\0") == "PONG"
        except ScannerUnavailable:
            return False

    def scan(self, daten: bytes) -> Verdict:
        antwort = self._frage(b"zINSTREAM\0", daten)
        if antwort == "stream: OK":
            return Verdict(True)
        if antwort.startswith("stream: ") and antwort.endswith(" FOUND"):
            return Verdict(False, antwort[len("stream: "):-len(" FOUND")][:120])
        raise ScannerUnavailable(f"unerwartete clamd-Antwort ({len(antwort)} Zeichen)")   # z. B. Größenlimit


@dataclass
class ScanRun:
    clean: int = 0
    infected: int = 0
    pending: int = 0                                     # nicht geprüft (Scanner weg) — bleiben in Quarantäne
    failed_tenants: list[str] = field(default_factory=list)


def _firma(engines: Engines, storage: Storage, client: ClamdClient, tid: uuid.UUID, limit: int, lauf: ScanRun) -> None:
    """Eine Firma. Fällt der Scanner mitten im Stapel aus, bleibt das bereits Geprüfte gespeichert (Commit) und der
    Rest in Quarantäne; danach wird der Ausfall gemeldet."""
    ausfall: ScannerUnavailable | None = None
    with tenant_transaction(engines.worker, tid) as s:   # Worker-Rolle: nur scan_status, nur diese Firma
        zeilen = s.execute(select(Document, ObjectRow.public_id).join(
            ObjectRow, (ObjectRow.id == Document.id) & (ObjectRow.tenant_id == Document.tenant_id))
            .where(Document.scan_status == "quarantined").order_by(ObjectRow.created_at)
            .limit(limit).with_for_update(of=Document, skip_locked=True)).all()
        for i, (doc, pid) in enumerate(zeilen):
            try:
                urteil = client.scan(storage.get(doc.storage_key))
            except ScannerUnavailable as e:
                ausfall, lauf.pending = e, lauf.pending + len(zeilen) - i
                break
            status = "clean" if urteil.clean else "infected"
            s.execute(update(Document).where(Document.id == doc.id).values(scan_status=status))
            audit(s, "document.scanned", target_type="document", target_id=pid,
                  data={"result": status, **({"signature": urteil.signature} if urteil.signature else {})})
            if urteil.clean:
                lauf.clean += 1
            else:
                lauf.infected += 1
                log.warning("dokument_infiziert", extra={"tenant_id": str(tid), "document": pid,
                                                         "signatur": urteil.signature})
    if ausfall is not None:
        raise ausfall


def scan_pending(engines: Engines, storage: Storage, client: ClamdClient, limit: int = 50) -> ScanRun:
    lauf = ScanRun()
    with platform_transaction(engines.platform) as s:
        firmen = list(s.scalars(text("SELECT id FROM tenants WHERE status IN ('active','paused') ORDER BY id")))
    for tid in firmen:
        try:
            _firma(engines, storage, client, tid, limit, lauf)
        except ScannerUnavailable as e:
            log.warning("virenscanner_nicht_erreichbar", extra={"fehler": str(e)})
            break                                        # nächster Lauf versucht es erneut
        except Exception as e:   # eine Firma darf die anderen nicht aufhalten
            lauf.failed_tenants.append(str(tid))
            log.error("dokumente_scan_firma_fehler", extra={"tenant_id": str(tid), "fehler": e.__class__.__name__})
    return lauf
