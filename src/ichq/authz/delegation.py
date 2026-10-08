"""Rechte an Personen geben (M4, ADR-011): Rollen zuweisen/entziehen, Einzelrechte ALLOW/DENY, Vorschau.

* **Kein Selbstbedienen:** eigene Rollen und eigene Einzelrechte ändert niemand selbst.
* **Rang:** Personen nur verwalten, deren Rang höchstens dem eigenen entspricht; Rollen vergeben/entziehen bis
  zum eigenen Rang (archivierte Rollen dürfen immer entzogen werden — sie wirken nicht).
* **Obergrenze:** Vergeben nur, wenn man jedes Recht der Rolle selbst effektiv hat; Einzelrechte (ALLOW wie DENY,
  auch Zurücksetzen) nur für Rechte, die man selbst hat.
* **Last-Admin-Schutz** bei allem, was Rechte entziehen kann.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ichq.audit.service import record as audit
from ichq.authz.effective import Effective, effective
from ichq.authz.guard import admin_remains
from ichq.authz.models import MembershipRole, PermissionOverride, Role
from ichq.authz.registry import PERMISSIONS
from ichq.authz.roles import get as get_role
from ichq.authz.roles import role_permissions
from ichq.authz.service import Principal
from ichq.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from ichq.db.session import current_tenant_id

_PUBLIC = re.compile(r"^[0-9a-f]{32}$")
EFFECTS = ("allow", "deny")


@dataclass(frozen=True)
class Target:
    id: uuid.UUID
    public_id: str
    status: str


def _anzahl(res: object) -> int:
    return int(getattr(res, "rowcount", 0) or 0)


def target(session: Session, ref: str) -> Target:
    if not _PUBLIC.match(ref or ""):
        raise NotFound("Mitglied nicht gefunden")
    r = session.execute(text("SELECT id, public_id, status FROM memberships WHERE public_id = :p"),
                        {"p": ref}).one_or_none()
    if r is None:
        raise NotFound("Mitglied nicht gefunden")
    return Target(r.id, r.public_id, r.status)


def manageable(session: Session, p: Principal, ref: str) -> tuple[Effective, Target]:
    a = effective(session, p.membership_id)
    t = target(session, ref)
    if t.id == p.membership_id:
        raise PermissionDenied("Eigene Rollen und Einzelrechte kann niemand selbst ändern")
    if effective(session, t.id).rank > a.rank:
        raise PermissionDenied("Personen mit höherem Rang als dem eigenen sind nicht verwaltbar")
    return a, t


def _audit(session: Session, p: Principal, action: str, t: Target, **data: str) -> None:
    audit(session, action, actor_membership_id=p.membership_id, target_type="membership", target_id=t.public_id,
          data=data)


# ---------- Rollen ----------
def roles_of(session: Session, membership_id: uuid.UUID) -> list[Role]:
    return list(session.scalars(select(Role).join(MembershipRole, MembershipRole.role_id == Role.id)
                                .where(MembershipRole.membership_id == membership_id)
                                .order_by(Role.priority.desc(), Role.name)).all())


def assign(session: Session, p: Principal, member_ref: str, role_ref: str) -> bool:
    a, t = manageable(session, p, member_ref)
    if t.status not in ("active", "invited", "suspended"):
        raise Conflict(f"Mitgliedschaft ist beendet ({t.status})")
    r = get_role(session, role_ref)
    if r.archived_at is not None:
        raise Conflict("Archivierte Rollen können nicht vergeben werden")
    if r.priority > a.rank:
        raise PermissionDenied("Rollen über dem eigenen Rang können nicht vergeben werden")
    fehlend = sorted(role_permissions(session, r) - a.permissions)
    if fehlend:
        raise PermissionDenied(f"Rolle enthält Rechte, die man selbst nicht hat: {', '.join(fehlend)}")
    neu = _anzahl(session.execute(pg_insert(MembershipRole).values(
        tenant_id=current_tenant_id(session), membership_id=t.id, role_id=r.id).on_conflict_do_nothing()))
    if neu:
        _audit(session, p, "role.assigned", t, role=r.public_id, role_name=r.name)
    return bool(neu)


def unassign(session: Session, p: Principal, member_ref: str, role_ref: str) -> bool:
    a, t = manageable(session, p, member_ref)
    r = get_role(session, role_ref)
    if r.archived_at is None and r.priority > a.rank:
        raise PermissionDenied("Rollen über dem eigenen Rang können nicht entzogen werden")
    with admin_remains(session):
        weg = _anzahl(session.execute(delete(MembershipRole).where(MembershipRole.membership_id == t.id,
                                                                   MembershipRole.role_id == r.id)))
    if weg:
        _audit(session, p, "role.unassigned", t, role=r.public_id, role_name=r.name)
    return bool(weg)


# ---------- Einzelrechte ----------
def overrides_of(session: Session, membership_id: uuid.UUID) -> dict[str, str]:
    return {r.permission: r.effect for r in session.execute(
        select(PermissionOverride.permission, PermissionOverride.effect)
        .where(PermissionOverride.membership_id == membership_id))}


def _recht(a: Effective, permission: str) -> None:
    if permission not in PERMISSIONS:
        raise ValidationFailed("Unbekanntes Recht")
    if permission not in a.permissions:
        raise PermissionDenied("Einzelrechte nur für Rechte, die man selbst hat")


def set_override(session: Session, p: Principal, member_ref: str, permission: str, effect: str) -> None:
    if effect not in EFFECTS:
        raise ValidationFailed("effect muss allow oder deny sein")
    a, t = manageable(session, p, member_ref)
    _recht(a, permission)
    with admin_remains(session):
        stmt = pg_insert(PermissionOverride).values(
            tenant_id=current_tenant_id(session), membership_id=t.id, permission=permission, effect=effect)
        session.execute(stmt.on_conflict_do_update(index_elements=["membership_id", "permission"],
                                                   set_={"effect": effect, "created_at": text("now()")}))
    _audit(session, p, "permission.override_set", t, permission=permission, effect=effect)


def clear_override(session: Session, p: Principal, member_ref: str, permission: str) -> bool:
    a, t = manageable(session, p, member_ref)
    _recht(a, permission)
    with admin_remains(session):
        weg = _anzahl(session.execute(delete(PermissionOverride).where(
            PermissionOverride.membership_id == t.id, PermissionOverride.permission == permission)))
    if weg:
        _audit(session, p, "permission.override_cleared", t, permission=permission)
    return bool(weg)
