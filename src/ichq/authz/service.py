"""Die eine Entscheidungsfunktion — in M1 der Kern ohne Overrides/Ressourcen (die kommen in M4)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ichq.authz.models import MembershipRole, Role, RolePermission
from ichq.authz.registry import is_known


@dataclass(frozen=True)
class Principal:
    """Wer handelt — immer im Kontext genau einer Firma."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    permissions: frozenset[str] = field(default_factory=frozenset)


def decide(principal: Principal | None, permission: str) -> bool:
    """Reihenfolge (M0, Abschnitt 19): unbekanntes Recht/kein Principal → nein; sonst Rollenrecht."""
    if principal is None or not is_known(permission):
        return False
    return permission in principal.permissions


def permissions_for_membership(session: Session, membership_id: uuid.UUID) -> frozenset[str]:
    """Rechte aus nicht archivierten Rollen. Läuft in einer Mandanten-Transaktion (RLS)."""
    rows = session.scalars(
        select(RolePermission.permission)
        .join(Role, (Role.id == RolePermission.role_id) & (Role.tenant_id == RolePermission.tenant_id))
        .join(MembershipRole, (MembershipRole.role_id == Role.id) & (MembershipRole.tenant_id == Role.tenant_id))
        .where(MembershipRole.membership_id == membership_id, Role.archived_at.is_(None))
    ).all()
    return frozenset(p for p in rows if is_known(p))
