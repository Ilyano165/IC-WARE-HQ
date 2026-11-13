"""Fristen: anlegen, zuständig, Erinnerung, erledigen (mit Folgefrist bei Wiederholung), absagen, Liste.

HQ kennt keine gesetzlichen Fristen. Datum, Wiederholung und Quelle stammen vom Nutzer; ``source_status`` sagt nur,
ob eine Quelle angegeben ist (``user_reference``) oder nicht (``unconfirmed``) — geprüft wird sie nie.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.core.kalender import PERIODEN, plus_monate
from ichq.db.paging import SortKey, keyset
from ichq.finance.models_deadlines import CATEGORY, MAX_TEXT, RECURRENCE, Deadline
from ichq.objects.models import ObjectRow
from ichq.objects.service import clean_title, create_object, member, resolve

SORTS: dict[str, SortKey] = {
    "due_on": SortKey("due_on", Deadline.due_on, "date"),
    "created_at": SortKey("created_at", ObjectRow.created_at, "ts"),
}


def _pruefe(w: dict[str, Any]) -> None:
    if w.get("category") is not None and w["category"] not in CATEGORY:
        raise ValidationFailed("category ist ungültig")
    if w.get("recurrence") is not None and w["recurrence"] not in RECURRENCE:
        raise ValidationFailed("recurrence ist ungültig")
    if w.get("remind_days_before") is not None and not 0 <= w["remind_days_before"] <= 365:
        raise ValidationFailed("remind_days_before: 0–365")
    if len(w.get("description") or "") > MAX_TEXT:
        raise ValidationFailed(f"description: höchstens {MAX_TEXT} Zeichen")


def _setze(session: Session, d: Deadline, w: dict[str, Any]) -> None:
    for f in ("due_on", "category", "remind_days_before", "recurrence"):
        if w.get(f) is not None:
            setattr(d, f, w[f])
    if "description" in w:
        d.description = (w["description"] or "").strip()
    if "source_reference" in w:
        d.source_reference = " ".join((w["source_reference"] or "").split())[:500] or None
    if "responsible" in w:
        d.responsible_membership_id = member(session, w["responsible"]).id if w["responsible"] else None


def create(session: Session, principal: Principal, *, title: str, werte: dict[str, Any]) -> tuple[Deadline, ObjectRow]:
    _pruefe(werte)
    o = create_object(session, type_="deadline", title=title, actor_membership_id=principal.membership_id,
                      search_text=(werte.get("description") or "")[:1000])
    d = Deadline(id=o.id, tenant_id=o.tenant_id, due_on=werte["due_on"])
    _setze(session, d, werte)
    session.add(d)
    session.flush()
    activity(session, o.id, "deadline.created", actor_membership_id=principal.membership_id)
    audit(session, "deadline.created", actor_membership_id=principal.membership_id, target_type="deadline",
          target_id=o.public_id)
    return d, o


def get(session: Session, principal: Principal, ref: str) -> tuple[Deadline, ObjectRow]:
    o = resolve(session, principal, ref, type_="deadline")
    d = session.get(Deadline, o.id)
    if d is None:
        raise NotFound()
    return d, o


def _offen(d: Deadline) -> None:
    if d.status != "open":
        raise Conflict("Frist ist abgeschlossen — Änderungen nur an offenen Fristen")


def update(session: Session, principal: Principal, ref: str, changes: dict[str, Any]) -> tuple[Deadline, ObjectRow]:
    d, o = get(session, principal, ref)
    _offen(d)
    _pruefe(changes)
    if "title" in changes:
        o.title = clean_title(changes["title"])
    _setze(session, d, changes)
    if "description" in changes:
        o.search_text = d.description[:1000] or None
    session.flush()
    activity(session, o.id, "deadline.updated", actor_membership_id=principal.membership_id,
             data={"fields": sorted(changes)})
    audit(session, "deadline.updated", actor_membership_id=principal.membership_id, target_type="deadline",
          target_id=o.public_id, data={"fields": sorted(changes)})
    return d, o


def next_due(d: Deadline) -> date | None:
    return plus_monate(d.due_on, PERIODEN[d.recurrence]) if d.recurrence in PERIODEN else None


def _abschliessen(session: Session, principal: Principal, ref: str, status: str, note: str) -> tuple[
        Deadline, ObjectRow]:
    d, o = get(session, principal, ref)
    _offen(d)
    jetzt = session.scalar(select(func.now()))                 # erst Wert holen, dann Felder gemeinsam setzen
    d.status, d.done_at, d.done_by_membership_id = status, jetzt, principal.membership_id
    d.done_note = " ".join(note.split())[:500] or None
    session.flush()
    activity(session, o.id, f"deadline.{status}", actor_membership_id=principal.membership_id)
    audit(session, f"deadline.{status}", actor_membership_id=principal.membership_id, target_type="deadline",
          target_id=o.public_id)
    return d, o


def complete(session: Session, principal: Principal, ref: str, note: str) -> tuple[Deadline, ObjectRow,
                                                                                 tuple[Deadline, ObjectRow] | None]:
    """Erledigen. Bei Wiederholung entsteht genau eine Folgefrist (eindeutig über ``follows_deadline_id``)."""
    d, o = _abschliessen(session, principal, ref, "done", note)
    faellig = next_due(d)
    if faellig is None:
        return d, o, None
    werte = {"due_on": faellig, "category": d.category, "description": d.description,
             "source_reference": d.source_reference, "remind_days_before": d.remind_days_before,
             "recurrence": d.recurrence}
    n, no = create(session, principal, title=o.title, werte=werte)
    n.responsible_membership_id, n.follows_deadline_id = d.responsible_membership_id, d.id
    session.flush()
    return d, o, (n, no)


def cancel(session: Session, principal: Principal, ref: str, note: str) -> tuple[Deadline, ObjectRow]:
    if len(" ".join(note.split())) < 3:
        raise ValidationFailed("Grund angeben (mindestens 3 Zeichen)")
    return _abschliessen(session, principal, ref, "cancelled", note)


def reminder_on(d: Deadline) -> date:
    return d.due_on - timedelta(days=d.remind_days_before)


@dataclass(frozen=True)
class DeadlineFilter:
    status: tuple[str, ...] = ("open",)
    category: tuple[str, ...] = ()
    responsible_membership_id: uuid.UUID | None = None
    due_from: date | None = None
    due_to: date | None = None
    overdue_before: date | None = None          # offen und due_on < Datum
    remind_by: date | None = None               # offen und Erinnerungsdatum ≤ Datum
    q: str | None = None


def filter_clauses(f: DeadlineFilter) -> list[Any]:
    teile: list[Any] = [ObjectRow.archived_at.is_(None)]
    if f.status:
        teile.append(Deadline.status.in_(f.status))
    if f.category:
        teile.append(Deadline.category.in_(f.category))
    if f.responsible_membership_id is not None:
        teile.append(Deadline.responsible_membership_id == f.responsible_membership_id)
    if f.due_from is not None:
        teile.append(Deadline.due_on >= f.due_from)
    if f.due_to is not None:
        teile.append(Deadline.due_on <= f.due_to)
    if f.overdue_before is not None:
        teile += [Deadline.status == "open", Deadline.due_on < f.overdue_before]
    if f.remind_by is not None:
        teile += [Deadline.status == "open", Deadline.due_on - Deadline.remind_days_before <= f.remind_by]
    if f.q:
        muster = f"%{f.q.lower()}%"
        teile.append(or_(func.lower(ObjectRow.title).like(muster), func.lower(Deadline.description).like(muster),
                         func.lower(Deadline.source_reference).like(muster)))
    return teile


def list_deadlines(session: Session, visible: Any, f: DeadlineFilter, *, sort: str, desc: bool, cursor: str | None,
                   limit: int | None) -> tuple[list[Any], str | None]:
    key = SORTS.get(sort)
    if key is None:
        raise ValidationFailed(f"sort muss eine von {sorted(SORTS)} sein")
    stmt = select(Deadline, ObjectRow).join(ObjectRow, ObjectRow.id == Deadline.id).where(visible, *filter_clauses(f))
    seite = keyset(session, stmt, key, ObjectRow.id, desc=desc, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor
