"""Anmeldung, 2FA-Schritt, Abmelden, Firmenauswahl.

WICHTIG: Diese Funktionen werfen bei fachlichen Fehlschlägen KEINE Ausnahme, sondern geben ein
``Outcome`` zurück. Eine Ausnahme rollt die Transaktion zurück — dann wäre der Fehlversuch nicht
gespeichert und die Brute-Force-Sperre wirkungslos. Die API wirft erst nach dem Commit.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.auth import events, sessions, throttle, totp
from ichq.auth.passwords import hash_password, verify_password
from ichq.auth.tokens import hash_token, keyed_hash, normalize_recovery_code
from ichq.core.config import Settings

MFA_MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class Outcome:
    ok: bool
    error: str | None = None             # feste Kennung, nie ein Text mit Details
    token: str | None = None
    session_id: uuid.UUID | None = None
    mfa_required: bool = False
    data: dict[str, Any] = field(default_factory=dict)


def normalize_login(login: str) -> str:
    return login.strip().lower()[:254]


def login(s: Session, settings: Settings, login_name: str, password: str, *, ip: str,
          user_agent: str | None) -> Outcome:
    ident = normalize_login(login_name)
    subjekt = keyed_hash(settings.session_secret.get_secret_value(), "login:" + ident)
    if throttle.is_throttled(s, settings, "login", subjekt, ip):
        events.record(s, "login_throttled", ip=ip)
        return Outcome(False, "too_many_attempts", data={"retry_after": settings.throttle_window_minutes * 60})

    u = s.execute(text("""
        SELECT id, status, password_hash, failed_logins, totp_enabled_at,
               -- gesperrt: automatische Sperre läuft noch ODER Betreiber-Sperre (ohne Ablauf)
               status = 'locked' AND (locked_until IS NULL OR locked_until > now()) AS gesperrt
        FROM users WHERE lower(email) = :i OR lower(username) = :i FOR UPDATE"""), {"i": ident}).one_or_none()
    stimmt, neu_hashen = verify_password(settings, u.password_hash if u else None, password)

    grund = None
    if u is None:
        grund = "unknown_account"
    elif u.gesperrt:
        grund = "locked"
    elif u.status in ("pending", "suspended", "deactivated"):
        grund = f"status_{u.status}"
    elif not stimmt:
        grund = "bad_password"

    if grund:
        throttle.record_attempt(s, "login", subjekt, ip, False)
        if grund == "bad_password" and u is not None:
            fehler = u.failed_logins + 1
            if fehler >= settings.login_max_failures:
                s.execute(text("""UPDATE users SET failed_logins = :f, status = 'locked',
                                  locked_until = now() + make_interval(mins => :m) WHERE id = :id"""),
                          {"f": fehler, "m": settings.lockout_minutes, "id": u.id})
                events.record(s, "account_locked", user_id=u.id, ip=ip, reason="too_many_failures",
                              minutes=settings.lockout_minutes)
            else:
                s.execute(text("UPDATE users SET failed_logins = :f WHERE id = :id"), {"f": fehler, "id": u.id})
        events.record(s, "login_failed", user_id=u.id if u else None, ip=ip, reason=grund)
        return Outcome(False, "invalid_credentials")   # immer dieselbe Antwort — verrät nichts über das Konto

    assert u is not None
    if u.status == "locked":                 # automatische Sperre ist abgelaufen
        events.record(s, "account_unlocked", user_id=u.id, ip=ip, reason="lock_expired")
    s.execute(text("""UPDATE users SET failed_logins = 0, status = 'active', locked_until = NULL,
                      last_login_at = now() WHERE id = :id"""), {"id": u.id})
    if neu_hashen:
        s.execute(text("UPDATE users SET password_hash = :h WHERE id = :id"),
                  {"h": hash_password(settings, password), "id": u.id})
    throttle.record_attempt(s, "login", subjekt, ip, True)

    stufe = "mfa_pending" if u.totp_enabled_at else "full"
    roh, sid = sessions.create(s, settings, u.id, stage=stufe, ip=ip, user_agent=user_agent)
    events.record(s, "mfa_required" if stufe == "mfa_pending" else "login_succeeded", user_id=u.id,
                  session_id=sid, ip=ip)
    return Outcome(True, token=roh, session_id=sid, mfa_required=stufe == "mfa_pending")


def verify_mfa(s: Session, settings: Settings, challenge: sessions.SessionInfo, code: str, *, ip: str,
               user_agent: str | None) -> Outcome:
    if challenge.stage != "mfa_pending":
        return Outcome(False, "mfa_invalid")
    u = s.execute(text("SELECT id, totp_secret_enc, totp_last_step FROM users WHERE id = :id FOR UPDATE"),
                  {"id": challenge.user_id}).one()
    schritt = None
    if u.totp_secret_enc:
        geheimnis = totp.decrypt(settings.secret_key.get_secret_value(), u.totp_secret_enc, str(u.id))
        schritt = totp.verify(geheimnis, code, u.totp_last_step)
    recovery = None
    if schritt is None and len(normalize_recovery_code(code)) == 10:
        recovery = s.execute(text("""UPDATE recovery_codes SET used_at = now()
                                     WHERE user_id = :u AND code_hash = :h AND used_at IS NULL RETURNING id"""),
                             {"u": u.id, "h": keyed_hash(settings.session_secret.get_secret_value(),
                                                         "recovery:" + normalize_recovery_code(code))}).scalar()
    if schritt is None and recovery is None:
        versuche = challenge.mfa_attempts + 1
        s.execute(text("UPDATE auth_sessions SET mfa_attempts = :n WHERE id = :id"),
                  {"n": versuche, "id": challenge.id})
        events.record(s, "mfa_failed", user_id=u.id, session_id=challenge.id, ip=ip, attempt=versuche)
        if versuche >= MFA_MAX_ATTEMPTS:
            sessions.revoke(s, challenge.id, "mfa_attempts_exceeded")
            events.record(s, "mfa_locked_out", user_id=u.id, session_id=challenge.id, ip=ip)
        return Outcome(False, "mfa_invalid")
    if schritt is not None:
        s.execute(text("UPDATE users SET totp_last_step = :st WHERE id = :id"), {"st": schritt, "id": u.id})
    roh, sid = sessions.rotate(s, settings, challenge, "mfa_completed", ip=ip, user_agent=user_agent,
                               keep_expiry=False)
    if recovery is not None:
        uebrig = s.execute(text("SELECT count(*) FROM recovery_codes WHERE user_id = :u AND used_at IS NULL"),
                           {"u": u.id}).scalar()
        events.record(s, "recovery_code_used", user_id=u.id, session_id=sid, ip=ip, remaining=uebrig)
    events.record(s, "login_succeeded", user_id=u.id, session_id=sid, ip=ip, mfa=True,
                  method="recovery_code" if recovery else "totp")
    return Outcome(True, token=roh, session_id=sid)


def logout(s: Session, current: sessions.SessionInfo, *, ip: str) -> None:
    sessions.revoke(s, current.id, "logout")
    events.record(s, "logout", user_id=current.user_id, session_id=current.id, ip=ip)


def logout_all(s: Session, current: sessions.SessionInfo, *, ip: str) -> int:
    n = sessions.revoke_all(s, current.user_id, "logout_all")
    events.record(s, "logout_all", user_id=current.user_id, session_id=current.id, ip=ip, sessions=n)
    return n


def memberships(s: Session) -> list[dict[str, Any]]:
    """Firmen des Kontos. Läuft in ``auth_transaction(user_id=...)`` — RLS zeigt nur eigene Mitgliedschaften."""
    rows = s.execute(text("""
        SELECT t.id AS tenant_id, t.slug, t.name, t.status AS tenant_status, m.id AS membership_id,
               m.status AS membership_status
        FROM memberships m JOIN tenants t ON t.id = m.tenant_id ORDER BY t.name""")).mappings().all()
    return [dict(r) for r in rows]


def select_tenant(s: Session, settings: Settings, current: sessions.SessionInfo, tenant_id: uuid.UUID, *,
                  ip: str, user_agent: str | None) -> Outcome:
    """Wählt die Firma für die Sitzung. Prüft Mitgliedschaft — vergibt KEINE Rechte (das macht ichq.authz)."""
    m = s.execute(text("""
        SELECT m.id FROM memberships m JOIN tenants t ON t.id = m.tenant_id
        WHERE m.tenant_id = :t AND m.user_id = :u AND m.status = 'active' AND t.status IN ('active','paused')"""),
        {"t": tenant_id, "u": current.user_id}).scalar()
    if m is None:
        events.record(s, "tenant_selection_denied", user_id=current.user_id, session_id=current.id, ip=ip)
        return Outcome(False, "tenant_forbidden")
    roh, sid = sessions.rotate(s, settings, current, "tenant_selected", ip=ip, user_agent=user_agent,
                               tenant_id=tenant_id, membership_id=m)
    events.record(s, "tenant_selected", user_id=current.user_id, session_id=sid, ip=ip, tenant_id=str(tenant_id))
    return Outcome(True, token=roh, session_id=sid)


def token_hash(roh: str) -> bytes:
    return hash_token(roh)
