"""Betreiber und Einrichtungscodes (ADR-021). Alles in der Plattform-Transaktion.

* **Betreiber** dürfen Firmen anlegen und verwalten — sonst nichts. In einer Firma haben sie nur die Rechte ihrer
  Mitgliedschaft dort (Authentifizierung ≠ Autorisierung bleibt). Der letzte Betreiber lässt sich nicht entfernen.
* **Einrichtungscode:** Solange es keinen Betreiber gibt, richtet ein einmaliger Code die Installation in der
  Oberfläche ein. Er entsteht nur auf dem Server (``ichq setup-code``), wird nur als Hash gespeichert, läuft ab und
  ist nach dem Einlösen verbraucht. Die Antwort auf einen falschen Code verrät nicht, warum er nicht gilt.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.audit.service import record_platform
from ichq.core.errors import Conflict, NotFound, PermissionDenied
from ichq.core.ids import uuid7

CODE_STUNDEN = 24


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().encode()).hexdigest()


def is_operator(s: Session, user_id: uuid.UUID) -> bool:
    return s.execute(text("SELECT 1 FROM platform_operators WHERE user_id = :u"), {"u": user_id}).scalar() is not None


def setup_needed(s: Session) -> bool:
    """Ersteinrichtung offen = es gibt noch keinen Betreiber."""
    return s.execute(text("SELECT 1 FROM platform_operators LIMIT 1")).scalar() is None


def operators(s: Session) -> list[dict[str, Any]]:
    rows = s.execute(text("""SELECT u.id, u.email, u.display_name, u.status, o.created_at, o.created_by
                             FROM platform_operators o JOIN users u ON u.id = o.user_id
                             ORDER BY o.created_at, u.email""")).mappings()
    return [dict(r) for r in rows]


def user_by_email(s: Session, email: str) -> Any:
    return s.execute(text("SELECT id, email, display_name, status FROM users WHERE lower(email) = lower(:e)"),
                     {"e": email.strip()}).one_or_none()


def add_operator(s: Session, user_id: uuid.UUID, *, actor: str) -> bool:
    """Gibt False zurück, wenn das Konto schon Betreiber ist."""
    neu = s.execute(text("""INSERT INTO platform_operators(user_id, created_by) VALUES (:u, :a)
                            ON CONFLICT (user_id) DO NOTHING RETURNING user_id"""),
                    {"u": user_id, "a": actor[:120]}).scalar()
    if neu is not None:
        record_platform(s, "operator.added", actor=actor, data={"user_id": str(user_id)})
    return neu is not None


def remove_operator(s: Session, user_id: uuid.UUID, *, actor: str) -> None:
    # Sperre statt FOR UPDATE: die Plattform-Rolle hat bewusst kein UPDATE-Recht auf dieser Tabelle.
    s.execute(text("SELECT pg_advisory_xact_lock(hashtext('ichq.platform_operators'))"))
    alle = list(s.execute(text("SELECT user_id FROM platform_operators ORDER BY user_id")).scalars())
    if user_id not in alle:
        raise NotFound("Betreiber nicht gefunden")
    if len(alle) == 1:
        raise Conflict("Der letzte Betreiber kann nicht entfernt werden — erst einen weiteren hinzufügen")
    s.execute(text("DELETE FROM platform_operators WHERE user_id = :u"), {"u": user_id})
    record_platform(s, "operator.removed", actor=actor, data={"user_id": str(user_id)})


def new_setup_code(s: Session, *, actor: str) -> str:
    """Neuen Code ausstellen; ältere, unbenutzte Codes verfallen. Nur solange es keinen Betreiber gibt."""
    if not setup_needed(s):
        raise Conflict("Die Installation ist bereits eingerichtet — Firmen legt ein Betreiber in der Oberfläche an")
    s.execute(text("UPDATE platform_setup_codes SET used_at = now() WHERE used_at IS NULL"))
    code = secrets.token_urlsafe(24)
    s.execute(text("""INSERT INTO platform_setup_codes(id, code_hash, expires_at)
                      VALUES (:id, :h, now() + make_interval(hours => :st))"""),
              {"id": uuid7(), "h": _hash(code), "st": CODE_STUNDEN})
    record_platform(s, "setup.code_issued", actor=actor, data={"hours": CODE_STUNDEN})
    return code


def redeem_setup_code(s: Session, code: str) -> None:
    """Code prüfen und verbrauchen — in DERSELBEN Transaktion, in der die Einrichtung geschrieben wird: scheitert
    die Einrichtung, bleibt der Code gültig. Jede Ablehnung sieht gleich aus."""
    ok = None
    if code and len(code) <= 128 and setup_needed(s):
        ok = s.execute(text("""UPDATE platform_setup_codes SET used_at = now()
                               WHERE code_hash = :h AND used_at IS NULL AND expires_at > now() RETURNING id"""),
                       {"h": _hash(code)}).scalar()
    if ok is None:
        raise PermissionDenied("Einrichtungscode ungültig oder abgelaufen")
