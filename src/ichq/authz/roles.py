"""Rollenverwaltung (M4) mit den Delegationsregeln aus ADR-011. Alles im Mandantenkontext (RLS).

* **Obergrenze:** In eine Rolle schreiben, duplizieren oder wiederherstellen kann man nur Rechte, die man
  selbst effektiv hat.
* **Keine Lücken-Löschung:** Beim Bearbeiten bleiben Rechte, die man selbst nicht hat, unverändert.
* **Rang:** Rollen bearbeiten, archivieren, löschen nur mit kleinerem Rang als dem eigenen; neue Ränge
  ebenfalls nur darunter.
* **Gesperrt:** „Company Admin" (``grants_all``) ist unveränderlich — zusätzlich per DB-Trigger.
* **Last-Admin-Schutz** für alles, was Rechte entziehen kann (``ichq.authz.guard``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ichq.audit.service import record as audit
from ichq.authz.effective import Effective, effective
from ichq.authz.guard import admin_remains
from ichq.authz.models import MembershipRole, Role, RolePermission
from ichq.authz.registry import PERMISSIONS
from ichq.authz.service import Principal
from ichq.core.errors import AppError, Conflict, NotFound, PermissionDenied, ValidationFailed
from ichq.core.ids import uuid7
from ichq.db.session import current_tenant_id

_PUBLIC = re.compile(r"^[0-9a-f]{32}$")


class RoleLocked(AppError):
    status, code, title = 409, "role_locked", "Gesperrte Rolle"


@dataclass(frozen=True)
class RoleView:
    public_id: str
    name: str
    description: str
    rank: int
    locked: bool
    archived_at: datetime | None
    permissions: tuple[str, ...]
    members: int


def role_permissions(session: Session, role: Role) -> frozenset[str]:
    if role.grants_all:
        return PERMISSIONS
    return frozenset(session.scalars(select(RolePermission.permission).where(RolePermission.role_id == role.id)))


def _view(session: Session, r: Role) -> RoleView:
    n = session.scalar(select(func.count()).select_from(MembershipRole).where(MembershipRole.role_id == r.id)) or 0
    return RoleView(r.public_id, r.name, r.description, r.priority, r.grants_all, r.archived_at,
                    tuple(sorted(role_permissions(session, r))), int(n))


def get(session: Session, ref: str, *, lock: bool = False) -> Role:
    if not _PUBLIC.match(ref or ""):
        raise NotFound("Rolle nicht gefunden")
    stmt = select(Role).where(Role.public_id == ref)
    r = session.scalar(stmt.with_for_update() if lock else stmt)
    if r is None:
        raise NotFound("Rolle nicht gefunden")
    return r


def list_roles(session: Session, *, archived: bool) -> list[RoleView]:
    stmt = select(Role).order_by(Role.priority.desc(), Role.name)
    if not archived:
        stmt = stmt.where(Role.archived_at.is_(None))
    return [_view(session, r) for r in session.scalars(stmt).all()]


def view(session: Session, ref: str) -> RoleView:
    return _view(session, get(session, ref))


# ---------- Prüfungen ----------
def _bekannt(perms: list[str]) -> frozenset[str]:
    unbekannt = sorted(set(perms) - PERMISSIONS)
    if unbekannt:
        raise ValidationFailed(f"Unbekannte Rechte: {', '.join(unbekannt)}")
    return frozenset(perms)


def _obergrenze(a: Effective, perms: frozenset[str]) -> None:
    fehlend = sorted(perms - a.permissions)
    if fehlend:
        raise PermissionDenied(f"Nur eigene Rechte sind vergebbar — fehlt selbst: {', '.join(fehlend)}")


def _neuer_rang(a: Effective, rank: int) -> None:
    if not 1 <= rank < a.rank:
        raise PermissionDenied(f"Rang muss zwischen 1 und {a.rank - 1} liegen (unter dem eigenen Rang)")


def _verwaltbar(a: Effective, r: Role) -> None:
    if r.grants_all:
        raise RoleLocked("„Company Admin“ ist gesperrt und hält immer alle Rechte")
    if r.priority >= a.rank:
        raise PermissionDenied("Nur Rollen mit kleinerem Rang als dem eigenen sind verwaltbar")


def _name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 60:
        raise ValidationFailed("name muss 1–60 Zeichen lang sein")
    return name


def _speichern(session: Session, r: Role, perms: frozenset[str], alt: frozenset[str]) -> None:
    tid = current_tenant_id(session)
    if alt - perms:
        session.execute(delete(RolePermission).where(RolePermission.role_id == r.id,
                                                     RolePermission.permission.in_(sorted(alt - perms))))
    if perms - alt:
        session.execute(insert(RolePermission), [{"tenant_id": tid, "role_id": r.id, "permission": p}
                                                 for p in sorted(perms - alt)])


def _anlegen(session: Session, name: str, description: str, rank: int) -> Role:
    r = Role(id=uuid7(), tenant_id=current_tenant_id(session), name=_name(name), description=description,
             priority=rank)
    session.add(r)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError:
        raise Conflict("Eine Rolle mit diesem Namen gibt es schon") from None
    return r


def _audit(session: Session, p: Principal, action: str, r: Role, **data: Any) -> None:
    audit(session, action, actor_membership_id=p.membership_id, target_type="role", target_id=r.public_id,
          data={"name": r.name, **data})


# ---------- Ändern ----------
def create(session: Session, p: Principal, *, name: str, description: str, rank: int,
           permissions: list[str]) -> RoleView:
    a = effective(session, p.membership_id)
    perms = _bekannt(permissions)
    _neuer_rang(a, rank)
    _obergrenze(a, perms)
    r = _anlegen(session, name, description, rank)
    _speichern(session, r, perms, frozenset())
    _audit(session, p, "role.created", r, rank=rank, permissions=sorted(perms))
    return _view(session, r)


def edit(session: Session, p: Principal, ref: str, *, name: str | None = None, description: str | None = None,
         rank: int | None = None, permissions: list[str] | None = None) -> RoleView:
    a = effective(session, p.membership_id)
    r = get(session, ref, lock=True)
    _verwaltbar(a, r)
    if r.archived_at is not None:
        raise Conflict("Archivierte Rollen erst wiederherstellen")
    aenderung: dict[str, Any] = {}
    if rank is not None and rank != r.priority:
        _neuer_rang(a, rank)
        aenderung["rank"] = rank
    if name is not None and _name(name) != r.name:
        aenderung["new_name"] = _name(name)
    if description is not None:
        aenderung["description_changed"] = description != r.description
    with admin_remains(session):
        if permissions is not None:
            alt, gewuenscht = role_permissions(session, r), _bekannt(permissions)
            _obergrenze(a, gewuenscht - alt)                           # Hinzufügen nur eigener Rechte
            neu = (gewuenscht & a.permissions) | (alt - a.permissions)   # keine Lücken-Löschung
            _speichern(session, r, neu, alt)
            aenderung |= {"added": sorted(neu - alt), "removed": sorted(alt - neu)}
        werte = {k: v for k, v in (("priority", rank), ("description", description)) if v is not None}
        if "new_name" in aenderung:
            werte["name"] = aenderung["new_name"]
        if werte:
            try:
                with session.begin_nested():
                    session.execute(update(Role).where(Role.id == r.id).values(**werte))
            except IntegrityError:
                raise Conflict("Eine Rolle mit diesem Namen gibt es schon") from None
            session.refresh(r)
    _audit(session, p, "role.updated", r, **aenderung)
    return _view(session, r)


def duplicate(session: Session, p: Principal, ref: str, *, name: str, rank: int | None = None) -> RoleView:
    """Kopiert nur die Rechte, die man selbst hat. Rang: angegeben oder der der Vorlage (beides unter dem eigenen)."""
    a = effective(session, p.membership_id)
    quelle = get(session, ref)
    rang = rank if rank is not None else min(quelle.priority, a.rank - 1)
    _neuer_rang(a, rang)
    perms = role_permissions(session, quelle) & a.permissions
    r = _anlegen(session, name, quelle.description, rang)
    _speichern(session, r, perms, frozenset())
    _audit(session, p, "role.duplicated", r, source=quelle.public_id, rank=rang, permissions=sorted(perms),
           not_copied=sorted(role_permissions(session, quelle) - perms))
    return _view(session, r)


def archive(session: Session, p: Principal, ref: str) -> RoleView:
    """Entzieht allen Trägern die Rechte der Rolle sofort; die Zuweisungen bleiben für Audit und Wiederherstellen."""
    a = effective(session, p.membership_id)
    r = get(session, ref, lock=True)
    _verwaltbar(a, r)
    if r.archived_at is None:
        with admin_remains(session):
            session.execute(update(Role).where(Role.id == r.id).values(archived_at=func.now()))
        session.refresh(r)
        _audit(session, p, "role.archived", r)
    return _view(session, r)


def restore(session: Session, p: Principal, ref: str) -> RoleView:
    a = effective(session, p.membership_id)
    r = get(session, ref, lock=True)
    _verwaltbar(a, r)
    _obergrenze(a, role_permissions(session, r))      # wie Vergeben: wirkt wieder für alle Träger
    if r.archived_at is not None:
        session.execute(update(Role).where(Role.id == r.id).values(archived_at=None))
        session.refresh(r)
        _audit(session, p, "role.restored", r)
    return _view(session, r)


def remove(session: Session, p: Principal, ref: str) -> None:
    """Endgültig löschen: nur archiviert UND von niemandem mehr gehalten."""
    a = effective(session, p.membership_id)
    r = get(session, ref, lock=True)
    _verwaltbar(a, r)
    if r.archived_at is None:
        raise Conflict("Nur archivierte Rollen können gelöscht werden")
    if session.scalar(select(func.count()).select_from(MembershipRole).where(MembershipRole.role_id == r.id)):
        raise Conflict("Die Rolle ist noch zugewiesen — erst allen entziehen")
    _audit(session, p, "role.deleted", r)
    session.execute(delete(Role).where(Role.id == r.id))
