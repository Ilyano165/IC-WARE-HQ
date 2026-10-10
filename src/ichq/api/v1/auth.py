"""Authentifizierung unter /api/v1/auth. Das Token steht nur im Cookie, nie im Antworttext."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import text

from ichq.api.cookies import clear_session_cookie, client_ip, set_session_cookie
from ichq.api.problems import problem
from ichq.api.security import any_session, mfa_challenge, public, signed_in
from ichq.api.state import AppState, get_state
from ichq.auth import account
from ichq.auth import login as auth_login
from ichq.auth.login import Outcome
from ichq.auth.sessions import SessionInfo
from ichq.db.session import auth_transaction
from ichq.mail import templates
from ichq.mail.outbox import enqueue

router = APIRouter(prefix="/api/v1/auth")
STATUS = {"invalid_credentials": 401, "too_many_attempts": 429, "mfa_invalid": 401, "tenant_forbidden": 403,
          "password_policy": 422, "invalid_token": 400, "totp_already_enabled": 409, "totp_not_pending": 409,
          "totp_not_enabled": 409}
TEXT = {"invalid_credentials": "E-Mail/Benutzername oder Passwort ist falsch.",
        "too_many_attempts": "Zu viele Versuche. Bitte später erneut versuchen.",
        "mfa_invalid": "Der Bestätigungscode ist ungültig.",
        "tenant_forbidden": "Kein Zugriff auf diese Firma.",
        "invalid_token": "Der Link ist ungültig oder abgelaufen."}


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=512)


class CodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class TenantIn(BaseModel):
    tenant_id: uuid.UUID


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=512)
    new_password: str = Field(min_length=1, max_length=512)


class ResetRequestIn(BaseModel):
    login: str = Field(min_length=1, max_length=254)


class ResetConfirmIn(BaseModel):
    token: str = Field(min_length=16, max_length=128)
    new_password: str = Field(min_length=1, max_length=512)


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class PasswordCodeIn(BaseModel):
    password: str = Field(min_length=1, max_length=512)
    code: str = Field(min_length=6, max_length=16)


def _fehler(o: Outcome) -> JSONResponse:
    code = o.error or "error"
    extra: dict[str, Any] = {"policy": o.data.get("policy")} if code == "password_policy" else {}
    resp = problem(STATUS.get(code, 400), code, detail=o.data.get("message") or TEXT.get(code), **extra)
    if code == "too_many_attempts":
        resp.headers["Retry-After"] = str(o.data.get("retry_after", 900))
    return resp


def _mit_cookie(state: AppState, o: Outcome, body: dict[str, Any], *, mfa: bool = False) -> JSONResponse:
    resp = JSONResponse(body)
    dauer = state.settings.mfa_challenge_minutes * 60 if mfa else state.settings.session_absolute_hours * 3600
    assert o.token
    set_session_cookie(resp, state.settings, o.token, max_age=dauer)
    return resp


@router.post("/login")
def login(body: LoginIn, request: Request, _: None = Depends(public("Anmeldung")),
          state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        o = auth_login.login(s, state.settings, body.login, body.password, ip=client_ip(request),
                             user_agent=request.headers.get("user-agent"))
    if not o.ok:
        return _fehler(o)
    return _mit_cookie(state, o, {"status": "mfa_required" if o.mfa_required else "ok"}, mfa=o.mfa_required)


@router.post("/mfa")
def mfa(body: CodeIn, request: Request, challenge: SessionInfo = Depends(mfa_challenge()),
        state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        o = auth_login.verify_mfa(s, state.settings, challenge, body.code, ip=client_ip(request),
                                  user_agent=request.headers.get("user-agent"))
    return _mit_cookie(state, o, {"status": "ok"}) if o.ok else _fehler(o)


@router.post("/logout", status_code=204)
def logout(request: Request, current: SessionInfo = Depends(any_session()),
           state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        auth_login.logout(s, current, ip=client_ip(request))
    resp = Response(status_code=204)
    clear_session_cookie(resp, state.settings)
    return resp


@router.post("/logout-all", status_code=204)
def logout_all(request: Request, current: SessionInfo = Depends(signed_in()),
               state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        auth_login.logout_all(s, current, ip=client_ip(request))
    resp = Response(status_code=204)
    clear_session_cookie(resp, state.settings)
    return resp


@router.get("/session")
def session_info(current: SessionInfo = Depends(signed_in()), state: AppState = Depends(get_state)) -> dict[str, Any]:
    with auth_transaction(state.engines.auth, user_id=current.user_id) as s:
        u = s.execute(text("SELECT id, email, username, display_name, totp_enabled_at IS NOT NULL AS totp "
                           "FROM users WHERE id = :id"), {"id": current.user_id}).one()
        firmen = auth_login.memberships(s)
    return {"user": {"id": u.id, "email": u.email, "username": u.username, "display_name": u.display_name,
                     "totp_enabled": u.totp},
            "session": {"expires_at": current.expires_at, "idle_expires_at": current.idle_expires_at,
                        "active_tenant_id": current.active_tenant_id},
            "memberships": [{k: f[k] for k in ("tenant_id", "slug", "name", "tenant_status", "membership_status")}
                            for f in firmen]}


@router.post("/tenant")
def select_tenant(body: TenantIn, request: Request, current: SessionInfo = Depends(signed_in()),
                  state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth, user_id=current.user_id) as s:
        o = auth_login.select_tenant(s, state.settings, current, body.tenant_id, ip=client_ip(request),
                                     user_agent=request.headers.get("user-agent"))
    return _mit_cookie(state, o, {"status": "ok", "tenant_id": str(body.tenant_id)}) if o.ok else _fehler(o)


@router.post("/password")
def change_password(body: PasswordChangeIn, request: Request, current: SessionInfo = Depends(signed_in()),
                    state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        o = account.change_password(s, state.settings, current, body.current_password, body.new_password,
                                    ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    return _mit_cookie(state, o, {"status": "ok"}) if o.ok else _fehler(o)


@router.post("/password-reset/request", status_code=202)
def reset_request(body: ResetRequestIn, request: Request, tasks: BackgroundTasks,
                  _: None = Depends(public("Passwort vergessen")), state: AppState = Depends(get_state)) -> Response:
    if not state.mail_enabled:
        return problem(503, "password_reset_unavailable",
                       detail="Passwort-Reset ist auf diesem Server nicht eingerichtet.")
    with auth_transaction(state.engines.auth) as s:
        _o, roh, email = account.request_reset(s, state.settings, body.login, ip=client_ip(request))
    if roh and email:   # Einreihen NACH der Antwort: gleiche Antwortzeit für bekannte und unbekannte Konten
        tasks.add_task(_reset_mail_einreihen, state, email, roh)
    return Response(status_code=202)


def _reset_mail_einreihen(state: AppState, email: str, roh: str) -> None:
    """Token nur verschlüsselt in der Outbox; gültig so lange wie der Token selbst."""
    basis = (state.settings.public_origin or "http://localhost").rstrip("/")
    minuten = state.settings.password_reset_minutes
    with auth_transaction(state.engines.auth) as s:
        enqueue(s, kind="password_reset", to=email, mail=templates.password_reset(basis, roh, minuten),
                secret_key=state.settings.secret_key.get_secret_value(),
                expires_at=datetime.now(UTC) + timedelta(minutes=minuten))


@router.post("/password-reset/confirm", status_code=204)
def reset_confirm(body: ResetConfirmIn, request: Request, _: None = Depends(public("Passwort neu setzen")),
                  state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        o = account.confirm_reset(s, state.settings, body.token, body.new_password, ip=client_ip(request))
    return Response(status_code=204) if o.ok else _fehler(o)


@router.post("/2fa/setup")
def totp_setup(body: PasswordIn, request: Request, current: SessionInfo = Depends(signed_in()),
               state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        o = account.totp_setup(s, state.settings, current, body.password, ip=client_ip(request))
    return JSONResponse(o.data) if o.ok else _fehler(o)


@router.post("/2fa/enable")
def totp_enable(body: CodeIn, request: Request, current: SessionInfo = Depends(signed_in()),
                state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        o = account.totp_enable(s, state.settings, current, body.code, ip=client_ip(request))
    return JSONResponse(o.data) if o.ok else _fehler(o)


@router.post("/2fa/disable", status_code=204)
def totp_disable(body: PasswordCodeIn, request: Request, current: SessionInfo = Depends(signed_in()),
                 state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        o = account.totp_disable(s, state.settings, current, body.password, body.code, ip=client_ip(request))
    return Response(status_code=204) if o.ok else _fehler(o)


@router.post("/2fa/recovery-codes")
def recovery_codes(body: PasswordCodeIn, request: Request, current: SessionInfo = Depends(signed_in()),
                   state: AppState = Depends(get_state)) -> Response:
    with auth_transaction(state.engines.auth) as s:
        o = account.regenerate_recovery_codes(s, state.settings, current, body.password, body.code,
                                              ip=client_ip(request))
    return JSONResponse(o.data) if o.ok else _fehler(o)
