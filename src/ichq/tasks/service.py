"""Zentrale Aufgaben.

* Eine Aufgabe ist ein Objekt vom Typ ``task`` (Titel/Ersteller in ``objects``) plus Zeile in ``tasks``.
* Bezug zu einem Fachobjekt (``subject``) und Herkunft aus einem Kommentar (``source_comment``) sind echte
  Fremdschlüssel. Wer eine Aufgabe zu einem Objekt anlegt, muss dieses Objekt sehen dürfen.
* Zuweisen an jemand anderen braucht ``tasks.assign``. Der Verantwortliche muss ``tasks.read`` haben;
  ohne ``objects.read_all`` erhält er automatisch eine Freigabe für die Aufgabe (nicht für das Bezugsobjekt).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Date, case, cast, func, literal, select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal, decide
from ichq.comments.models import Comment
from ichq.core.errors import NotFound, PermissionDenied, ValidationFailed
from ichq.db.paging import SortKey, keyset
from ichq.jobs.service import emit_event
from ichq.objects.models import ObjectDeny, ObjectRow
from ichq.objects.service import Member, clean_title, create_object, member, resolve
from ichq.objects.visibility import READ_ALL, principal_for_membership
from ichq.relations.service import drop_assignment_grant, grant_for_assignment
from ichq.tasks.models import MAX_DESCRIPTION, TASK_PRIORITY, TASK_STATUS, Task

_RANG = case({"urgent": 4, "high": 3, "normal": 2, "low": 1}, value=Task.priority, else_=0)
SORTS: dict[str, SortKey] = {
    "created_at": SortKey("created_at", ObjectRow.created_at, "ts"),
    "due_date": SortKey("due_date", func.coalesce(Task.due_date, cast(literal("9999-12-31"), Date)), "date"),
    "priority": SortKey("priority", _RANG, "int"),
    "title": SortKey("title", ObjectRow.title, "text"),
}


@dataclass(frozen=True)
class TaskFilter:
    status: tuple[str, ...] = ()
    priority: tuple[str, ...] = ()
    assignee_membership_id: uuid.UUID | None = None
    subject_object_id: uuid.UUID | None = None
    due_before: date | None = None
    unassigned: bool = False           # nur Aufgaben ohne Zuständige (Dashboard „ohne Zuständigkeit")


def _beschreibung(text: str | None) -> str:
    text = (text or "").strip()
    if len(text) > MAX_DESCRIPTION:
        raise ValidationFailed(f"description: höchstens {MAX_DESCRIPTION} Zeichen")
    return text


def _verantwortlich(session: Session, principal: Principal, ref: str, task_obj: ObjectRow | None) -> Member:
    m = member(session, ref)
    if m.id != principal.membership_id and not decide(principal, "tasks.assign"):
        raise PermissionDenied("Fehlendes Recht: tasks.assign")
    ziel = principal_for_membership(session, m.id)
    if ziel is None or not decide(ziel, "tasks.read"):
        raise ValidationFailed("Dieses Mitglied darf keine Aufgaben sehen (tasks.read fehlt)")
    if task_obj is not None and session.get(ObjectDeny, (task_obj.id, m.id)) is not None:
        raise ValidationFailed("Für dieses Mitglied ist die Aufgabe gesperrt (Ressourcen-DENY)")
    if task_obj is not None and not decide(ziel, READ_ALL):
        grant_for_assignment(session, principal, task_obj, m)
    return m


def create(session: Session, principal: Principal, *, title: str, description: str | None = None,
           assignee: str | None = None, due_date: date | None = None, priority: str = "normal",
           subject: ObjectRow | None = None, source_comment: Comment | None = None) -> tuple[Task, ObjectRow]:
    if priority not in TASK_PRIORITY:
        raise ValidationFailed("priority ist ungültig")
    obj = create_object(session, type_="task", title=title, actor_membership_id=principal.membership_id,
                        search_text=_beschreibung(description)[:1000])
    m = _verantwortlich(session, principal, assignee, obj) if assignee else None
    task = Task(id=obj.id, tenant_id=obj.tenant_id, description=_beschreibung(description), priority=priority,
                assignee_membership_id=m.id if m else None, due_date=due_date,
                subject_object_id=subject.id if subject else None,
                source_comment_id=source_comment.id if source_comment else None)
    session.add(task)
    session.flush()
    activity(session, obj.id, "task.created", actor_membership_id=principal.membership_id)
    if subject is not None:
        # ohne Task-Ref: Wer das Bezugsobjekt sieht, sieht nicht zwingend die Aufgabe
        activity(session, subject.id, "task.created", actor_membership_id=principal.membership_id)
    audit(session, "task.created", actor_membership_id=principal.membership_id, target_type="task",
          target_id=obj.public_id, data={"subject": subject.public_id if subject else None,
                                         "assignee": m.public_id if m else None,
                                         "from_comment": source_comment.public_id if source_comment else None})
    if m is not None and m.id != principal.membership_id:
        emit_event(session, "task.assigned", {"task_id": str(obj.id)})
    return task, obj


def get(session: Session, principal: Principal, ref: str) -> tuple[Task, ObjectRow]:
    obj = resolve(session, principal, ref, type_="task")
    task = session.get(Task, obj.id)
    if task is None:
        raise NotFound()
    return task, obj


def update(session: Session, principal: Principal, ref: str, changes: dict[str, Any]) -> tuple[Task, ObjectRow]:
    task, obj = get(session, principal, ref)
    alt = {"status": task.status, "assignee": task.assignee_membership_id}
    geaendert = sorted(changes)
    if "title" in changes:
        obj.title = clean_title(changes["title"])
    if "description" in changes:
        task.description = _beschreibung(changes["description"])
        obj.search_text = task.description[:1000] or None
    if "priority" in changes:
        if changes["priority"] not in TASK_PRIORITY:
            raise ValidationFailed("priority ist ungültig")
        task.priority = changes["priority"]
    if "due_date" in changes:
        task.due_date = changes["due_date"]
    if "status" in changes:
        if changes["status"] not in TASK_STATUS:
            raise ValidationFailed("status ist ungültig")
        fertig = session.scalar(select(func.now())) if changes["status"] == "done" else None
        task.status, task.completed_at = changes["status"], fertig
    m = None
    if "assignee" in changes:
        ref_m = changes["assignee"]
        m = _verantwortlich(session, principal, ref_m, obj) if ref_m else None
        if m is None and not decide(principal, "tasks.assign") and task.assignee_membership_id not in (
                None, principal.membership_id):
            raise PermissionDenied("Fehlendes Recht: tasks.assign")
        alt_assignee = task.assignee_membership_id
        task.assignee_membership_id = m.id if m else None
        if alt_assignee is not None and alt_assignee != task.assignee_membership_id:
            drop_assignment_grant(session, principal, obj, alt_assignee)   # nur die automatische Freigabe
    session.flush()
    if task.status != alt["status"]:
        activity(session, obj.id, "task.status_changed", actor_membership_id=principal.membership_id,
                 data={"from": alt["status"], "to": task.status})
    if task.assignee_membership_id != alt["assignee"]:
        activity(session, obj.id, "task.assigned", actor_membership_id=principal.membership_id,
                 data={"assignee": m.public_id if m else None})
        if m is not None and m.id != principal.membership_id:
            emit_event(session, "task.assigned", {"task_id": str(obj.id)})
    elif geaendert != ["status"]:
        activity(session, obj.id, "task.updated", actor_membership_id=principal.membership_id,
                 data={"fields": geaendert})
    audit(session, "task.updated", actor_membership_id=principal.membership_id, target_type="task",
          target_id=obj.public_id, data={"fields": geaendert, "status_from": alt["status"], "status_to": task.status})
    return task, obj


def filter_clauses(f: TaskFilter) -> list[Any]:
    """Die Filterbedingungen der Aufgabenliste — dieselben nutzt das Dashboard für seine Zahlen (D0: jede Zahl
    entspricht genau der verlinkten Liste)."""
    teile: list[Any] = [ObjectRow.archived_at.is_(None)]
    if f.status:
        teile.append(Task.status.in_(f.status))
    if f.priority:
        teile.append(Task.priority.in_(f.priority))
    if f.assignee_membership_id is not None:
        teile.append(Task.assignee_membership_id == f.assignee_membership_id)
    if f.unassigned:
        teile.append(Task.assignee_membership_id.is_(None))
    if f.subject_object_id is not None:
        teile.append(Task.subject_object_id == f.subject_object_id)
    if f.due_before is not None:
        teile.append(Task.due_date < f.due_before)
    return teile


def list_tasks(session: Session, visible: Any, f: TaskFilter, *, sort: str, desc: bool, cursor: str | None,
               limit: int | None) -> tuple[list[Any], str | None]:
    key = SORTS.get(sort)
    if key is None:
        raise ValidationFailed(f"sort muss eine von {sorted(SORTS)} sein")
    stmt = (select(Task, ObjectRow)
            .join(ObjectRow, (ObjectRow.id == Task.id) & (ObjectRow.tenant_id == Task.tenant_id))
            .where(visible, *filter_clauses(f)))
    seite = keyset(session, stmt, key, ObjectRow.id, desc=desc, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor
