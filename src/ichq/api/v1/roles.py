"""M4: Rechte-Registry, Rollen, Zuweisungen, Einzelrechte, Vorschau „was darf diese Person" (ADR-011).

Jede Änderung landet im Mandanten-Audit (in den Services). Die Regeln stehen in ``ichq.authz.roles`` und
``ichq.authz.delegation`` — die Routen prüfen nur das Modulrecht.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Response
from pydantic import Field

from ichq.api.security import TenantDB, authenticated, require, tenant_db
from ichq.api.v1.common import Strict, writing
from ichq.authz import delegation
from ichq.authz import roles as rollen
from ichq.authz.effective import disabled_modules, effective
from ichq.authz.registry import CORE_MODULES, CRITICAL, PERMISSIONS, module_of
from ichq.authz.service import Principal

router = APIRouter(prefix="/api/v1", tags=["roles"])

Permission = Annotated[str, Path(pattern=r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$", max_length=64)]


class RoleIn(Strict):
    name: str = Field(min_length=1, max_length=60)
    description: str = Field(default="", max_length=200)
    rank: int = Field(ge=1, le=999)
    permissions: list[str] = Field(default_factory=list, max_length=200)


class RolePatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    rank: int | None = Field(default=None, ge=1, le=999)
    permissions: list[str] | None = Field(default=None, max_length=200)


class DuplicateIn(Strict):
    name: str = Field(min_length=1, max_length=60)
    rank: int | None = Field(default=None, ge=1, le=999)


class OverrideIn(Strict):
    effect: str = Field(pattern="^(allow|deny)$")


def _role(v: rollen.RoleView) -> dict[str, Any]:
    return {"id": v.public_id, "name": v.name, "description": v.description, "rank": v.rank, "locked": v.locked,
            "archived": v.archived_at is not None, "permissions": list(v.permissions), "members": v.members}


@router.get("/permissions")
def registry(_: Principal = Depends(require("roles.read")), db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Alle Rechte der Registry. ``disabled``: Modul für diese Firma per Feature-Flag abgeschaltet."""
    with db() as s:
        aus = disabled_modules(s)
    return {"items": [{"permission": p, "module": module_of(p), "critical": p in CRITICAL,
                       "core_module": module_of(p) in CORE_MODULES, "disabled": module_of(p) in aus}
                      for p in sorted(PERMISSIONS)]}


@router.get("/roles")
def list_roles(_: Principal = Depends(require("roles.read")), db: TenantDB = Depends(tenant_db),
               archived: bool = False) -> dict[str, Any]:
    with db() as s:
        return {"items": [_role(v) for v in rollen.list_roles(s, archived=archived)]}


@router.post("/roles", status_code=201)
def create_role(body: RoleIn, p: Principal = Depends(require("roles.create")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return _role(rollen.create(s, p, name=body.name, description=body.description, rank=body.rank,
                                   permissions=body.permissions))


@router.get("/roles/{role}")
def get_role(role: str, _: Principal = Depends(require("roles.read")),
             db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        return _role(rollen.view(s, role))


@router.patch("/roles/{role}")
def edit_role(role: str, body: RolePatch, p: Principal = Depends(require("roles.update")),
              db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return _role(rollen.edit(s, p, role, name=body.name, description=body.description, rank=body.rank,
                                 permissions=body.permissions))


@router.post("/roles/{role}/duplicate", status_code=201)
def duplicate_role(role: str, body: DuplicateIn, p: Principal = Depends(require("roles.create")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return _role(rollen.duplicate(s, p, role, name=body.name, rank=body.rank))


@router.post("/roles/{role}/archive")
def archive_role(role: str, p: Principal = Depends(require("roles.delete")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return _role(rollen.archive(s, p, role))


@router.post("/roles/{role}/restore")
def restore_role(role: str, p: Principal = Depends(require("roles.delete")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return _role(rollen.restore(s, p, role))


@router.delete("/roles/{role}", status_code=204)
def delete_role(role: str, p: Principal = Depends(require("roles.delete")),
                db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        rollen.remove(s, p, role)
    return Response(status_code=204)


# ---------- Personen ----------
def _vorschau(s: Any, membership_id: Any) -> dict[str, Any]:
    e = effective(s, membership_id)
    gehalten = delegation.roles_of(s, membership_id)
    namen = {r.public_id: r.name for r in gehalten}
    return {"rank": e.rank,
            "roles": [{"id": r.public_id, "name": r.name, "rank": r.priority, "archived": r.archived_at is not None}
                      for r in gehalten],
            "overrides": delegation.overrides_of(s, membership_id),
            "permissions": [{"permission": d.permission, "granted": d.granted, "decided_by": d.decided_by,
                             "roles": [{"id": r, "name": namen.get(r, "")} for r in d.roles]}
                            for d in e.decisions.values()]}


@router.get("/me/permissions")
def my_permissions(p: Principal = Depends(authenticated()), db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Eigene Rechte mit Quelle je Recht (keine Zusatzrechte nötig)."""
    with db() as s:
        return _vorschau(s, p.membership_id)


@router.get("/members/{member}/permissions")
def member_permissions(member: str, _: Principal = Depends(require("users.read", "roles.read")),
                       db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Vorschau „was darf diese Person" — jedes Recht mit Entscheidung und Quelle."""
    with db() as s:
        return _vorschau(s, delegation.target(s, member).id)


@router.put("/members/{member}/roles/{role}")
def assign_role(member: str, role: str, p: Principal = Depends(require("roles.assign")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return {"member": member, "role": role, "created": delegation.assign(s, p, member, role)}


@router.delete("/members/{member}/roles/{role}", status_code=204)
def unassign_role(member: str, role: str, p: Principal = Depends(require("roles.assign")),
                  db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        delegation.unassign(s, p, member, role)
    return Response(status_code=204)


@router.put("/members/{member}/overrides/{permission}")
def set_override(member: str, permission: Permission, body: OverrideIn,
                 p: Principal = Depends(require("users.override")), db: TenantDB = Depends(tenant_db),
                 ) -> dict[str, str]:
    with writing(db) as s:
        delegation.set_override(s, p, member, permission, body.effect)
    return {"member": member, "permission": permission, "effect": body.effect}


@router.delete("/members/{member}/overrides/{permission}", status_code=204)
def clear_override(member: str, permission: Permission, p: Principal = Depends(require("users.override")),
                   db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        delegation.clear_override(s, p, member, permission)
    return Response(status_code=204)
