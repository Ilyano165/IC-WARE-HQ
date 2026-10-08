"""Aufgaben (C0): Liste mit Filter/Sortierung/Cursor, Anlegen (auch aus Objekt), Ändern, Anhänge."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, object_out, refs_for, writing
from ichq.authz.service import Principal
from ichq.core.errors import ValidationFailed
from ichq.db.session import TenantSession
from ichq.objects import service as objects
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import can_see, visible_clause
from ichq.relations import service as relations
from ichq.tasks import service as tasks
from ichq.tasks.models import TASK_PRIORITY, TASK_STATUS, Task

router = APIRouter(prefix="/api/v1", tags=["tasks"])
Status = Annotated[str, Field(pattern="^(" + "|".join(TASK_STATUS) + ")$")]
Priority = Annotated[str, Field(pattern="^(" + "|".join(TASK_PRIORITY) + ")$")]


class TaskIn(Strict):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    assignee: str | None = Field(default=None, max_length=64)
    due_date: date | None = None
    priority: Priority = "normal"
    subject: str | None = Field(default=None, max_length=64, description="öffentliche ID des Bezugsobjekts")


class TaskFromObjectIn(Strict):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    assignee: str | None = Field(default=None, max_length=64)
    due_date: date | None = None
    priority: Priority = "normal"


class TaskPatch(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20_000)
    assignee: str | None = Field(default=None, max_length=64)
    due_date: date | None = None
    priority: Priority | None = None
    status: Status | None = None


class AttachmentIn(Strict):
    document: str = Field(min_length=1, max_length=64)


def task_out(s: TenantSession, p: Principal, t: Task, o: ObjectRow) -> dict[str, Any]:
    refs = refs_for(s, {t.assignee_membership_id})
    subject = None
    # Bezugsobjekt nur nennen, wenn der Aufrufer es sehen darf (Verantwortliche sehen es nicht automatisch)
    if t.subject_object_id is not None and can_see(s, p, t.subject_object_id):
        so = objects.by_id(s, t.subject_object_id)
        subject = {"id": so.public_id, "type": so.type, "title": so.title}
    return {**object_out(s, o), "description": t.description, "status": t.status, "priority": t.priority,
            "assignee": refs.get(t.assignee_membership_id) if t.assignee_membership_id else None,
            "due_date": t.due_date, "completed_at": t.completed_at, "subject": subject}


@router.get("/tasks")
def list_tasks(p: Principal = Depends(require("tasks.read")), db: TenantDB = Depends(tenant_db),
               status: Annotated[list[str] | None, Query(max_length=5)] = None,
               priority: Annotated[list[str] | None, Query(max_length=4)] = None,
               assignee: Annotated[str | None, Query(max_length=64, description="ID, 'me', 'none'")] = None,
               subject: Annotated[str | None, Query(max_length=64)] = None,
               due_before: date | None = None,
               sort: Annotated[str, Query(pattern="^(created_at|due_date|priority|title)$")] = "created_at",
               order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
               cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    for wert, erlaubt, name in ((status, TASK_STATUS, "status"), (priority, TASK_PRIORITY, "priority")):
        if wert and not set(wert) <= set(erlaubt):
            raise ValidationFailed(f"{name} muss aus {list(erlaubt)} sein")
    with db() as s:
        assignee_id: uuid.UUID | None
        if assignee == "me":
            assignee_id = p.membership_id
        elif assignee == "none":
            assignee_id = None
        else:
            assignee_id = objects.member(s, assignee, active_only=False).id if assignee else None
        subject_id = objects.resolve(s, p, subject).id if subject else None
        f = tasks.TaskFilter(status=tuple(status or ()), priority=tuple(priority or ()),
                             assignee_membership_id=assignee_id, subject_object_id=subject_id, due_before=due_before,
                             unassigned=assignee == "none")
        rows, weiter = tasks.list_tasks(s, visible_clause(p), f, sort=sort, desc=order == "desc", cursor=cursor,
                                        limit=limit)
        return {"items": [task_out(s, p, t, o) for t, o, *_ in rows], "next_cursor": weiter}


@router.post("/tasks", status_code=201)
def create_task(body: TaskIn, p: Principal = Depends(require("tasks.create")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        subject = objects.resolve(s, p, body.subject) if body.subject else None
        t, o = tasks.create(s, p, title=body.title, description=body.description, assignee=body.assignee,
                            due_date=body.due_date, priority=body.priority, subject=subject)
        return task_out(s, p, t, o)


@router.post("/objects/{ref}/tasks", status_code=201)
def create_task_for_object(ref: str, body: TaskFromObjectIn, p: Principal = Depends(require("tasks.create")),
                           db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Aufgabe aus einem Fachobjekt, z. B. Beleg → „IBAN prüfen"."""
    with writing(db) as s:
        subject = objects.resolve(s, p, ref)
        t, o = tasks.create(s, p, title=body.title, description=body.description, assignee=body.assignee,
                            due_date=body.due_date, priority=body.priority, subject=subject)
        return task_out(s, p, t, o)


@router.get("/tasks/{ref}")
def get_task(ref: str, p: Principal = Depends(require("tasks.read")),
             db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        t, o = tasks.get(s, p, ref)
        return task_out(s, p, t, o)


@router.patch("/tasks/{ref}")
def update_task(ref: str, body: TaskPatch, p: Principal = Depends(require("tasks.update")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    for pflicht in ("title", "status", "priority"):
        if pflicht in changes and changes[pflicht] is None:
            raise ValidationFailed(f"{pflicht} darf nicht leer sein")
    with writing(db) as s:
        t, o = tasks.update(s, p, ref, changes)
        return task_out(s, p, t, o)


@router.post("/tasks/{ref}/attachments", status_code=201)
def attach(ref: str, body: AttachmentIn, p: Principal = Depends(require("tasks.update")),
           db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Anhang = typisierte Verknüpfung ``attachment`` von der Aufgabe zu einem Dokument."""
    with writing(db) as s:
        _, o = tasks.get(s, p, ref)
        doc = objects.resolve(s, p, body.document, type_="document")
        link = relations.create_link(s, p, o, doc, "attachment")
        return {"id": link.public_id, "task": o.public_id, "document": doc.public_id}
