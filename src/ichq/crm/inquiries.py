"""Anfragen: Eingang, Zuständigkeit, nächste Aktion, Wiedervorlage, Abschluss (gewonnen/verloren/erledigt)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import Date, case, cast, func, literal, select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import NotFound, ValidationFailed
from ichq.crm.models import INQUIRY_OPEN, INQUIRY_SOURCE, INQUIRY_STATUS, MAX_NOTES, PRIORITY, Customer, Inquiry
from ichq.db.paging import SortKey, keyset
from ichq.objects.models import ObjectRow
from ichq.objects.service import clean_title, create_object, member, resolve

_RANG = case({"urgent": 4, "high": 3, "normal": 2, "low": 1}, value=Inquiry.priority, else_=0)
SORTS: dict[str, SortKey] = {
    "received_on": SortKey("received_on", Inquiry.received_on, "date"),
    "follow_up_on": SortKey("follow_up_on", func.coalesce(Inquiry.follow_up_on, cast(literal("9999-12-31"), Date)),
                            "date"),
    "priority": SortKey("priority", _RANG, "int"),
    "title": SortKey("title", ObjectRow.title, "text"),
}


def _pruefe(w: dict[str, Any]) -> None:
    for feld, erlaubt in (("status", INQUIRY_STATUS), ("source", INQUIRY_SOURCE), ("priority", PRIORITY)):
        if feld in w and w[feld] not in erlaubt:
            raise ValidationFailed(f"{feld} ist ungültig")
    if len(w.get("description") or "") > MAX_NOTES:
        raise ValidationFailed(f"description: höchstens {MAX_NOTES} Zeichen")


def _kunde(session: Session, principal: Principal, ref: str | None) -> uuid.UUID | None:
    if not ref:
        return None
    o = resolve(session, principal, ref, type_="customer")     # nur sichtbare Kunden zuordnen
    return o.id


def create(session: Session, principal: Principal, *, title: str, werte: dict[str, Any], today: date) -> tuple[
        Inquiry, ObjectRow]:
    _pruefe(werte)
    o = create_object(session, type_="inquiry", title=title, actor_membership_id=principal.membership_id,
                      search_text=(werte.get("description") or "")[:1000])
    i = Inquiry(id=o.id, tenant_id=o.tenant_id, description=(werte.get("description") or "").strip(),
                source=werte.get("source") or "other", received_on=werte.get("received_on") or today,
                priority=werte.get("priority") or "normal",
                customer_id=_kunde(session, principal, werte.get("customer")),
                owner_membership_id=member(session, werte["owner"]).id if werte.get("owner") else None,
                next_action=werte.get("next_action") or None, follow_up_on=werte.get("follow_up_on"))
    session.add(i)
    session.flush()
    activity(session, o.id, "inquiry.created", actor_membership_id=principal.membership_id)
    audit(session, "inquiry.created", actor_membership_id=principal.membership_id, target_type="inquiry",
          target_id=o.public_id)
    return i, o


def get(session: Session, principal: Principal, ref: str) -> tuple[Inquiry, ObjectRow]:
    o = resolve(session, principal, ref, type_="inquiry")
    i = session.get(Inquiry, o.id)
    if i is None:
        raise NotFound()
    return i, o


def update(session: Session, principal: Principal, ref: str, changes: dict[str, Any]) -> tuple[Inquiry, ObjectRow]:
    i, o = get(session, principal, ref)
    _pruefe(changes)
    alt = i.status
    if "title" in changes:
        o.title = clean_title(changes["title"])
    if "description" in changes:
        i.description = (changes["description"] or "").strip()
        o.search_text = i.description[:1000] or None
    for f in ("source", "priority", "received_on", "follow_up_on"):
        if f in changes and (changes[f] is not None or f == "follow_up_on"):
            setattr(i, f, changes[f])
    if "next_action" in changes:
        i.next_action = changes["next_action"] or None
    if "customer" in changes:
        i.customer_id = _kunde(session, principal, changes["customer"])
    if "owner" in changes:
        i.owner_membership_id = member(session, changes["owner"]).id if changes["owner"] else None
    if changes.get("status") and changes["status"] != alt:
        jetzt = session.scalar(select(func.now()))           # erst Wert holen, dann Felder gemeinsam setzen
        i.status, i.closed_at = changes["status"], (None if changes["status"] in INQUIRY_OPEN else jetzt)
    session.flush()
    if i.status != alt:
        activity(session, o.id, "inquiry.status_changed", actor_membership_id=principal.membership_id,
                 data={"from": alt, "to": i.status})
    activity(session, o.id, "inquiry.updated", actor_membership_id=principal.membership_id,
             data={"fields": sorted(changes)})
    audit(session, "inquiry.updated", actor_membership_id=principal.membership_id, target_type="inquiry",
          target_id=o.public_id, data={"fields": sorted(changes), "status_from": alt, "status_to": i.status})
    return i, o


@dataclass(frozen=True)
class InquiryFilter:
    status: tuple[str, ...] = ()
    owner_membership_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    follow_up_before: date | None = None     # Wiedervorlage fällig: follow_up_on < Datum, nur offene
    archived: bool = False


def filter_clauses(f: InquiryFilter) -> list[Any]:
    teile: list[Any] = [ObjectRow.archived_at.is_not(None) if f.archived else ObjectRow.archived_at.is_(None)]
    if f.status:
        teile.append(Inquiry.status.in_(f.status))
    if f.owner_membership_id is not None:
        teile.append(Inquiry.owner_membership_id == f.owner_membership_id)
    if f.customer_id is not None:
        teile.append(Inquiry.customer_id == f.customer_id)
    if f.follow_up_before is not None:
        teile += [Inquiry.follow_up_on < f.follow_up_before, Inquiry.status.in_(INQUIRY_OPEN)]
    return teile


def list_inquiries(session: Session, visible: Any, f: InquiryFilter, *, sort: str, desc: bool,
                   cursor: str | None, limit: int | None) -> tuple[list[Any], str | None]:
    key = SORTS.get(sort)
    if key is None:
        raise ValidationFailed(f"sort muss eine von {sorted(SORTS)} sein")
    stmt = select(Inquiry, ObjectRow).join(ObjectRow, ObjectRow.id == Inquiry.id).where(visible, *filter_clauses(f))
    seite = keyset(session, stmt, key, ObjectRow.id, desc=desc, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor


def customer_title(session: Session, customer_id: uuid.UUID | None) -> tuple[str, str] | None:
    if customer_id is None:
        return None
    zeile = session.execute(select(ObjectRow.public_id, ObjectRow.title).join(Customer, Customer.id == ObjectRow.id)
                            .where(ObjectRow.id == customer_id)).one_or_none()
    return None if zeile is None else (zeile[0], zeile[1])
