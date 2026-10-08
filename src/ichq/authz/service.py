"""Die eine Entscheidungsfunktion — in M1 der Kern ohne Overrides/Ressourcen (die kommen in M4)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ichq.authz.models import MembershipRole, Role, RolePermission
from ichq.authz.registry import PERMISSIONS, is_known
from ichq.core.ids import uuid7
from ichq.db.session import current_tenant_id


@dataclass(frozen=True)
class Principal:
    """Wer handelt — immer im Kontext genau einer Firma."""

    user_id: uuid.UUID
    tenant_id: uuid.UUID
    membership_id: uuid.UUID
    permissions: frozenset[str] = field(default_factory=frozenset)
    tenant_status: str = "active"     # 'paused' → nur lesende Anfragen (zentral in ichq.api.security)


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


COMPANY_ADMIN = "Company Admin"


def ensure_company_admin(session: Session, membership_id: uuid.UUID) -> uuid.UUID:
    """ÜBERGANG bis M4 (Rollenverwaltung): Systemrolle „Company Admin" mit ALLEN Rechten der Registry anlegen
    bzw. auf den aktuellen Registry-Stand bringen und der Mitgliedschaft zuweisen. Mandanten-Transaktion.
    Wird mit M4 durch Rollenvorlagen ersetzt — dann diese Funktion und den CLI-Befehl entfernen."""
    tid = current_tenant_id(session)
    rid = session.execute(text("SELECT id FROM roles WHERE name = :n"), {"n": COMPANY_ADMIN}).scalar()
    if rid is None:
        rid = uuid7()
        session.execute(text("""INSERT INTO roles(id, tenant_id, name, description, priority, is_system)
                                VALUES (:id, :t, :n, 'Übergang bis M4: alle Rechte', 1, true)"""),
                        {"id": rid, "t": tid, "n": COMPANY_ADMIN})
    vorhanden = set(session.scalars(text("SELECT permission FROM role_permissions WHERE role_id = :r"),
                                    {"r": rid}).all())
    for perm in sorted(PERMISSIONS - vorhanden):
        session.execute(text("INSERT INTO role_permissions(tenant_id, role_id, permission) VALUES (:t, :r, :p)"),
                        {"t": tid, "r": rid, "p": perm})
    session.execute(text("""INSERT INTO membership_roles(tenant_id, membership_id, role_id) VALUES (:t, :m, :r)
                            ON CONFLICT DO NOTHING"""), {"t": tid, "m": membership_id, "r": rid})
    return rid
