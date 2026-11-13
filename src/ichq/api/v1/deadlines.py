"""Fristen (ADR-020 Nr. 10): selbst angelegt, mit optionaler Quelle — HQ gibt keine Fristen vor und prüft keine."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, object_out, refs_for, writing
from ichq.authz.service import Principal
from ichq.core.errors import ValidationFailed
from ichq.db.session import TenantSession
from ichq.finance import deadlines
from ichq.finance.models_deadlines import CATEGORY, DEADLINE_STATUS, Deadline
from ichq.objects import service as objects
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import visible_clause
from ichq.tenancy.service import company_today

router = APIRouter(prefix="/api/v1", tags=["deadlines"])
KAT = "^(tax|contract|payroll|insurance|authority|other)$"
WDH = "^(none|monthly|quarterly|yearly)$"


class DeadlineFields(Strict):
    due_on: date | None = None
    category: str | None = Field(default=None, pattern=KAT)
    description: str | None = Field(default=None, max_length=5000)
    source_reference: str | None = Field(default=None, max_length=500,
                                         description="Fundstelle/Quelle als Freitext — wird nicht geprüft")
    responsible: str | None = Field(default=None, max_length=64)
    remind_days_before: int | None = Field(default=None, ge=0, le=365)
    recurrence: str | None = Field(default=None, pattern=WDH)


class DeadlineIn(DeadlineFields):
    title: str = Field(min_length=1, max_length=300)
    due_on: date


class DeadlinePatch(DeadlineFields):
    title: str | None = Field(default=None, min_length=1, max_length=300)


class CloseIn(Strict):
    note: str = Field(default="", max_length=500)


def deadline_out(s: TenantSession, d: Deadline, o: ObjectRow, today: date) -> dict[str, Any]:
    refs = refs_for(s, {d.responsible_membership_id, d.done_by_membership_id})
    return {**object_out(s, o), "due_on": d.due_on, "category": d.category, "description": d.description,
            "source_reference": d.source_reference,
            "source_status": "user_reference" if d.source_reference else "unconfirmed",
            "responsible": refs.get(d.responsible_membership_id) if d.responsible_membership_id else None,
            "remind_days_before": d.remind_days_before, "reminder_on": deadlines.reminder_on(d),
            "recurrence": d.recurrence, "next_due_on": deadlines.next_due(d), "status": d.status,
            "overdue": d.status == "open" and d.due_on < today, "days_left": (d.due_on - today).days,
            "done_at": d.done_at, "done_note": d.done_note,
            "done_by": refs.get(d.done_by_membership_id) if d.done_by_membership_id else None}


@router.get("/deadlines")
def list_deadlines(p: Principal = Depends(require("finance.read")), db: TenantDB = Depends(tenant_db),
                   status: Annotated[list[str] | None, Query(max_length=3)] = None,
                   category: Annotated[list[str] | None, Query(max_length=6)] = None,
                   responsible: Annotated[str | None, Query(max_length=64, description="ID oder 'me'")] = None,
                   due_from: date | None = None, due_to: date | None = None, overdue: bool = False,
                   reminder_due: bool = False, q: Annotated[str | None, Query(max_length=100)] = None,
                   sort: Annotated[str, Query(pattern="^(due_on|created_at)$")] = "due_on",
                   order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                   cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    if status and not set(status) <= set(DEADLINE_STATUS):
        raise ValidationFailed(f"status muss aus {list(DEADLINE_STATUS)} sein")
    if category and not set(category) <= set(CATEGORY):
        raise ValidationFailed(f"category muss aus {list(CATEGORY)} sein")
    with db() as s:
        heute = company_today(s)
        wer = p.membership_id if responsible == "me" else (
            objects.member(s, responsible, active_only=False).id if responsible else None)
        f = deadlines.DeadlineFilter(status=tuple(status or ("open",)), category=tuple(category or ()),
                                     responsible_membership_id=wer, due_from=due_from, due_to=due_to,
                                     overdue_before=heute if overdue else None,
                                     remind_by=heute if reminder_due else None, q=q)
        rows, weiter = deadlines.list_deadlines(s, visible_clause(p), f, sort=sort, desc=order == "desc",
                                                cursor=cursor, limit=limit)
        return {"items": [deadline_out(s, d, o, heute) for d, o, *_ in rows], "next_cursor": weiter}


@router.post("/deadlines", status_code=201)
def create_deadline(body: DeadlineIn, p: Principal = Depends(require("finance.create")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        d, o = deadlines.create(s, p, title=body.title, werte=body.model_dump(exclude={"title"}, exclude_none=True))
        return deadline_out(s, d, o, company_today(s))


@router.get("/deadlines/{ref}")
def get_deadline(ref: str, p: Principal = Depends(require("finance.read")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        d, o = deadlines.get(s, p, ref)
        return deadline_out(s, d, o, company_today(s))


@router.patch("/deadlines/{ref}")
def update_deadline(ref: str, body: DeadlinePatch, p: Principal = Depends(require("finance.update")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    for pflicht in ("title", "due_on", "category", "remind_days_before", "recurrence"):
        if pflicht in changes and changes[pflicht] is None:
            raise ValidationFailed(f"{pflicht} darf nicht leer sein")
    with writing(db) as s:
        d, o = deadlines.update(s, p, ref, changes)
        return deadline_out(s, d, o, company_today(s))


@router.post("/deadlines/{ref}/complete")
def complete_deadline(ref: str, body: CloseIn | None = None, p: Principal = Depends(require("finance.update")),
                      db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Erledigt melden. Bei Wiederholung wird die nächste Frist angelegt (``next``)."""
    with writing(db) as s:
        heute = company_today(s)
        d, o, folge = deadlines.complete(s, p, ref, body.note if body else "")
        return {**deadline_out(s, d, o, heute), "next": deadline_out(s, *folge, heute) if folge else None}


@router.post("/deadlines/{ref}/cancel")
def cancel_deadline(ref: str, body: CloseIn, p: Principal = Depends(require("finance.update")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Absagen (entfällt) — mit Grund, bleibt sichtbar."""
    with writing(db) as s:
        d, o = deadlines.cancel(s, p, ref, body.note)
        return deadline_out(s, d, o, company_today(s))
