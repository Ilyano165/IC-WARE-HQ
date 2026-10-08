"""Version 1 der API. Alles unter /api/v1."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ichq.api.security import TenantDB, authenticated, require, tenant_db, usable_tenant
from ichq.authz.service import Principal

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


@router.get("/company", response_model=CompanyOut)
def company(_: Principal = Depends(require("company.read")), db: TenantDB = Depends(tenant_db)) -> CompanyOut:
    with db() as s:
        t = usable_tenant(s)
    return CompanyOut(id=t.id, slug=t.slug, name=t.name, legal_name=t.legal_name, status=t.status,
                      timezone=t.timezone, language=t.language, currency=t.currency)
