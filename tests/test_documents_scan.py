"""Virenprüfung (ClamAV, clamd INSTREAM): sauber → Download möglich, infiziert → gesperrt, Scanner weg → alles bleibt
in Quarantäne, Ausfall mitten im Stapel verliert nichts, Firmen getrennt. Gegen einen Test-clamd, der das echte
Protokoll spricht (Länge + Daten, Null-Terminierung); gegen echtes ClamAV prüft deploy/smoke-test.sh."""
from __future__ import annotations

import socket
import struct
import threading
from collections.abc import Iterator
from typing import Any

import pytest

from ichq.documents.scan import ClamdClient, ScannerUnavailable, scan_pending
from ichq.storage import build_storage
from tests.auth_helpers import db
from tests.core_helpers import ok
from tests.m4_helpers import RbacWorld

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class FakeClamd:
    """Antwortet wie clamd: 'stream: OK' oder 'stream: Eicar-Signature FOUND'. ``abbruch_nach``: nach n Scans
    Verbindung ohne Antwort schließen (Ausfall mitten im Stapel)."""

    def __init__(self, abbruch_nach: int | None = None, antwort: bytes | None = None) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.scans, self.abbruch_nach, self.empfangen, self.antwort = 0, abbruch_nach, [], antwort
        threading.Thread(target=self._dienen, daemon=True).start()

    def _lesen(self, c: socket.socket, n: int) -> bytes:
        daten = b""
        while len(daten) < n:
            teil = c.recv(n - len(daten))
            if not teil:
                raise ConnectionError
            daten += teil
        return daten

    def _dienen(self) -> None:
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            with c:
                befehl = b""
                while not befehl.endswith(b"\0"):
                    befehl += c.recv(1)
                if befehl == b"zPING\0":
                    c.sendall(b"PONG\0")
                    continue
                inhalt = b""
                while (laenge := struct.unpack("!L", self._lesen(c, 4))[0]):
                    inhalt += self._lesen(c, laenge)
                self.empfangen.append(inhalt)
                self.scans += 1
                if self.abbruch_nach is not None and self.scans > self.abbruch_nach:
                    continue                                     # Verbindung zu, keine Antwort
                if self.antwort is not None:
                    c.sendall(self.antwort)
                    continue
                c.sendall(b"stream: Eicar-Signature FOUND\0" if EICAR in inhalt else b"stream: OK\0")

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def clamd() -> Iterator[FakeClamd]:
    f = FakeClamd()
    yield f
    f.close()


def _hochladen(c: Any, name: str, inhalt: bytes) -> str:
    return str(ok(c.post(f"/api/v1/documents?filename={name}", content=inhalt,
                         headers={"content-type": "text/plain"}), 201)["id"])


def _status(rw: RbacWorld, ref: str) -> str:
    return str(ok(rw.client(rw.admin).get(f"/api/v1/documents/{ref}"))["scan_status"])


def test_client_protokoll(clamd: FakeClamd) -> None:
    c = ClamdClient("127.0.0.1", clamd.port, timeout=5)
    assert c.ping()
    gross = b"x" * (200 * 1024 + 7)                              # mehrere 64-KiB-Stücke
    assert c.scan(gross).clean and clamd.empfangen[-1] == gross
    v = c.scan(b"vorher " + EICAR + b" nachher")
    assert not v.clean and v.signature == "Eicar-Signature"
    with pytest.raises(ScannerUnavailable):
        ClamdClient("127.0.0.1", 1, timeout=2).scan(b"egal")      # niemand hört zu
    assert not ClamdClient("127.0.0.1", 1, timeout=2).ping()


def test_sauber_infiziert_und_download(rw: RbacWorld, clamd: FakeClamd, settings: Any) -> None:
    a = rw.client(rw.admin)
    gut, boese = _hochladen(a, "gut.txt", b"Rechnung 42"), _hochladen(a, "boese.txt", EICAR)
    assert a.get(f"/api/v1/documents/{gut}/content").status_code == 409            # vor der Prüfung gesperrt
    lauf = scan_pending(rw.engines, build_storage(settings), ClamdClient("127.0.0.1", clamd.port, timeout=5))
    assert (lauf.clean, lauf.infected, lauf.pending, lauf.failed_tenants) == (1, 1, 0, [])
    assert _status(rw, gut) == "clean" and _status(rw, boese) == "infected"
    r = a.get(f"/api/v1/documents/{gut}/content")
    assert r.status_code == 200 and r.content == b"Rechnung 42"
    assert a.get(f"/api/v1/documents/{boese}/content").status_code == 409
    aktionen = db(rw.engines, "SELECT data->>'result', data->>'signature' FROM audit_events "
                              "WHERE action = 'document.scanned' ORDER BY data->>'result'")
    assert aktionen == [("clean", None), ("infected", "Eicar-Signature")]
    assert scan_pending(rw.engines, build_storage(settings), ClamdClient("127.0.0.1", clamd.port)).clean == 0  # idempotent


@pytest.mark.parametrize("antwort", [b"INSTREAM size limit exceeded. ERROR\0", b"stream: OK FOUND?\0", b"\0", b""])
def test_unklare_antwort_bleibt_in_quarantaene(rw: RbacWorld, settings: Any, antwort: bytes) -> None:
    """Größenlimit, Fehlertext, leere oder abgebrochene Antwort: nie „sauber"."""
    ref = _hochladen(rw.client(rw.admin), "a.txt", b"Inhalt")
    f = FakeClamd(antwort=antwort)
    try:
        lauf = scan_pending(rw.engines, build_storage(settings), ClamdClient("127.0.0.1", f.port, timeout=5))
    finally:
        f.close()
    assert (lauf.clean, lauf.infected, lauf.pending) == (0, 0, 1) and _status(rw, ref) == "quarantined"


def test_scanner_weg_alles_bleibt_in_quarantaene(rw: RbacWorld, settings: Any) -> None:
    ref = _hochladen(rw.client(rw.admin), "a.txt", b"Inhalt")
    lauf = scan_pending(rw.engines, build_storage(settings), ClamdClient("127.0.0.1", 1, timeout=2))
    assert lauf.pending == 1 and lauf.clean == 0 and _status(rw, ref) == "quarantined"


def test_ausfall_mitten_im_stapel_verliert_nichts(rw: RbacWorld, settings: Any) -> None:
    a = rw.client(rw.admin)
    refs = [_hochladen(a, f"d{i}.txt", f"Inhalt {i}".encode()) for i in range(3)]
    f = FakeClamd(abbruch_nach=1)
    try:
        lauf = scan_pending(rw.engines, build_storage(settings), ClamdClient("127.0.0.1", f.port, timeout=5))
    finally:
        f.close()
    assert (lauf.clean, lauf.pending) == (1, 2)
    assert sorted(_status(rw, r) for r in refs) == ["clean", "quarantined", "quarantined"]   # Erstes bleibt geprüft


def test_firmen_getrennt_und_cli_ohne_scanner(rw: RbacWorld, clamd: FakeClamd, settings: Any) -> None:
    a_ref = _hochladen(rw.client(rw.admin), "a.txt", b"A")
    b_ref = _hochladen(rw.client(rw.admin_b), "b.txt", EICAR)
    lauf = scan_pending(rw.engines, build_storage(settings), ClamdClient("127.0.0.1", clamd.port))
    assert (lauf.clean, lauf.infected) == (1, 1)
    assert _status(rw, a_ref) == "clean"
    assert ok(rw.client(rw.admin_b).get(f"/api/v1/documents/{b_ref}"))["scan_status"] == "infected"
    assert rw.client(rw.admin).get(f"/api/v1/documents/{b_ref}").status_code == 404
    import subprocess
    import sys

    from tests.test_entrypoints import _umgebung
    r = subprocess.run([sys.executable, "-m", "ichq.cli", "documents-scan"], env=_umgebung(settings),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "ICHQ_CLAMD_HOST" in r.stderr
    env = {**_umgebung(settings), "ICHQ_CLAMD_HOST": "127.0.0.1", "ICHQ_CLAMD_PORT": str(clamd.port)}
    _hochladen(rw.client(rw.admin), "c.txt", b"C")
    r = subprocess.run([sys.executable, "-m", "ichq.cli", "documents-scan"], env=env, capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0 and "sauber 1 · infiziert 0 · wartend 0" in r.stdout, r.stderr[-400:]


def test_db_erlaubt_nur_uebergang_aus_der_quarantaene(rw: RbacWorld, clamd: FakeClamd, settings: Any) -> None:
    from sqlalchemy import exc, text

    from ichq.db.session import tenant_transaction
    ref = _hochladen(rw.client(rw.admin), "x.txt", EICAR)
    scan_pending(rw.engines, build_storage(settings), ClamdClient("127.0.0.1", clamd.port))
    for neu in ("clean", "quarantined"):                       # selbst die Worker-Rolle: nie aus „infected" heraus
        with pytest.raises(exc.DBAPIError, match="nicht erlaubt"), tenant_transaction(rw.engines.worker, rw.a) as s:
            s.execute(text("UPDATE documents SET scan_status = :n FROM objects o WHERE o.id = documents.id "
                           "AND o.public_id = :p"), {"n": neu, "p": ref})
    assert _status(rw, ref) == "infected"
    with pytest.raises(exc.ProgrammingError), tenant_transaction(rw.engines.worker, rw.a) as s:  # andere Spalten nicht
        s.execute(text("UPDATE documents SET storage_key = 'x'"))
    neu_ref = _hochladen(rw.client(rw.admin), "y.txt", b"y")
    with pytest.raises(exc.ProgrammingError), tenant_transaction(rw.engines.app, rw.a) as s:     # Web-App gar nicht
        s.execute(text("UPDATE documents SET scan_status = 'clean'"))
    assert _status(rw, neu_ref) == "quarantined"
    with tenant_transaction(rw.engines.worker, rw.b) as s:          # fremde Firma: jede Tabelle einzeln leer
        for tabelle in ("documents", "objects", "audit_events"):
            assert s.execute(text(f"SELECT count(*) FROM {tabelle} WHERE tenant_id = :a"), {"a": rw.a}).scalar() == 0
        assert s.execute(text("UPDATE documents SET scan_status = 'clean' WHERE tenant_id = :a"), {"a": rw.a}).rowcount == 0
