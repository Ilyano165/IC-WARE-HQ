"""Rollenvorlagen je Firma (M4, ADR-011) — beim Aktivieren angelegt, idempotent.

„Company Admin" ist gesperrt und hält berechnet ALLE Rechte (``grants_all``). Die übrigen Vorlagen sind
Startpunkte nach der Produktvision (Abschnitt 1.4, Rechte-Zuschnitt **[ANNAHME]**) und frei änderbar; eine
schon vorhandene Rolle gleichen Namens wird nie überschrieben.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import insert, select, text
from sqlalchemy.orm import Session

from ichq.audit.service import record as audit
from ichq.authz.models import MembershipRole, Role, RolePermission
from ichq.authz.registry import PERMISSIONS
from ichq.core.errors import Conflict
from ichq.core.ids import uuid7
from ichq.db.session import current_tenant_id

COMPANY_ADMIN = "Company Admin"

_VERWALTUNG = frozenset({"roles.create", "roles.update", "roles.delete", "roles.assign", "users.override",
                         "users.update", "users.deactivate"})
_LESEN_BASIS = frozenset({"dashboard.read", "company.read", "comments.read", "comments.create"})


@dataclass(frozen=True)
class Template:
    name: str
    rank: int
    description: str
    permissions: frozenset[str] = frozenset()
    grants_all: bool = False


TEMPLATES: tuple[Template, ...] = (
    Template(COMPANY_ADMIN, 100, "Gesperrt: hält immer alle Rechte der Registry", grants_all=True),
    Template("Geschäftsführung", 90, "Sieht und entscheidet alles Geschäftliche, verwaltet keine Rechte",
             PERMISSIONS - _VERWALTUNG),
    Template("Mitarbeiter", 40, "Eigene Aufgaben, Fahrten, Reisen, Termine; sieht nur Eigenes und Freigegebenes",
             _LESEN_BASIS | {
                 "tasks.read", "tasks.create", "tasks.update", "projects.read", "files.read", "files.upload",
                 "chat.read", "chat.create", "calendar.read", "calendar.create", "calendar.update",
                 "vehicles.read", "vehicles.update", "travel.read", "travel.update",
                 "hospitality.read", "hospitality.update", "activity.read"}),
    Template("Steuerberater", 30, "Extern: Rückfragen, Belege, Export — nur Freigegebenes (ohne objects.read_all)",
             _LESEN_BASIS | {
                 "finance.read", "finance.export", "invoices.read", "invoices.export", "files.read",
                 "tasks.read", "tasks.create", "vehicles.read", "travel.read", "hospitality.read",
                 "suppliers.read", "contracts.read"}),
)
assert all(t.permissions <= PERMISSIONS for t in TEMPLATES)
assert not any("objects.read_all" in t.permissions for t in TEMPLATES if t.name in ("Mitarbeiter", "Steuerberater"))


def company_admin_role(session: Session) -> uuid.UUID | None:
    return session.scalar(select(Role.id).where(Role.grants_all))


def install(session: Session) -> list[str]:
    """Fehlende Vorlagen anlegen. Gibt die Namen der neu angelegten Rollen zurück. Mandanten-Transaktion."""
    tid = current_tenant_id(session)
    vorhanden = set(session.scalars(select(Role.name)))
    neu = []
    for t in TEMPLATES:
        if t.grants_all and company_admin_role(session) is not None:
            continue
        if t.name in vorhanden:
            if t.grants_all:
                raise Conflict(f"Rolle „{t.name}“ existiert, ist aber nicht gesperrt — bitte umbenennen")
            continue
        rid = uuid7()
        session.execute(insert(Role).values(id=rid, tenant_id=tid, name=t.name, description=t.description,
                                            priority=t.rank, is_system=t.grants_all, grants_all=t.grants_all))
        if t.permissions:
            session.execute(insert(RolePermission), [{"tenant_id": tid, "role_id": rid, "permission": p}
                                                     for p in sorted(t.permissions)])
        neu.append(t.name)
    if neu:
        audit(session, "role.templates_installed", data={"roles": neu})
    return neu


def make_company_admin(session: Session, membership_id: uuid.UUID) -> bool:
    """Control Plane (CLI, Onboarding): gesperrte Rolle zuweisen. KEINE Delegationsprüfung — wer die Datenbank-
    Zugangsdaten der Control Plane hat, hat ohnehin diese Macht. Es gibt keine Route dafür."""
    install(session)
    rid = company_admin_role(session)
    if session.get(MembershipRole, (membership_id, rid)) is not None:
        return False
    session.execute(insert(MembershipRole).values(tenant_id=current_tenant_id(session), membership_id=membership_id,
                                                  role_id=rid))
    pid = session.scalar(text("SELECT public_id FROM memberships WHERE id = :m"), {"m": membership_id})
    audit(session, "role.assigned", target_type="membership", target_id=pid,
          data={"role_name": COMPANY_ADMIN, "by": "control_plane"})
    return True
