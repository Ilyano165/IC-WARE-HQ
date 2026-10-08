"""Kommentare an Fachobjekten (C0)."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, refs_for, writing
from ichq.api.v1.tasks import Priority, task_out
from ichq.authz.service import Principal
from ichq.comments import service as comments
from ichq.comments.models import Comment
from ichq.core.errors import Conflict
from ichq.db.session import TenantSession
from ichq.objects import service as objects
from ichq.tasks import service as tasks

router = APIRouter(prefix="/api/v1", tags=["comments"])


class CommentIn(Strict):
    body: str = Field(min_length=1, max_length=10_000)
    kind: Annotated[str, Field(pattern="^(note|question)$")] = "note"
    mentions: list[Annotated[str, Field(max_length=64)]] = Field(default_factory=list, max_length=20)


class CommentPatch(Strict):
    body: str = Field(min_length=1, max_length=10_000)


class DeleteIn(Strict):
    reason: str = Field(min_length=3, max_length=500)


class TaskFromCommentIn(Strict):
    title: str = Field(min_length=1, max_length=300)
    assignee: str | None = Field(default=None, max_length=64)
    due_date: date | None = None
    priority: Priority = "normal"


def comment_out(s: TenantSession, c: Comment, mentions: list[Any] | None = None) -> dict[str, Any]:
    ids = {c.author_membership_id, c.deleted_by_membership_id, *(mentions or [])}
    refs = refs_for(s, ids)
    return {"id": c.public_id, "kind": c.kind, "body": c.body if c.deleted_at is None else None,
            "author": refs.get(c.author_membership_id), "created_at": c.created_at, "edited_at": c.edited_at,
            "deleted": c.deleted_at is not None, "deleted_at": c.deleted_at,
            "deleted_by": refs.get(c.deleted_by_membership_id) if c.deleted_by_membership_id else None,
            "delete_reason": c.delete_reason,
            "mentions": [refs[m] for m in (mentions or []) if m in refs]}


@router.get("/objects/{ref}/comments")
def list_comments(ref: str, p: Principal = Depends(require("comments.read")), db: TenantDB = Depends(tenant_db),
                  cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    with db() as s:
        obj = objects.resolve(s, p, ref)
        rows, weiter = comments.list_for(s, obj, cursor=cursor, limit=limit)
        erw = comments.mentions_of(s, [r[0].id for r in rows])
        return {"items": [comment_out(s, r[0], erw.get(r[0].id)) for r in rows], "next_cursor": weiter}


@router.post("/objects/{ref}/comments", status_code=201)
def create_comment(ref: str, body: CommentIn, p: Principal = Depends(require("comments.create")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        obj = objects.resolve(s, p, ref)
        c = comments.create(s, p, obj, body=body.body, kind=body.kind, mentions=body.mentions)
        return comment_out(s, c, comments.mentions_of(s, [c.id]).get(c.id))


@router.patch("/comments/{ref}")
def edit_comment(ref: str, body: CommentPatch, p: Principal = Depends(require("comments.create")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        c = comments.edit(s, p, ref, body.body)
        return comment_out(s, c, comments.mentions_of(s, [c.id]).get(c.id))


@router.delete("/comments/{ref}", status_code=204)
def delete_comment(ref: str, body: DeleteIn, p: Principal = Depends(require("comments.create")),
                   db: TenantDB = Depends(tenant_db)) -> Response:
    """Tombstone statt Löschen; ``reason`` ist Pflicht (JSON-Body)."""
    with writing(db) as s:
        comments.delete(s, p, ref, body.reason)
    return Response(status_code=204)


@router.get("/comments/{ref}/revisions")
def comment_revisions(ref: str, p: Principal = Depends(require("audit.read")),
                      db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Prüfansicht: alle Fassungen inkl. gelöschtem Text. Nur mit audit.read und sichtbarem Objekt."""
    with db() as s:
        c, _ = comments.load(s, p, ref)
        revs = comments.revisions(s, c)
        refs = refs_for(s, {r.actor_membership_id for r in revs})
        return {"comment": c.public_id, "items": [
            {"kind": r.kind, "body": r.body, "reason": r.reason, "recorded_at": r.recorded_at,
             "actor": refs.get(r.actor_membership_id) if r.actor_membership_id else None} for r in revs]}


@router.post("/comments/{ref}/tasks", status_code=201)
def task_from_comment(ref: str, body: TaskFromCommentIn, p: Principal = Depends(require("tasks.create")),
                      db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Aufgabe aus Kommentar, z. B. Rückfrage des Steuerberaters → Aufgabe für den Geschäftsführer."""
    with writing(db) as s:
        c, obj = comments.load(s, p, ref)
        if c.deleted_at is not None:
            raise Conflict("Aus gelöschten Kommentaren entstehen keine Aufgaben")
        t, o = tasks.create(s, p, title=body.title, description=c.body[:20_000], assignee=body.assignee,
                            due_date=body.due_date, priority=body.priority, subject=obj, source_comment=c)
        return task_out(s, p, t, o)
