"""Projekte: anlegen, ändern, Status, Team (mit automatischer Freigabe), Projektzeiten.

* Ein Projekt ist ein Objekt vom Typ ``project`` plus Zeile in ``projects``.
* Teammitglieder ohne ``objects.read_all`` erhalten eine Freigabe mit Quelle ``project_team`` — nur für das Projekt.
  Wer das Team verlässt, verliert genau diese Freigabe (eine manuelle bleibt).
* Projektzeiten erfasst jedes Teammitglied für sich; für andere braucht es ``projects.assign``. Löschen darf, wer den
  Eintrag erfasst hat, oder wer ``projects.update`` hat.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Date, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal, decide
from ichq.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from ichq.db.paging import SortKey, keyset
from ichq.objects.models import ObjectDeny, ObjectRow
from ichq.objects.service import Member, clean_title, create_object, member, resolve
from ichq.objects.visibility import READ_ALL, principal_for_membership
from ichq.projects.models import MAX_TEXT, PRIORITY, PROJECT_STATUS, Project, ProjectMember, TimeEntry
from ichq.relations.service import TEAM, drop_assignment_grant, grant_for_assignment
from ichq.tasks.models import Task

_RANG = case({"urgent": 4, "high": 3, "normal": 2, "low": 1}, value=Project.priority, else_=0)
_FERN = cast(literal("9999-12-31"), Date)
SORTS: dict[str, SortKey] = {
    "name": SortKey("name", ObjectRow.title, "text"),
    "created_at": SortKey("created_at", ObjectRow.created_at, "ts"),
    "start_date": SortKey("start_date", func.coalesce(Project.start_date, _FERN), "date"),
    "end_date": SortKey("end_date", func.coalesce(Project.end_date, _FERN), "date"),
    "priority": SortKey("priority", _RANG, "int"),
}


def _pruefe(w: dict[str, Any]) -> None:
    if "status" in w and w["status"] not in PROJECT_STATUS:
        raise ValidationFailed("status ist ungültig")
    if "priority" in w and w["priority"] not in PRIORITY:
        raise ValidationFailed("priority ist ungültig")
    if len(w.get("description") or "") > MAX_TEXT:
        raise ValidationFailed(f"description: höchstens {MAX_TEXT} Zeichen")
    if (w.get("budget_minor") or 0) < 0:
        raise ValidationFailed("budget_minor darf nicht negativ sein")


def _zeitraum(start: date | None, ende: date | None) -> None:
    if start and ende and ende < start:
        raise ValidationFailed("end_date darf nicht vor start_date liegen")


def _kunde(session: Session, principal: Principal, ref: str | None) -> uuid.UUID | None:
    return resolve(session, principal, ref, type_="customer").id if ref else None


def _status_setzen(session: Session, p: Project, status: str) -> None:
    fertig = session.scalar(select(func.now())) if status == "completed" else None   # erst holen, dann setzen
    p.status, p.completed_at = status, fertig


def create(session: Session, principal: Principal, *, name: str, werte: dict[str, Any],
           currency: str) -> tuple[Project, ObjectRow]:
    _pruefe(werte)
    _zeitraum(werte.get("start_date"), werte.get("end_date"))
    o = create_object(session, type_="project", title=name, actor_membership_id=principal.membership_id,
                      search_text=(werte.get("description") or "")[:1000])
    p = Project(id=o.id, tenant_id=o.tenant_id, description=(werte.get("description") or "").strip(),
                priority=werte.get("priority") or "normal",
                customer_id=_kunde(session, principal, werte.get("customer")),
                owner_membership_id=member(session, werte["owner"]).id if werte.get("owner") else None,
                start_date=werte.get("start_date"), end_date=werte.get("end_date"),
                budget_minor=werte.get("budget_minor"), currency=werte.get("currency") or currency)
    _status_setzen(session, p, werte.get("status") or "planned")
    session.add(p)
    session.flush()
    activity(session, o.id, "project.created", actor_membership_id=principal.membership_id)
    audit(session, "project.created", actor_membership_id=principal.membership_id, target_type="project",
          target_id=o.public_id)
    if p.owner_membership_id is not None:
        _ins_team(session, principal, o, member(session, werte["owner"]), "Projektleitung")
    return p, o


def get(session: Session, principal: Principal, ref: str) -> tuple[Project, ObjectRow]:
    o = resolve(session, principal, ref, type_="project")
    p = session.get(Project, o.id)
    if p is None:
        raise NotFound()
    return p, o


def update(session: Session, principal: Principal, ref: str, changes: dict[str, Any]) -> tuple[Project, ObjectRow]:
    p, o = get(session, principal, ref)
    _pruefe(changes)
    _zeitraum(changes.get("start_date", p.start_date), changes.get("end_date", p.end_date))
    alt = p.status
    if "name" in changes:
        o.title = clean_title(changes["name"])
    if "description" in changes:
        p.description = (changes["description"] or "").strip()
        o.search_text = p.description[:1000] or None
    for f in ("priority", "start_date", "end_date", "budget_minor", "currency"):
        if f in changes:
            setattr(p, f, changes[f])
    if "customer" in changes:
        p.customer_id = _kunde(session, principal, changes["customer"])
    if "owner" in changes:
        neu = member(session, changes["owner"]) if changes["owner"] else None
        p.owner_membership_id = neu.id if neu else None
        if neu is not None:
            _ins_team(session, principal, o, neu, "Projektleitung")
    if changes.get("status") and changes["status"] != alt:
        _status_setzen(session, p, changes["status"])
    session.flush()
    if p.status != alt:
        activity(session, o.id, "project.status_changed", actor_membership_id=principal.membership_id,
                 data={"from": alt, "to": p.status})
    activity(session, o.id, "project.updated", actor_membership_id=principal.membership_id,
             data={"fields": sorted(changes)})
    audit(session, "project.updated", actor_membership_id=principal.membership_id, target_type="project",
          target_id=o.public_id, data={"fields": sorted(changes), "status_from": alt, "status_to": p.status})
    return p, o


@dataclass(frozen=True)
class ProjectFilter:
    q: str | None = None
    status: tuple[str, ...] = ()
    customer_id: uuid.UUID | None = None
    owner_membership_id: uuid.UUID | None = None
    team_membership_id: uuid.UUID | None = None
    archived: bool = False


def filter_clauses(f: ProjectFilter) -> list[Any]:
    teile: list[Any] = [ObjectRow.archived_at.is_not(None) if f.archived else ObjectRow.archived_at.is_(None)]
    if f.status:
        teile.append(Project.status.in_(f.status))
    if f.customer_id is not None:
        teile.append(Project.customer_id == f.customer_id)
    if f.owner_membership_id is not None:
        teile.append(Project.owner_membership_id == f.owner_membership_id)
    if f.team_membership_id is not None:
        teile.append(select(ProjectMember.project_id).where(
            ProjectMember.project_id == Project.id,
            ProjectMember.membership_id == f.team_membership_id).exists())
    if f.q:
        muster = f"%{f.q.lower()}%"
        teile.append(or_(func.lower(ObjectRow.title).like(muster), func.lower(Project.description).like(muster)))
    return teile


def list_projects(session: Session, visible: Any, f: ProjectFilter, *, sort: str, desc: bool, cursor: str | None,
                  limit: int | None) -> tuple[list[Any], str | None]:
    key = SORTS.get(sort)
    if key is None:
        raise ValidationFailed(f"sort muss eine von {sorted(SORTS)} sein")
    stmt = select(Project, ObjectRow).join(ObjectRow, ObjectRow.id == Project.id).where(visible, *filter_clauses(f))
    seite = keyset(session, stmt, key, ObjectRow.id, desc=desc, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor


# ---- Team -------------------------------------------------------------------------------------------------------
def team(session: Session, project_id: uuid.UUID) -> list[ProjectMember]:
    return list(session.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)
                                .order_by(ProjectMember.created_at)))


def _ins_team(session: Session, principal: Principal, o: ObjectRow, m: Member, rolle: str | None,
              kosten: int | None = None, kosten_setzen: bool = False) -> ProjectMember:
    ziel = principal_for_membership(session, m.id)
    if ziel is None or not decide(ziel, "projects.read"):
        raise ValidationFailed("Dieses Mitglied darf keine Projekte sehen (projects.read fehlt)")
    if session.get(ObjectDeny, (o.id, m.id)) is not None:
        raise ValidationFailed("Für dieses Mitglied ist das Projekt gesperrt (Ressourcen-DENY)")
    pm = session.get(ProjectMember, (o.id, m.id))
    if pm is None:
        pm = ProjectMember(tenant_id=o.tenant_id, project_id=o.id, membership_id=m.id, role=rolle,
                           hourly_cost_minor=kosten, added_by_membership_id=principal.membership_id)
        session.add(pm)
        session.flush()
        activity(session, o.id, "project.member_added", actor_membership_id=principal.membership_id,
                 data={"member": m.public_id})
        audit(session, "project.member_added", actor_membership_id=principal.membership_id, target_type="project",
              target_id=o.public_id, data={"member": m.public_id})
    else:
        if rolle is not None:
            pm.role = rolle
        if kosten_setzen:
            pm.hourly_cost_minor = kosten
    if not decide(ziel, READ_ALL):
        grant_for_assignment(session, principal, o, m, TEAM)
    return pm


def put_member(session: Session, principal: Principal, ref: str, member_ref: str, *, role: str | None,
               hourly_cost_minor: int | None, cost_given: bool) -> ProjectMember:
    _, o = get(session, principal, ref)
    if cost_given and not decide(principal, "finance.read"):
        raise PermissionDenied("Kostensätze brauchen finance.read")
    if cost_given and hourly_cost_minor is not None and hourly_cost_minor < 0:
        raise ValidationFailed("hourly_cost_minor darf nicht negativ sein")
    pm = _ins_team(session, principal, o, member(session, member_ref), role, hourly_cost_minor, cost_given)
    session.flush()
    return pm


def remove_member(session: Session, principal: Principal, ref: str, member_ref: str) -> None:
    p, o = get(session, principal, ref)
    m = member(session, member_ref, active_only=False)
    pm = session.get(ProjectMember, (o.id, m.id))
    if pm is None:
        raise NotFound("Nicht im Projektteam")
    if p.owner_membership_id == m.id:
        raise Conflict("Die Projektleitung kann nicht entfernt werden — zuerst eine andere Leitung wählen")
    session.delete(pm)
    session.flush()
    drop_assignment_grant(session, principal, o, m.id, TEAM)
    activity(session, o.id, "project.member_removed", actor_membership_id=principal.membership_id,
             data={"member": m.public_id})
    audit(session, "project.member_removed", actor_membership_id=principal.membership_id, target_type="project",
          target_id=o.public_id, data={"member": m.public_id})


# ---- Projektzeiten ---------------------------------------------------------------------------------------------
def time_entries(session: Session, project_id: uuid.UUID, limit: int = 200) -> list[TimeEntry]:
    return list(session.scalars(select(TimeEntry).where(TimeEntry.project_id == project_id)
                                .order_by(TimeEntry.work_date.desc(), TimeEntry.created_at.desc()).limit(limit)))


def add_time(session: Session, principal: Principal, ref: str, *, work_date: date, minutes: int, billable: bool,
             description: str, member_ref: str | None) -> TimeEntry:
    _, o = get(session, principal, ref)
    wer = member(session, member_ref) if member_ref else None
    mid = wer.id if wer else principal.membership_id
    if mid != principal.membership_id and not decide(principal, "projects.assign"):
        raise PermissionDenied("Fehlendes Recht: projects.assign (Zeit für andere erfassen)")
    if session.get(ProjectMember, (o.id, mid)) is None:
        raise ValidationFailed("Zeiten nur für Mitglieder des Projektteams")
    e = TimeEntry(id=uuid.uuid4(), tenant_id=o.tenant_id, public_id=secrets.token_hex(16), project_id=o.id,
                  membership_id=mid, work_date=work_date, minutes=minutes, billable=billable,
                  description=" ".join(description.split())[:500], created_by_membership_id=principal.membership_id)
    session.add(e)
    session.flush()
    activity(session, o.id, "project.time_logged", actor_membership_id=principal.membership_id)
    return e


def delete_time(session: Session, principal: Principal, ref: str, entry_ref: str) -> None:
    _, o = get(session, principal, ref)
    e = session.scalars(select(TimeEntry).where(TimeEntry.public_id == entry_ref,
                                                TimeEntry.project_id == o.id)).one_or_none()
    if e is None:
        raise NotFound()
    if e.created_by_membership_id != principal.membership_id and not decide(principal, "projects.update"):
        raise PermissionDenied("Fehlendes Recht: projects.update (fremde Zeiten löschen)")
    session.delete(e)
    session.flush()
    audit(session, "project.time_deleted", actor_membership_id=principal.membership_id, target_type="project",
          target_id=o.public_id, data={"entry": entry_ref, "minutes": e.minutes})


def summary(session: Session, project_id: uuid.UUID) -> dict[str, int]:
    """Kennzahlen aus echten Zeilen — ohne Kosten (die rechnet die Profitabilität mit Kennzeichnung)."""
    zeit = session.execute(select(func.coalesce(func.sum(TimeEntry.minutes), 0),
                                  func.coalesce(func.sum(case((TimeEntry.billable, TimeEntry.minutes), else_=0)), 0))
                           .where(TimeEntry.project_id == project_id)).one()
    offen = session.scalar(select(func.count()).select_from(Task).join(ObjectRow, ObjectRow.id == Task.id).where(
        Task.subject_object_id == project_id, Task.status.in_(("open", "in_progress", "blocked")),
        ObjectRow.archived_at.is_(None))) or 0
    return {"minutes_total": int(zeit[0]), "minutes_billable": int(zeit[1]), "open_tasks": int(offen)}
