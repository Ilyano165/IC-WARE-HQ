"""Version 1 der API. Alles unter /api/v1."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ichq.api.security import TenantDB, authenticated, require, tenant_db, usable_tenant
from ichq.api.v1.common import writing
from ichq.authz.service import Principal
from ichq.core.errors import ValidationFailed
from ichq.tenancy.service import TenantInfo, update_profile

router = APIRouter(prefix="/api/v1")


class MeOut(BaseModel):
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    permissions: list[str]


class CompanyOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    legal_name: str | None
    status: str
    timezone: str
    language: str
    currency: str


@router.get("/me", response_model=MeOut)
def me(principal: Principal = Depends(authenticated())) -> MeOut:
    return MeOut(user_id=principal.user_id, tenant_id=principal.tenant_id,
                 membership_id=principal.membership_id, permissions=sorted(principal.permissions))


class CompanyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    legal_name: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    language: str | None = Field(default=None, min_length=2, max_length=8)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


def _out(t: TenantInfo) -> CompanyOut:
    return CompanyOut(id=t.id, slug=t.slug, name=t.name, legal_name=t.legal_name, status=t.status,
                      timezone=t.timezone, language=t.language, currency=t.currency)


@router.get("/company", response_model=CompanyOut)
def company(_: Principal = Depends(require("company.read")), db: TenantDB = Depends(tenant_db)) -> CompanyOut:
    with db() as s:
        return _out(usable_tenant(s))


@router.patch("/company", response_model=CompanyOut)
def update_company(body: CompanyPatch, p: Principal = Depends(require("company.update")),
                   db: TenantDB = Depends(tenant_db)) -> CompanyOut:
    """Profil der eigenen Firma (M3). Slug, Status, Plan nur über die Control Plane."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    if any(changes.get(f) is None for f in ("name", "timezone", "language", "currency") if f in changes):
        raise ValidationFailed("name, timezone, language, currency dürfen nicht leer sein")
    with writing(db) as s:
        return _out(update_profile(s, changes, actor_membership_id=p.membership_id))
