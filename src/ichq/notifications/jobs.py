"""Fälligkeits-Scan als eigenständiger Job — unabhängig davon, WER ihn startet.

Heute startet ihn ein systemd-Timer (``deploy/systemd/``) über ``ichq notifications-scan``. Ein anderer
Scheduler (Cron, Kubernetes-CronJob, Worker-Zeitplan) ruft dieselbe Funktion ``run_scan`` auf — die Fachlogik
(Regeln in ``handlers.RULES``) bleibt unverändert.

* **Idempotent:** Jede Zustellung trägt einen ``dedup_key`` (z. B. ``overdue:<aufgabe>:<fälligkeit>``); ein
  erneuter Lauf am selben Tag stellt nichts doppelt zu (Unique-Index in der Datenbank, nicht nur Code).
* **Kein Parallellauf:** PostgreSQL-Advisory-Lock für die Dauer des Laufs. Läuft schon einer, endet der zweite
  sofort ohne Arbeit (``skipped``).
* **Fehler je Firma isoliert:** Scheitert eine Firma, wird ihre Transaktion zurückgerollt, geloggt (ohne Inhalte)
  und mit der nächsten weitergemacht. Das Ergebnis meldet die Zahl gescheiterter Firmen → Exitcode 1.
* **Nie firmenübergreifend:** je Firma eine eigene Mandanten-Transaktion.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import text

from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.notifications.handlers import scan

log = logging.getLogger("ichq.jobs.notifications_scan")
LOCK_KEY = 0x1C4A_5C40   # fester Schlüssel für pg_try_advisory_lock


@dataclass
class ScanReport:
    day: date
    skipped: bool = False
    tenants: int = 0
    delivered: int = 0
    failed: list[str] = field(default_factory=list)    # nur Firmen-IDs, keine Inhalte

    @property
    def ok(self) -> bool:
        return not self.failed


def run_scan(engines: Engines, day: date) -> ScanReport:
    bericht = ScanReport(day=day)
    with engines.platform.connect() as sperre:
        if not sperre.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar():
            bericht.skipped = True
            log.warning("notifications_scan_uebersprungen", extra={"grund": "laeuft_bereits"})
            return bericht
        try:
            with platform_transaction(engines.platform) as s:
                firmen: list[uuid.UUID] = list(s.scalars(text(
                    "SELECT id FROM tenants WHERE status = 'active' ORDER BY id")).all())
            for tid in firmen:
                t0 = time.perf_counter()
                try:
                    with tenant_transaction(engines.app, tid) as ts:
                        ergebnis = scan(ts, day)
                except Exception as e:   # eine Firma darf die anderen nicht aufhalten
                    bericht.failed.append(str(tid))
                    log.error("notifications_scan_firma_fehler",
                              extra={"tenant_id": str(tid), "fehler": e.__class__.__name__})
                    continue
                n = sum(ergebnis.values())
                bericht.tenants += 1
                bericht.delivered += n
                log.info("notifications_scan_firma", extra={"tenant_id": str(tid), "zugestellt": n,
                                                             "regeln": ergebnis,
                                                             "dauer_ms": int((time.perf_counter() - t0) * 1000)})
        finally:
            sperre.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            sperre.commit()
    log.info("notifications_scan_fertig", extra={"tag": day.isoformat(), "firmen": bericht.tenants,
                                                   "zugestellt": bericht.delivered, "fehler": len(bericht.failed)})
    return bericht
