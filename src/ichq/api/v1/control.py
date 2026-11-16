"""Unternehmensverwaltung in der Oberfläche (ADR-021): Ersteinrichtung mit Einrichtungscode, Firmen anlegen,
bearbeiten, Status ändern, Module schalten, Administratoren zuweisen, Betreiber verwalten.

Alle Routen unter ``/platform`` tragen die Marke ``operator()``. Firmen werden nach außen über ihr Kürzel
(``slug``) angesprochen, Konten über ihre E-Mail — keine internen IDs.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import text

from ichq.api.security import operator, public
from ichq.api.state import AppState, get_state
from ichq.api.v1.common import Strict
from ichq.audit.service import record_platform
from ichq.auth.sessions import SessionInfo
from ichq.authz.flags import set_flag
from ichq.authz.guard import admins
from ichq.authz.registry import FLAGGABLE_MODULES
from ichq.authz.templates import install
from ichq.control import onboarding
from ichq.control import service as control
from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.tenancy import service as tenancy
from ichq.tenancy.service import UEBERGAENGE, TenantInfo

router = APIRouter(prefix="/api/v1", tags=["platform"])
STATUS_MUSTER = "^(pending|active|paused|suspended|deactivated)$"
STATUS_TEXT = {"pending": "angelegt", "active": "aktiv", "paused": "pausiert (nur lesen)", "suspended": "gesperrt",
               "deactivated": "deaktiviert (endgültig)"}


class CompanyFields(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    legal_name: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    language: str | None = Field(default=None, pattern="^(de|en)$")
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")


class CompanyIn(CompanyFields):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=3, max_length=48)
    modules_off: list[str] = Field(default_factory=list, max_length=40)


class AdminIn(Strict):
    """``self``: mein Konto · ``existing``: bestehendes Konto (E-Mail) · ``new``: neues Konto mit Startpasswort."""

    mode: str = Field(pattern="^(self|existing|new)$")
    email: str | None = Field(default=None, max_length=254)
    name: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, max_length=512)


class CompanyCreate(Strict):
    company: CompanyIn
    admin: AdminIn


class SetupIn(Strict):
    code: str = Field(min_length=8, max_length=128)
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=512)
    company: CompanyIn


class StatusIn(Strict):
    status: str = Field(pattern="^(active|paused|suspended|deactivated)$")
    reason: str = Field(min_length=3, max_length=500)


class ModuleIn(Strict):
    enabled: bool
    reason: str = Field(min_length=3, max_length=500)


class EmailIn(Strict):
    email: str = Field(min_length=3, max_length=254)


def _firma(c: CompanyIn) -> onboarding.Firma:
    return onboarding.Firma(name=c.name, slug=c.slug, legal_name=c.legal_name, timezone=c.timezone or "Europe/Berlin",
                            language=c.language or "de", currency=c.currency or "EUR",
                            modules_off=tuple(c.modules_off))


def _actor(state: AppState, info: SessionInfo) -> str:
    with platform_transaction(state.engines.platform) as s:
        mail = s.execute(text("SELECT email FROM users WHERE id = :u"), {"u": info.user_id}).scalar()
    return f"operator:{mail}"[:120]


def _out(t: TenantInfo) -> dict[str, Any]:
    return {"slug": t.slug, "name": t.name, "legal_name": t.legal_name, "status": t.status,
            "status_text": STATUS_TEXT[t.status], "timezone": t.timezone, "language": t.language,
            "currency": t.currency, "created_at": t.created_at,
            "next_status": sorted(UEBERGAENGE.get(t.status, frozenset()))}


def _team(state: AppState, t: TenantInfo) -> dict[str, Any]:
    """Mitgliederzahl und Administratoren — über die Mandanten-Transaktion der Firma (RLS)."""
    with tenant_transaction(state.engines.app, t.id) as s:
        zahl = s.execute(text("SELECT count(*) FROM memberships WHERE status = 'active'")).scalar_one()
        ids = admins(s)
        leute = s.execute(text("""SELECT u.email, u.display_name FROM memberships m JOIN users u ON u.id = m.user_id
                                  WHERE m.id = ANY(:ids) ORDER BY u.email"""), {"ids": ids}).mappings().all() \
            if ids else []
    return {"members": int(zahl), "admins": [dict(x) for x in leute]}


# ---- Ersteinrichtung (ohne Anmeldung, nur mit Einrichtungscode) ---------------------------------------------------
@router.get("/setup")
def setup_status(_: None = Depends(public("Ersteinrichtung: sagt nur, ob sie noch offen ist")),
                 state: AppState = Depends(get_state)) -> dict[str, Any]:
    with platform_transaction(state.engines.platform) as s:
        return {"needed": control.setup_needed(s)}


@router.post("/setup", status_code=201)
def setup(body: SetupIn, _: None = Depends(public("Ersteinrichtung: nur mit einmaligem Einrichtungscode")),
          state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Erstes Konto wird Betreiber und Company Admin der ersten Firma. Der Code wird dabei verbraucht."""
    t = onboarding.first_setup(state.engines, state.settings, code=body.code, firma=_firma(body.company),
                               admin=onboarding.Admin(email=body.email, name=body.name, password=body.password))
    return {"company": _out(t), "login": body.email.strip().lower()}


# ---- Firmen -------------------------------------------------------------------------------------------------------
@router.get("/platform/companies")
def list_companies(_: SessionInfo = Depends(operator()), state: AppState = Depends(get_state),
                   q: Annotated[str | None, Query(max_length=100)] = None,
                   status: Annotated[str | None, Query(pattern=STATUS_MUSTER)] = None,
                   limit: Annotated[int, Query(ge=1, le=200)] = 100,
                   offset: Annotated[int, Query(ge=0, le=100_000)] = 0) -> dict[str, Any]:
    wo: list[str] = ["true"]
    werte: dict[str, Any] = {"lim": limit + 1, "off": offset}
    if q:
        wo.append("(lower(name) LIKE :q OR slug LIKE :q OR lower(coalesce(legal_name, '')) LIKE :q)")
        werte["q"] = f"%{q.strip().lower()}%"
    if status:
        wo.append("status = :st")
        werte["st"] = status
    with platform_transaction(state.engines.platform) as s:
        ids = list(s.execute(text(f"SELECT id FROM tenants WHERE {' AND '.join(wo)} "   # noqa: S608 — feste Bausteine
                                  "ORDER BY lower(name), id LIMIT :lim OFFSET :off"), werte).scalars())
        firmen = [tenancy.get_tenant(s, i) for i in ids[:limit]]
        gesamt = s.execute(text("SELECT status, count(*) FROM tenants GROUP BY status")).all()
    return {"items": [_out(t) for t in firmen], "has_more": len(ids) > limit,
            "next_offset": offset + limit if len(ids) > limit else None,
            "counts": {st: int(n) for st, n in gesamt}}


@router.get("/platform/slug-suggestion")
def slug_suggestion(name: Annotated[str, Query(min_length=1, max_length=120)], _: SessionInfo = Depends(operator()),
                    state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Kürzel aus dem Namen ableiten und sagen, ob es noch frei ist."""
    basis = onboarding.slug_vorschlag(name)
    with platform_transaction(state.engines.platform) as s:
        belegt = set(s.execute(text("SELECT slug FROM tenants WHERE slug LIKE :p"), {"p": basis + "%"}).scalars())
    slug, n = basis, 2
    while slug in belegt or slug in tenancy.RESERVIERT:
        slug, n = f"{basis[:44]}-{n}", n + 1
    return {"slug": slug}


@router.get("/platform/accounts")
def account_lookup(email: Annotated[str, Query(min_length=3, max_length=254)], _: SessionInfo = Depends(operator()),
                   state: AppState = Depends(get_state)) -> dict[str, Any]:
    with platform_transaction(state.engines.platform) as s:
        u = control.user_by_email(s, email)
    return {"exists": u is not None, "display_name": u.display_name if u else None,
            "active": bool(u and u.status == "active")}


@router.post("/platform/companies", status_code=201)
def create_company(body: CompanyCreate, info: SessionInfo = Depends(operator()),
                   state: AppState = Depends(get_state)) -> dict[str, Any]:
    a = body.admin
    if a.mode == "self":
        admin = onboarding.Admin(user_id=info.user_id)
    else:
        if not a.email:
            raise ValidationFailed("E-Mail des Administrators fehlt")
        if a.mode == "existing":
            with platform_transaction(state.engines.platform) as s:
                u = control.user_by_email(s, a.email)
            if u is None:
                raise NotFound("Für diese E-Mail gibt es kein Konto")
            admin = onboarding.Admin(user_id=u.id)
        else:
            if not a.name or not a.password:
                raise ValidationFailed("Für ein neues Konto sind Name und Startpasswort nötig")
            admin = onboarding.Admin(email=a.email, name=a.name, password=a.password)
    t = onboarding.create_company(state.engines, state.settings, _firma(body.company), admin,
                                  actor=_actor(state, info))
    return {**_out(t), **_team(state, t)}


def _laden(state: AppState, slug: str) -> TenantInfo:
    with platform_transaction(state.engines.platform) as s:
        return tenancy.get_tenant_by_slug(s, slug)


@router.get("/platform/companies/{slug}")
def get_company(slug: str, _: SessionInfo = Depends(operator()),
                state: AppState = Depends(get_state)) -> dict[str, Any]:
    t = _laden(state, slug)
    with platform_transaction(state.engines.platform) as s:
        aus = set(s.execute(text("SELECT module FROM tenant_feature_flags WHERE tenant_id = :t AND NOT enabled"),
                            {"t": t.id}).scalars())
        verlauf = s.execute(text("""SELECT action, actor, occurred_at, data->>'reason' AS reason
                                    FROM platform_audit_events WHERE tenant_id = :t
                                    ORDER BY occurred_at DESC, id DESC LIMIT 30"""), {"t": t.id}).mappings().all()
    return {**_out(t), **_team(state, t),
            "modules": [{"module": m, "enabled": m not in aus} for m in sorted(FLAGGABLE_MODULES)],
            "history": [dict(v) for v in verlauf]}


@router.patch("/platform/companies/{slug}")
def update_company(slug: str, body: CompanyFields, info: SessionInfo = Depends(operator()),
                   state: AppState = Depends(get_state)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    t = _laden(state, slug)
    actor = _actor(state, info)
    with platform_transaction(state.engines.platform) as s:
        return _out(tenancy.update_by_platform(s, t.id, changes, actor=actor))


@router.post("/platform/companies/{slug}/status")
def set_company_status(slug: str, body: StatusIn, info: SessionInfo = Depends(operator()),
                       state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Aktivieren, pausieren (nur lesen), sperren oder endgültig deaktivieren — immer mit Begründung."""
    t = _laden(state, slug)
    actor = _actor(state, info)
    with platform_transaction(state.engines.platform) as s:
        neu = tenancy.set_status(s, t.id, body.status, actor=actor, reason=body.reason)
    if neu.status == "active":
        with tenant_transaction(state.engines.app, neu.id) as s:
            install(s)
    return _out(neu)


@router.put("/platform/companies/{slug}/modules/{module}")
def set_company_module(slug: str, module: str, body: ModuleIn, info: SessionInfo = Depends(operator()),
                       state: AppState = Depends(get_state)) -> dict[str, Any]:
    t = _laden(state, slug)
    actor = _actor(state, info)
    with platform_transaction(state.engines.platform) as s:
        set_flag(s, t.id, module, body.enabled, actor=actor, reason=body.reason)
    return {"module": module, "enabled": body.enabled}


@router.post("/platform/companies/{slug}/admins", status_code=201)
def add_company_admin(slug: str, body: EmailIn, info: SessionInfo = Depends(operator()),
                      state: AppState = Depends(get_state)) -> dict[str, Any]:
    """Bestehendes, aktives Konto zum Company Admin dieser Firma machen (z. B. wenn der einzige Admin ausfällt)."""
    t = _laden(state, slug)
    if t.status not in ("active", "paused"):
        raise Conflict("Administratoren lassen sich nur einer aktiven Firma zuweisen")
    actor = _actor(state, info)
    with platform_transaction(state.engines.platform) as s:
        u = control.user_by_email(s, body.email)
        if u is None or u.status != "active":
            raise NotFound("Für diese E-Mail gibt es kein aktives Konto")
        record_platform(s, "tenant.admin_assigned", actor=actor, tenant_id=t.id, data={"email": u.email})
    neu = onboarding.assign_admin(state.engines, t.id, u.id)
    return {"email": u.email, "assigned": neu, **_team(state, t)}


# ---- Betreiber ----------------------------------------------------------------------------------------------------
@router.get("/platform/operators")
def list_operators(info: SessionInfo = Depends(operator()), state: AppState = Depends(get_state)) -> dict[str, Any]:
    with platform_transaction(state.engines.platform) as s:
        alle = control.operators(s)
    return {"items": [{"email": o["email"], "display_name": o["display_name"], "status": o["status"],
                       "since": o["created_at"], "me": o["id"] == info.user_id} for o in alle]}


@router.post("/platform/operators", status_code=201)
def add_operator(body: EmailIn, info: SessionInfo = Depends(operator()),
                 state: AppState = Depends(get_state)) -> dict[str, Any]:
    actor = _actor(state, info)
    with platform_transaction(state.engines.platform) as s:
        u = control.user_by_email(s, body.email)
        if u is None or u.status != "active":
            raise NotFound("Für diese E-Mail gibt es kein aktives Konto")
        return {"email": u.email, "added": control.add_operator(s, u.id, actor=actor)}


@router.post("/platform/operators/remove")
def remove_operator(body: EmailIn, info: SessionInfo = Depends(operator()),
                    state: AppState = Depends(get_state)) -> dict[str, Any]:
    actor = _actor(state, info)
    with platform_transaction(state.engines.platform) as s:
        u = control.user_by_email(s, body.email)
        if u is None:
            raise NotFound("Betreiber nicht gefunden")
        control.remove_operator(s, u.id, actor=actor)
    return {"email": u.email, "removed": True}
