"""Konsumenten der Outbox-Ereignisse (M0: Benachrichtigungen hängen an denselben Ereignissen).

Jeder Prozess, der den Worker startet, muss dieses Modul laden — ``ichq.cli`` tut das, und
``assert_handlers`` bricht den Start ab, wenn ein von der Plattform erzeugtes Ereignis keinen Handler hat.
Außerdem: geplante Regeln (``scan``) für Fälligkeiten, aufgerufen per ``ichq notifications-scan``.
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ichq.authz.service import decide
from ichq.comments.models import Comment
from ichq.comments.service import mentions_of
from ichq.jobs.worker import HANDLERS, Job, handler
from ichq.notifications.service import deliver
from ichq.objects.service import by_id
from ichq.objects.visibility import principal_for_membership
from ichq.tasks.models import Task

# Ereignisse, die die Core-Plattform erzeugt — jedes braucht einen Handler.
EMITTED = ("comment.created", "task.assigned", "document.uploaded")
MAX_EMPFAENGER = 50


def assert_handlers() -> None:
    fehlend = [e for e in EMITTED if e not in HANDLERS]
    if fehlend:
        raise RuntimeError(f"Outbox-Ereignisse ohne Handler: {fehlend}")


@handler("comment.created")
def _kommentar(session: Session, job: Job) -> None:
    c = session.get(Comment, uuid.UUID(job.payload["comment_id"]))
    if c is None or c.deleted_at is not None:
        return
    obj = by_id(session, c.object_id)
    for mid in mentions_of(session, [c.id]).get(c.id, []):
        if mid != c.author_membership_id:
            deliver(session, mid, "comment.mention", title=f"Erwähnung in: {obj.title}"[:200], obj=obj,
                    dedup_key=f"mention:{c.id}")
    if c.kind == "question" and obj.created_by_membership_id not in (None, c.author_membership_id):
        assert obj.created_by_membership_id is not None
        deliver(session, obj.created_by_membership_id, "comment.question", title=f"Rückfrage zu: {obj.title}"[:200],
                obj=obj, dedup_key=f"question:{c.id}")


@handler("task.assigned")
def _zugewiesen(session: Session, job: Job) -> None:
    task = session.get(Task, uuid.UUID(job.payload["task_id"]))
    if task is None or task.assignee_membership_id is None:
        return
    obj = by_id(session, task.id)
    deliver(session, task.assignee_membership_id, "task.assigned", title=f"Neue Aufgabe: {obj.title}"[:200],
            obj=obj, dedup_key=f"assigned:{task.id}:{task.assignee_membership_id}")


@handler("document.uploaded")
def _hochgeladen(session: Session, job: Job) -> None:
    obj = by_id(session, uuid.UUID(job.payload["document_id"]))
    mitglieder = session.scalars(text("SELECT id FROM memberships WHERE status = 'active' ORDER BY created_at, id "
                                      "LIMIT 500")).all()
    zugestellt = 0
    for mid in mitglieder:
        if zugestellt >= MAX_EMPFAENGER:
            break
        if mid == obj.created_by_membership_id:
            continue
        p = principal_for_membership(session, mid)
        if p is not None and decide(p, "files.update") and deliver(
                session, mid, "document.review_pending", title=f"Wartet auf Prüfung: {obj.title}"[:200], obj=obj,
                dedup_key=f"review:{obj.id}"):
            zugestellt += 1


Rule = Callable[[Session, date], int]


def _ueberfaellige_aufgaben(session: Session, heute: date) -> int:
    rows = session.execute(select(Task.id, Task.assignee_membership_id, Task.due_date).where(
        Task.status.in_(("open", "in_progress", "blocked")), Task.due_date < heute,
        Task.assignee_membership_id.is_not(None)).order_by(Task.due_date, Task.id).limit(1000)).all()
    n = 0
    for tid, mid, faellig in rows:
        if mid is None or faellig is None:
            continue
        obj = by_id(session, tid)
        n += deliver(session, mid, "task.overdue", title=f"Überfällig: {obj.title}"[:200], obj=obj,
                     dedup_key=f"overdue:{tid}:{faellig.isoformat()}")
    return n


# Regeln für „Rechnung seit 14 Tagen überfällig" und „Vertrag läuft in 30 Tagen aus" werden hier ergänzt,
# sobald es Rechnungen und Verträge gibt (Arten in KINDS sind reserviert).
RULES: dict[str, Rule] = {"task.overdue": _ueberfaellige_aufgaben}


def scan(session: Session, heute: date) -> dict[str, int]:
    """Alle geplanten Regeln für die Firma des laufenden Mandantenkontexts."""
    return {name: rule(session, heute) for name, rule in RULES.items()}
