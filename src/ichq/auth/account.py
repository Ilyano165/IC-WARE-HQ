"""Passwort ändern, Passwort zurücksetzen, Kontostatus, 2FA verwalten.

Wie in ``login.py``: fachliche Fehlschläge als ``Outcome``, nie als Ausnahme in der Transaktion.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from ichq.auth import events, sessions, throttle, totp
from ichq.auth.login import Outcome, normalize_login
from ichq.auth.passwords import check_policy, hash_password, verify_password
from ichq.auth.tokens import hash_token, keyed_hash, new_recovery_code, new_token, normalize_recovery_code
from ichq.core.config import Settings
from ichq.core.ids import uuid7

STATUS = ("pending", "active", "locked", "suspended", "deactivated")
RECOVERY_CODES = 10


def _user(s: Session, user_id: uuid.UUID) -> Any:
    return s.execute(text("""SELECT id, email, username, status, password_hash, totp_secret_enc, totp_pending_enc,
                                    totp_enabled_at, totp_last_step
                             FROM users WHERE id = :id FOR UPDATE"""), {"id": user_id}).one()


def _setze_passwort(s: Session, settings: Settings, user_id: uuid.UUID, neu: str) -> None:
    s.execute(text("""UPDATE users SET password_hash = :h, password_changed_at = now(), failed_logins = 0,
                      locked_until = NULL,
                      status = CASE WHEN status IN ('pending','locked') THEN 'active' ELSE status END
                      WHERE id = :id"""), {"h": hash_password(settings, neu), "id": user_id})


def change_password(s: Session, settings: Settings, current: sessions.SessionInfo, old: str, new: str, *,
                    ip: str, user_agent: str | None) -> Outcome:
    u = _user(s, current.user_id)
    stimmt, _ = verify_password(settings, u.password_hash, old)
    if not stimmt:
        events.record(s, "password_change_failed", user_id=current.user_id, session_id=current.id, ip=ip,
                      reason="bad_password")
        return Outcome(False, "invalid_credentials")
    verstoss = check_policy(new, email=u.email, username=u.username)
    if verstoss:
        return Outcome(False, "password_policy", data={"policy": verstoss.code, "message": verstoss.message})
    _setze_passwort(s, settings, current.user_id, new)
    n = sessions.revoke_all(s, current.user_id, "password_changed", except_id=current.id)
    roh, sid = sessions.rotate(s, settings, current, "password_changed", ip=ip, user_agent=user_agent,
                               tenant_id=current.active_tenant_id, membership_id=current.active_membership_id)
    s.execute(text("UPDATE password_reset_tokens SET invalidated_at = now() "
                   "WHERE user_id = :u AND used_at IS NULL AND invalidated_at IS NULL"), {"u": current.user_id})
    events.record(s, "password_changed", user_id=current.user_id, session_id=sid, ip=ip, other_sessions_ended=n)
    return Outcome(True, token=roh, session_id=sid)


def request_reset(s: Session, settings: Settings, login_name: str, *,
                  ip: str) -> tuple[Outcome, str | None, str | None]:
    """Gibt (Ergebnis, roher Token oder None, E-Mail oder None) zurück. Die Antwort an den Client ist IMMER
    gleich — ob es das Konto gibt, erfährt niemand. Der rohe Token verlässt diese Funktion nur in Richtung
    E-Mail-Versand und wird nirgends gespeichert oder geloggt."""
    ident = normalize_login(login_name)
    subjekt = keyed_hash(settings.session_secret.get_secret_value(), "reset:" + ident)
    if throttle.is_throttled(s, settings, "reset", subjekt, ip):
        events.record(s, "password_reset_throttled", ip=ip)
        return Outcome(True), None, None             # nach außen identisch
    throttle.record_attempt(s, "reset", subjekt, ip, False)   # jede Anfrage zählt
    u = s.execute(text("SELECT id, email, status FROM users WHERE lower(email) = :i OR lower(username) = :i"),
                  {"i": ident}).one_or_none()
    if u is None or u.status not in ("pending", "active", "locked"):
        events.record(s, "password_reset_requested", user_id=u.id if u else None, ip=ip,
                      delivered=False, reason="no_eligible_account")
        return Outcome(True), None, None
    s.execute(text("UPDATE password_reset_tokens SET invalidated_at = now() "
                   "WHERE user_id = :u AND used_at IS NULL AND invalidated_at IS NULL"), {"u": u.id})
    roh, h = new_token()
    s.execute(text("""INSERT INTO password_reset_tokens(id, token_hash, user_id, expires_at)
                      VALUES (:id, :h, :u, now() + make_interval(mins => :m))"""),
              {"id": uuid7(), "h": h, "u": u.id, "m": settings.password_reset_minutes})
    events.record(s, "password_reset_requested", user_id=u.id, ip=ip, delivered=True)
    return Outcome(True), roh, u.email


def confirm_reset(s: Session, settings: Settings, token: str, new: str, *, ip: str) -> Outcome:
    if not token or len(token) > 128:
        return Outcome(False, "invalid_token")
    t = s.execute(text("""
        SELECT r.id, r.user_id, u.email, u.username, u.status,
               r.used_at IS NULL AND r.invalidated_at IS NULL AND r.expires_at > now() AS gueltig
        FROM password_reset_tokens r JOIN users u ON u.id = r.user_id
        WHERE r.token_hash = :h FOR UPDATE OF r"""), {"h": hash_token(token)}).one_or_none()
    if t is None or not t.gueltig or t.status not in ("pending", "active", "locked"):
        events.record(s, "password_reset_failed", user_id=t.user_id if t else None, ip=ip,
                      reason="unknown" if t is None else ("not_valid" if not t.gueltig else f"status_{t.status}"))
        return Outcome(False, "invalid_token")
    verstoss = check_policy(new, email=t.email, username=t.username)
    if verstoss:   # Token bleibt gültig — der Nutzer darf es mit einem besseren Passwort erneut versuchen
        return Outcome(False, "password_policy", data={"policy": verstoss.code, "message": verstoss.message})
    benutzt = s.execute(text("UPDATE password_reset_tokens SET used_at = now() WHERE id = :id AND used_at IS NULL "
                             "RETURNING id"), {"id": t.id}).scalar()
    if benutzt is None:
        return Outcome(False, "invalid_token")
    _setze_passwort(s, settings, t.user_id, new)
    n = sessions.revoke_all(s, t.user_id, "password_reset")
    events.record(s, "password_reset_completed", user_id=t.user_id, ip=ip, sessions_ended=n)
    return Outcome(True)


def set_initial_password(s: Session, settings: Settings, user_id: uuid.UUID, new: str, *, actor: str) -> Outcome:
    """Für den Betreiber (CLI): erstes Passwort setzen. Gleiche Regel wie überall."""
    u = _user(s, user_id)
    verstoss = check_policy(new, email=u.email, username=u.username)
    if verstoss:
        return Outcome(False, "password_policy", data={"policy": verstoss.code, "message": verstoss.message})
    _setze_passwort(s, settings, user_id, new)
    sessions.revoke_all(s, user_id, "password_set_by_operator")
    events.record(s, "password_set_by_operator", user_id=user_id, actor=actor)
    return Outcome(True)


def set_status(s: Session, user_id: uuid.UUID, new_status: str, *, actor: str, reason: str) -> Outcome:
    if new_status not in STATUS or not reason.strip():
        return Outcome(False, "invalid_status")
    u = _user(s, user_id)
    if new_status == "active" and u.password_hash is None:
        return Outcome(False, "password_required")
    s.execute(text("""UPDATE users SET status = :st, failed_logins = 0,
                      locked_until = NULL WHERE id = :id"""), {"st": new_status, "id": user_id})
    n = 0
    if new_status != "active":
        n = sessions.revoke_all(s, user_id, f"account_{new_status}")
        s.execute(text("UPDATE password_reset_tokens SET invalidated_at = now() "
                       "WHERE user_id = :u AND used_at IS NULL AND invalidated_at IS NULL"), {"u": user_id})
    events.record(s, "account_status_changed", user_id=user_id, actor=actor, reason=reason,
                  old=u.status, new=new_status, sessions_ended=n)
    return Outcome(True)


# ---------- 2FA ----------
def totp_setup(s: Session, settings: Settings, current: sessions.SessionInfo, password: str, *, ip: str) -> Outcome:
    u = _user(s, current.user_id)
    if not verify_password(settings, u.password_hash, password)[0]:
        events.record(s, "totp_setup_failed", user_id=current.user_id, session_id=current.id, ip=ip,
                      reason="bad_password")
        return Outcome(False, "invalid_credentials")
    if u.totp_enabled_at:
        return Outcome(False, "totp_already_enabled")
    geheimnis = totp.new_secret()
    s.execute(text("UPDATE users SET totp_pending_enc = :g WHERE id = :id"),
              {"g": totp.encrypt(settings.secret_key.get_secret_value(), geheimnis, str(u.id)),
               "id": current.user_id})
    events.record(s, "totp_setup_started", user_id=current.user_id, session_id=current.id, ip=ip)
    return Outcome(True, data={"secret": geheimnis,
                               "otpauth_uri": totp.otpauth_uri(geheimnis, u.email)})


def _neue_recovery_codes(s: Session, settings: Settings, user_id: uuid.UUID) -> list[str]:
    s.execute(text("DELETE FROM recovery_codes WHERE user_id = :u"), {"u": user_id})
    codes = [new_recovery_code() for _ in range(RECOVERY_CODES)]
    key = settings.session_secret.get_secret_value()
    for c in codes:
        s.execute(text("INSERT INTO recovery_codes(id, user_id, code_hash) VALUES (:id, :u, :h)"),
                  {"id": uuid7(), "u": user_id, "h": keyed_hash(key, "recovery:" + normalize_recovery_code(c))})
    return codes


def totp_enable(s: Session, settings: Settings, current: sessions.SessionInfo, code: str, *, ip: str) -> Outcome:
    u = _user(s, current.user_id)
    if not u.totp_pending_enc or u.totp_enabled_at:
        return Outcome(False, "totp_not_pending")
    geheimnis = totp.decrypt(settings.secret_key.get_secret_value(), u.totp_pending_enc, str(u.id))
    schritt = totp.verify(geheimnis, code, None)
    if schritt is None:
        events.record(s, "totp_enable_failed", user_id=current.user_id, session_id=current.id, ip=ip)
        return Outcome(False, "mfa_invalid")
    s.execute(text("""UPDATE users SET totp_secret_enc = totp_pending_enc, totp_pending_enc = NULL,
                      totp_enabled_at = now(), totp_last_step = :st WHERE id = :id"""),
              {"st": schritt, "id": current.user_id})
    codes = _neue_recovery_codes(s, settings, current.user_id)
    n = sessions.revoke_all(s, current.user_id, "totp_enabled", except_id=current.id)
    events.record(s, "totp_enabled", user_id=current.user_id, session_id=current.id, ip=ip, other_sessions_ended=n)
    return Outcome(True, data={"recovery_codes": codes})


def _zweiter_faktor(settings: Settings, u: Any, password: str, code: str) -> int | None:
    """Passwort UND aktueller TOTP-Code. Gibt den verwendeten Zeitschritt zurück oder None."""
    if not verify_password(settings, u.password_hash, password)[0]:
        return None
    geheimnis = totp.decrypt(settings.secret_key.get_secret_value(), u.totp_secret_enc, str(u.id))
    return totp.verify(geheimnis, code, u.totp_last_step)


def totp_disable(s: Session, settings: Settings, current: sessions.SessionInfo, password: str, code: str, *,
                 ip: str) -> Outcome:
    u = _user(s, current.user_id)
    if not u.totp_enabled_at:
        return Outcome(False, "totp_not_enabled")
    if _zweiter_faktor(settings, u, password, code) is None:
        events.record(s, "totp_disable_failed", user_id=current.user_id, session_id=current.id, ip=ip)
        return Outcome(False, "mfa_invalid")
    s.execute(text("""UPDATE users SET totp_secret_enc = NULL, totp_pending_enc = NULL, totp_enabled_at = NULL,
                      totp_last_step = NULL WHERE id = :id"""), {"id": current.user_id})
    s.execute(text("DELETE FROM recovery_codes WHERE user_id = :u"), {"u": current.user_id})
    events.record(s, "totp_disabled", user_id=current.user_id, session_id=current.id, ip=ip)
    return Outcome(True)


def regenerate_recovery_codes(s: Session, settings: Settings, current: sessions.SessionInfo, password: str,
                              code: str, *, ip: str) -> Outcome:
    u = _user(s, current.user_id)
    if not u.totp_enabled_at:
        return Outcome(False, "totp_not_enabled")
    schritt = _zweiter_faktor(settings, u, password, code)
    if schritt is None:
        events.record(s, "recovery_codes_failed", user_id=current.user_id, session_id=current.id, ip=ip)
        return Outcome(False, "mfa_invalid")
    s.execute(text("UPDATE users SET totp_last_step = :st WHERE id = :id"), {"st": schritt, "id": current.user_id})
    codes = _neue_recovery_codes(s, settings, current.user_id)
    events.record(s, "recovery_codes_regenerated", user_id=current.user_id, session_id=current.id, ip=ip)
    return Outcome(True, data={"recovery_codes": codes})
