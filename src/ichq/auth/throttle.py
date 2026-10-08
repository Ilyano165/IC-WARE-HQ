"""Schutz gegen Durchprobieren. Liegt in PostgreSQL: überlebt Neustarts, gilt für alle Prozesse.

Drei Grenzen im Zeitfenster (Standard 15 Minuten):
* je IP:           ip_max_failures Fehlversuche → 429
* je Login-Name:   identifier_max_failures → 429 — auch für Namen ohne Konto, damit sich
                   bekannte und unbekannte Konten nicht unterscheiden lassen
* je Konto:        login_max_failures falsche Passwörter in Folge → Konto ``locked`` für lockout_minutes
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.core.config import Settings
from ichq.core.ids import uuid7


def record_attempt(s: Session, kind: str, subject_hash: bytes, ip: str, success: bool) -> None:
    s.execute(text("""INSERT INTO login_attempts(id, kind, subject_hash, ip, success)
                      VALUES (:id, :k, :h, :ip, :ok)"""),
              {"id": uuid7(), "k": kind, "h": subject_hash, "ip": ip, "ok": success})


def is_throttled(s: Session, settings: Settings, kind: str, subject_hash: bytes, ip: str) -> bool:
    fenster = settings.throttle_window_minutes
    zeile = s.execute(text("""
        SELECT
          (SELECT count(*) FROM login_attempts
            WHERE kind = :k AND ip = :ip AND NOT success
              AND occurred_at > now() - make_interval(mins => :w)) AS ip_fehler,
          (SELECT count(*) FROM login_attempts a
            WHERE a.kind = :k AND a.subject_hash = :h AND NOT a.success
              AND a.occurred_at > now() - make_interval(mins => :w)
              AND a.occurred_at > COALESCE((SELECT max(b.occurred_at) FROM login_attempts b
                                             WHERE b.kind = :k AND b.subject_hash = :h AND b.success),
                                            '-infinity')) AS name_fehler
    """), {"k": kind, "ip": ip, "h": subject_hash, "w": fenster}).one()
    return bool(zeile.ip_fehler >= settings.ip_max_failures or zeile.name_fehler >= settings.identifier_max_failures)


def purge_old(s: Session, days: int = 30) -> int:
    """Alte Versuche löschen (Datensparsamkeit). Für einen täglichen Job gedacht."""
    res = s.execute(text("DELETE FROM login_attempts WHERE occurred_at < now() - make_interval(days => :d)"),
                    {"d": days})
    return int(getattr(res, "rowcount", 0) or 0)
