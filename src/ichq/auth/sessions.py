"""Serverseitige Sitzungen. Der Browser hält nur ein Zufallstoken; die Datenbank nur dessen Hash.

Ablauf einer Sitzung — was zuerst eintritt:
* absolute Grenze  ``expires_at`` (Standard 12 h nach Anmeldung, nie verlängert)
* Leerlauf          kein Aufruf seit ``session_idle_minutes`` (Standard 30)
* Widerruf          Abmelden, „überall abmelden", Passwortwechsel, Reset, Kontosperre, Deaktivierung
* Konto nicht mehr ``active``/``locked`` — wird bei JEDEM Aufruf geprüft

Jeder Wechsel der Berechtigungsstufe (Passwort → 2FA → Firma) erzeugt eine NEUE Sitzung mit neuem
Token; die alte wird widerrufen (Schutz gegen Session Fixation).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.auth import events
from ichq.auth.tokens import hash_token, new_token
from ichq.core.config import Settings
from ichq.core.ids import uuid7

TOUCH_SECONDS = 60   # last_seen höchstens einmal pro Minute schreiben


@dataclass(frozen=True)
class SessionInfo:
    id: uuid.UUID
    user_id: uuid.UUID
    stage: str
    active_tenant_id: uuid.UUID | None
    active_membership_id: uuid.UUID | None
    expires_at: datetime
    idle_expires_at: datetime
    mfa_attempts: int


def create(s: Session, settings: Settings, user_id: uuid.UUID, *, stage: str, ip: str | None, user_agent: str | None,
           tenant_id: uuid.UUID | None = None, membership_id: uuid.UUID | None = None,
           expires_at: datetime | None = None) -> tuple[str, uuid.UUID]:
    roh, h = new_token()
    sid = uuid7()
    dauer = settings.mfa_challenge_minutes if stage == "mfa_pending" else settings.session_absolute_hours * 60
    s.execute(text("""
        INSERT INTO auth_sessions(id, token_hash, user_id, stage, active_tenant_id, active_membership_id,
                                  ip, user_agent, expires_at)
        VALUES (:id, :h, :u, :st, :t, :m, :ip, :ua,
                COALESCE(CAST(:exp AS timestamptz), now() + make_interval(mins => :d)))"""),
              {"id": sid, "h": h, "u": user_id, "st": stage, "t": tenant_id, "m": membership_id, "ip": ip,
               "ua": (user_agent or "")[:200] or None, "exp": expires_at, "d": dauer})
    return roh, sid


def load(s: Session, settings: Settings, roh: str | None, *, touch: bool = True) -> SessionInfo | None:
    """Sitzung prüfen. Abgelaufene werden dabei widerrufen und protokolliert."""
    if not roh or len(roh) > 128:
        return None
    zeile = s.execute(text("""
        SELECT a.id, a.user_id, a.stage, a.active_tenant_id, a.active_membership_id, a.expires_at,
               a.last_seen_at + make_interval(mins => :idle) AS idle_expires_at, a.mfa_attempts,
               a.last_seen_at < now() - make_interval(secs => :touch) AS touch_faellig,
               now() >= a.expires_at AS absolut_abgelaufen,
               now() >= a.last_seen_at + make_interval(mins => :idle) AS idle_abgelaufen,
               u.status, a.ip
        FROM auth_sessions a JOIN users u ON u.id = a.user_id
        WHERE a.token_hash = :h AND a.revoked_at IS NULL"""),
        {"h": hash_token(roh), "idle": settings.session_idle_minutes, "touch": TOUCH_SECONDS}).one_or_none()
    if zeile is None:
        return None
    grund = ("absolute_timeout" if zeile.absolut_abgelaufen else
             "idle_timeout" if zeile.idle_abgelaufen and zeile.stage == "full" else
             f"account_{zeile.status}" if zeile.status not in ("active", "locked") else None)
    if grund:
        revoke(s, zeile.id, grund)
        events.record(s, "session_ended", user_id=zeile.user_id, session_id=zeile.id, ip=zeile.ip, reason=grund)
        return None
    if touch and zeile.touch_faellig:
        s.execute(text("UPDATE auth_sessions SET last_seen_at = now() WHERE id = :id"), {"id": zeile.id})
    return SessionInfo(zeile.id, zeile.user_id, zeile.stage, zeile.active_tenant_id, zeile.active_membership_id,
                       zeile.expires_at, zeile.idle_expires_at, zeile.mfa_attempts)


def revoke(s: Session, session_id: uuid.UUID, reason: str) -> None:
    s.execute(text("UPDATE auth_sessions SET revoked_at = now(), revoke_reason = :r "
                   "WHERE id = :id AND revoked_at IS NULL"), {"id": session_id, "r": reason[:40]})


def revoke_all(s: Session, user_id: uuid.UUID, reason: str, except_id: uuid.UUID | None = None) -> int:
    res = s.execute(text("""UPDATE auth_sessions SET revoked_at = now(), revoke_reason = :r
                            WHERE user_id = :u AND revoked_at IS NULL AND (CAST(:x AS uuid) IS NULL OR id <> :x)"""),
                    {"u": user_id, "r": reason[:40], "x": except_id})
    return int(getattr(res, "rowcount", 0) or 0)


def rotate(s: Session, settings: Settings, alt: SessionInfo, reason: str, *, ip: str | None, user_agent: str | None,
           tenant_id: uuid.UUID | None = None, membership_id: uuid.UUID | None = None,
           keep_expiry: bool = True) -> tuple[str, uuid.UUID]:
    """Neue Sitzung, alte widerrufen. Die absolute Grenze wandert NICHT mit nach hinten."""
    revoke(s, alt.id, reason)
    return create(s, settings, alt.user_id, stage="full", ip=ip, user_agent=user_agent, tenant_id=tenant_id,
                  membership_id=membership_id, expires_at=alt.expires_at if keep_expiry else None)
