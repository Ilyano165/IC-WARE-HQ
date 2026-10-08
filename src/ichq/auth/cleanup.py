"""Aufräumen der Anmeldedaten (M2-Restpunkt) — Datensparsamkeit und kleine Tabellen.

Gelöscht wird nur, was nicht mehr wirken kann UND älter als ``retention_days`` (Standard 30) ist:

| Tabelle | gelöscht, wenn … |
| --- | --- |
| ``login_attempts`` | Versuch älter als die Frist (Drosselfenster sind Minuten, Sperren Stunden) |
| ``auth_sessions`` | widerrufen oder abgelaufen, und das seit mehr als der Frist |
| ``password_reset_tokens`` | benutzt, ungültig gemacht oder abgelaufen, seit mehr als der Frist |
| ``recovery_codes`` | benutzt, seit mehr als der Frist (unbenutzte bleiben, sie sind noch gültig) |

``auth_events`` werden NIE gelöscht (nur anhängend; Aufbewahrungsfrist offen — docs/datenschutzkonzept.md).

Warum ein zeitgesteuerter Job und kein Outbox-Handler: Die Outbox ist mandantengebunden (Handler laufen im
Kontext EINER Firma), die Anmeldetabellen sind global und gehören der Rolle ``ichq_auth``. Ein Job mit eigener
Rolle, eigenem Advisory-Lock und systemd-Timer passt dazu — wie der Fälligkeits-Scan.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import text

from ichq.db.engine import Engines
from ichq.db.locks import AUTH_CLEANUP, job_lock
from ichq.db.session import auth_transaction

log = logging.getLogger("ichq.jobs.auth_cleanup")

_REGELN: dict[str, str] = {
    "login_attempts": "DELETE FROM login_attempts WHERE occurred_at < now() - make_interval(days => :d)",
    "auth_sessions": """DELETE FROM auth_sessions
        WHERE (revoked_at IS NOT NULL AND revoked_at < now() - make_interval(days => :d))
           OR (revoked_at IS NULL AND expires_at < now() - make_interval(days => :d))""",
    "password_reset_tokens": """DELETE FROM password_reset_tokens
        WHERE GREATEST(COALESCE(used_at, '-infinity'), COALESCE(invalidated_at, '-infinity'),
                       CASE WHEN expires_at < now() THEN expires_at ELSE '-infinity' END)
              < now() - make_interval(days => :d)
          AND (used_at IS NOT NULL OR invalidated_at IS NOT NULL OR expires_at < now())""",
    "recovery_codes": "DELETE FROM recovery_codes WHERE used_at < now() - make_interval(days => :d)",
}


@dataclass
class CleanupReport:
    skipped: bool = False
    deleted: dict[str, int] = field(default_factory=dict)


def run_cleanup(engines: Engines, retention_days: int = 30) -> CleanupReport:
    if not 1 <= retention_days <= 3650:
        raise ValueError("retention_days: 1–3650")
    bericht = CleanupReport()
    with job_lock(engines.auth, AUTH_CLEANUP) as erworben:
        if not erworben:
            bericht.skipped = True
            log.warning("auth_cleanup_uebersprungen", extra={"grund": "laeuft_bereits"})
            return bericht
        with auth_transaction(engines.auth) as s:     # eine Transaktion: alles oder nichts
            for tabelle, sql in _REGELN.items():
                res = s.execute(text(sql), {"d": retention_days})
                bericht.deleted[tabelle] = int(getattr(res, "rowcount", 0) or 0)
    log.info("auth_cleanup_fertig", extra={"geloescht": bericht.deleted, "frist_tage": retention_days})
    return bericht
