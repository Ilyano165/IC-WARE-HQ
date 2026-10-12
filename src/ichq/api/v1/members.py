"""M3: Mitglieder, Einladungen, Firma verlassen."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field, StringConstraints
from starlette.concurrency import run_in_threadpool

from ichq.api.problems import problem
from ichq.api.security import TenantDB, authenticated, public, require, signed_in, tenant_db
from ichq.api.state import AppState, get_state
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, refs_for, writing
from ichq.auth.sessions import SessionInfo
from ichq.authz.service import Principal
from ichq.mail import templates
from ichq.mail.outbox import enqueue
from ichq.members import accept as invitations_accept
from ichq.members import service as members

router = APIRouter(prefix="/api/v1", tags=["members"])


class InviteIn(Strict):
    email: str = Field(min_length=3, max_length=254)
    title: str | None = Field(default=None, max_length=120)


class AcceptNewIn(Strict):
    token: str = Field(min_length=16, max_length=128)
    display_name: str = Field(min_length=1, max_length=120)
    # Passwörter nie kürzen: Login und Reset nehmen sie wörtlich (Audit F6)
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=1, max_length=512)


class AcceptExistingIn(Strict):
    token: str = Field(min_length=16, max_length=128)


@router.get("/members")
def list_members(p: Principal = Depends(require("users.read")), db: TenantDB = Depends(tenant_db),
                 status: Annotated[str | None, Query(pattern="^(active|suspended|left|invited)$")] = None,
                 q: Annotated[str | None, Query(min_length=1, max_length=100)] = None,
                 cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    """Mitglieder dieser Firma. Ohne ``status``: alle Zustände. E-Mail nur mit users.read (Route)."""
    with db() as s:
        rows, weiter = members.list_members(s, status=status, q=q, cursor=cursor, limit=limit)
        return {"items": [{"id": r.public_id, "display_name": r.display_name, "email": r.email, "status": r.status,
                           "title": r.title, "joined_at": r.created_at} for r in rows], "next_cursor": weiter}


@router.post("/members/{member}/deactivate")
def deactivate(member: str, p: Principal = Depends(require("users.deactivate")),
               db: TenantDB = Depends(tenant_db)) -> dict[str, str]:
    with writing(db) as s:
        m = members.deactivate(s, p, member)
        return {"id": m.public_id, "status": m.status}


@router.post("/membership/leave", status_code=204)
def leave(p: Principal = Depends(authenticated()), db: TenantDB = Depends(tenant_db)) -> Response:
    """Eigene Mitgliedschaft beenden. Die Sitzung verliert damit sofort den Zugriff auf die Firma."""
    with writing(db) as s:
        members.leave(s, p)
    return Response(status_code=204)


@router.get("/invitations")
def list_invitations(p: Principal = Depends(require("users.read")), db: TenantDB = Depends(tenant_db),
                     open_only: bool = True, cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    with db() as s:
        rows, weiter = members.list_invitations(s, open_only=open_only, cursor=cursor, limit=limit)
        refs = refs_for(s, {r[0].invited_by_membership_id for r in rows})
        return {"items": [{"id": i.public_id, "email": i.email, "title": i.title, "created_at": i.created_at,
                           "expires_at": i.expires_at, "expired": not gueltig, "accepted": i.accepted_at is not None,
                           "revoked": i.revoked_at is not None,
                           "invited_by": refs.get(i.invited_by_membership_id) if i.invited_by_membership_id else None}
                          for i, gueltig, *_ in rows], "next_cursor": weiter}


@router.post("/invitations", status_code=201)
def create_invitation(body: InviteIn, p: Principal = Depends(require("users.create")),
                      db: TenantDB = Depends(tenant_db), state: AppState = Depends(get_state)) -> Any:
    if not state.mail_enabled:
        return problem(503, "invitation_unavailable", detail="E-Mail-Versand ist auf diesem Server nicht eingerichtet.")
    basis = (state.settings.public_origin or "http://localhost").rstrip("/")
    with writing(db) as s:   # Einladung und Mail in EINER Transaktion: beides oder nichts
        inv, roh = members.invite(s, p, email=body.email, title=body.title)
        enqueue(s, kind="invitation", to=inv.email, tenant_id=p.tenant_id, expires_at=inv.expires_at,
                mail=templates.invitation(basis, roh, members.INVITATION_DAYS),
                secret_key=state.settings.secret_key.get_secret_value())
        return {"id": inv.public_id, "email": inv.email, "expires_at": inv.expires_at}


@router.delete("/invitations/{ref}", status_code=204)
def revoke_invitation(ref: str, p: Principal = Depends(require("users.create")),
                      db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        members.revoke(s, p, ref)
    return Response(status_code=204)


@router.post("/invitations/accept", status_code=201)
async def accept_new(body: AcceptNewIn, _: None = Depends(public("Einladung annehmen — neues Konto")),
                     state: AppState = Depends(get_state)) -> dict[str, str]:
    """Neues Konto. Gibt es zur E-Mail schon ein Konto: 409 ``account_exists`` → anmelden und accept-existing."""
    pid = await run_in_threadpool(invitations_accept.accept_new, state.engines, state.settings, body.token,
                                  display_name=body.display_name, password=body.password)
    return {"member": pid, "next": "login"}


@router.post("/invitations/accept-existing", status_code=201)
def accept_existing(body: AcceptExistingIn, current: SessionInfo = Depends(signed_in()),
                    state: AppState = Depends(get_state)) -> dict[str, str]:
    pid = invitations_accept.accept_existing(state.engines, body.token, user_id=current.user_id)
    return {"member": pid, "next": "select_tenant"}
