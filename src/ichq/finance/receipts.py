"""Ausgaben mit Beleg: erfassen, Beleg anhängen (geprüftes Dokument), Zahlungsstatus, fehlende Belege, Stornieren.

Belegstatus (aus Daten berechnet, nie gesetzt):
* ``missing``   — kein Dokument verknüpft
* ``unchecked`` — Dokument verknüpft, Virenprüfung noch offen (Quarantäne)
* ``rejected``  — Dokument bei der Prüfung als gefährlich erkannt
* ``complete``  — Dokument verknüpft und sauber geprüft
Eine stornierte Ausgabe (Fehlerfassung) bleibt sichtbar, zählt aber nirgends mehr mit.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.db.paging import SortKey, keyset
from ichq.documents.models import Document
from ichq.finance import sperre
from ichq.finance.models_receipts import MAX_TEXT, Receipt
from ichq.objects.models import ObjectRow
from ichq.objects.service import ARCHIVE_GUARDS, clean_title, create_object, member, resolve

EVIDENCE = ("missing", "unchecked", "rejected", "complete")
_SCAN = select(Document.scan_status).where(Document.id == Receipt.document_id).correlate(Receipt).scalar_subquery()
BELEG = case((Receipt.document_id.is_(None), "missing"), (_SCAN == "clean", "complete"),
             (_SCAN == "infected", "rejected"), else_="unchecked")
SORTS: dict[str, SortKey] = {
    "expense_date": SortKey("expense_date", Receipt.expense_date, "date"),
    "created_at": SortKey("created_at", ObjectRow.created_at, "ts"),
    "amount": SortKey("amount", Receipt.amount_minor, "int"),
}
BUCHUNG = {"expense_date", "amount_minor", "currency", "tax_rate_bp", "supplier_name", "category", "description",
           "project"}                               # in einem abgeschlossenen Monat gesperrt (wie Trigger 0015)
ARCHIVE_GUARDS["receipt"] = lambda _s, _o: "Ausgaben werden nicht archiviert — Fehlerfassung bitte stornieren"


def _pruefe(w: dict[str, Any]) -> None:
    if "amount_minor" in w and (w["amount_minor"] is None or w["amount_minor"] <= 0):
        raise ValidationFailed("amount_minor muss positiv sein")
    if w.get("tax_rate_bp") is not None and not 0 <= w["tax_rate_bp"] <= 10_000:
        raise ValidationFailed("tax_rate_bp außerhalb 0–10000")
    if len(w.get("description") or "") > MAX_TEXT:
        raise ValidationFailed(f"description: höchstens {MAX_TEXT} Zeichen")


def _text(v: Any, n: int) -> str | None:
    return (" ".join(str(v).split())[:n] or None) if v is not None else None


def _setze(session: Session, principal: Principal, r: Receipt, w: dict[str, Any], today: date) -> None:
    for f, n in (("supplier_name", 200), ("category", 60), ("missing_reason", 500)):
        if f in w:
            setattr(r, f, _text(w[f], n))
    for f in ("expense_date", "amount_minor", "currency", "tax_rate_bp", "due_date", "follow_up_on"):
        if f in w and (w[f] is not None or f in ("tax_rate_bp", "due_date", "follow_up_on")):
            setattr(r, f, w[f])
    if "description" in w:
        r.description = (w["description"] or "").strip()
    if "project" in w:
        r.project_id = resolve(session, principal, w["project"], type_="project").id if w["project"] else None
    if "responsible" in w:
        r.responsible_membership_id = member(session, w["responsible"]).id if w["responsible"] else None
    if "paid_on" in w or "payment_status" in w:
        bezahlt = w.get("payment_status", r.payment_status) == "paid"
        datum = w.get("paid_on") or (r.paid_on if bezahlt else None) or (today if bezahlt else None)
        if datum and datum > today:
            raise ValidationFailed("paid_on darf nicht in der Zukunft liegen")
        r.payment_status, r.paid_on = ("paid", datum) if bezahlt else ("unpaid", None)
    if r.expense_date > today:
        raise ValidationFailed("expense_date darf nicht in der Zukunft liegen")


def create(session: Session, principal: Principal, *, title: str, werte: dict[str, Any], currency: str,
           today: date) -> tuple[Receipt, ObjectRow]:
    _pruefe(werte)
    if not werte.get("amount_minor"):
        raise ValidationFailed("amount_minor fehlt")
    o = create_object(session, type_="receipt", title=title, actor_membership_id=principal.membership_id,
                      search_text=" ".join(str(werte.get(k) or "") for k in ("supplier_name", "category"))[:1000])
    r = Receipt(id=o.id, tenant_id=o.tenant_id, expense_date=werte.get("expense_date") or today,
                amount_minor=werte["amount_minor"], currency=werte.get("currency") or currency)
    _setze(session, principal, r, werte, today)
    sperre.pruefe(session, r.expense_date, r.paid_on)
    session.add(r)
    session.flush()
    if werte.get("document"):
        _beleg(session, principal, r, o, werte["document"])
    activity(session, o.id, "receipt.created", actor_membership_id=principal.membership_id)
    audit(session, "receipt.created", actor_membership_id=principal.membership_id, target_type="receipt",
          target_id=o.public_id)
    return r, o


def get(session: Session, principal: Principal, ref: str) -> tuple[Receipt, ObjectRow]:
    o = resolve(session, principal, ref, type_="receipt")
    r = session.get(Receipt, o.id)
    if r is None:
        raise NotFound()
    return r, o


def _offen(r: Receipt) -> None:
    if r.voided_at is not None:
        raise Conflict("Stornierte Ausgaben sind unveränderlich")


def update(session: Session, principal: Principal, ref: str, changes: dict[str, Any],
           today: date) -> tuple[Receipt, ObjectRow]:
    r, o = get(session, principal, ref)
    _offen(r)
    _pruefe(changes)
    if "title" in changes:
        o.title = clean_title(changes["title"])
    alt_datum, alt_bezahlt = r.expense_date, r.paid_on
    _setze(session, principal, r, changes, today)
    if BUCHUNG & changes.keys():
        sperre.pruefe(session, alt_datum, r.expense_date)
    if r.paid_on != alt_bezahlt:
        sperre.pruefe(session, alt_bezahlt, r.paid_on)
    session.flush()
    activity(session, o.id, "receipt.updated", actor_membership_id=principal.membership_id,
             data={"fields": sorted(changes)})
    audit(session, "receipt.updated", actor_membership_id=principal.membership_id, target_type="receipt",
          target_id=o.public_id, data={"fields": sorted(changes)})
    return r, o


def _beleg(session: Session, principal: Principal, r: Receipt, o: ObjectRow, doc_ref: str | None) -> None:
    if doc_ref is None:
        r.document_id = None
    else:
        r.document_id = resolve(session, principal, doc_ref, type_="document").id   # nur sichtbare Dokumente
    session.flush()
    activity(session, o.id, "receipt.evidence_changed", actor_membership_id=principal.membership_id,
             data={"attached": doc_ref is not None})


def set_document(session: Session, principal: Principal, ref: str, doc_ref: str | None) -> tuple[Receipt, ObjectRow]:
    r, o = get(session, principal, ref)
    _offen(r)
    _beleg(session, principal, r, o, doc_ref)
    audit(session, "receipt.evidence_changed", actor_membership_id=principal.membership_id, target_type="receipt",
          target_id=o.public_id, data={"attached": doc_ref is not None})
    return r, o


def void(session: Session, principal: Principal, ref: str, reason: str) -> tuple[Receipt, ObjectRow]:
    r, o = get(session, principal, ref)
    _offen(r)
    grund = " ".join(reason.split())[:500]
    if not grund:
        raise ValidationFailed("Grund für das Stornieren fehlt")
    sperre.pruefe(session, r.expense_date)
    jetzt = session.scalar(select(func.now()))
    r.voided_at, r.void_reason = jetzt, grund
    session.flush()
    activity(session, o.id, "receipt.voided", actor_membership_id=principal.membership_id)
    audit(session, "receipt.voided", actor_membership_id=principal.membership_id, target_type="receipt",
          target_id=o.public_id)
    return r, o


def evidence(session: Session, r: Receipt) -> str:
    if r.document_id is None:
        return "missing"
    scan = session.scalar(select(Document.scan_status).where(Document.id == r.document_id))
    return {"clean": "complete", "infected": "rejected"}.get(scan or "", "unchecked")


@dataclass(frozen=True)
class ReceiptFilter:
    evidence: tuple[str, ...] = ()
    payment_status: tuple[str, ...] = ()
    project_id: uuid.UUID | None = None
    responsible_membership_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    follow_up_before: date | None = None
    voided: bool = False
    q: str | None = None


def filter_clauses(f: ReceiptFilter) -> list[Any]:
    teile: list[Any] = [Receipt.voided_at.is_not(None) if f.voided else Receipt.voided_at.is_(None)]
    if f.evidence:
        teile.append(BELEG.in_(f.evidence))
    if f.payment_status:
        teile.append(Receipt.payment_status.in_(f.payment_status))
    if f.project_id is not None:
        teile.append(Receipt.project_id == f.project_id)
    if f.responsible_membership_id is not None:
        teile.append(Receipt.responsible_membership_id == f.responsible_membership_id)
    if f.date_from is not None:
        teile.append(Receipt.expense_date >= f.date_from)
    if f.date_to is not None:
        teile.append(Receipt.expense_date <= f.date_to)
    if f.follow_up_before is not None:
        teile += [Receipt.follow_up_on < f.follow_up_before, BELEG != "complete"]
    if f.q:
        muster = f"%{f.q.lower()}%"
        teile.append(or_(func.lower(ObjectRow.title).like(muster), func.lower(Receipt.supplier_name).like(muster),
                         func.lower(Receipt.category).like(muster)))
    return teile


def list_receipts(session: Session, visible: Any, f: ReceiptFilter, *, sort: str, desc: bool, cursor: str | None,
                  limit: int | None) -> tuple[list[Any], str | None]:
    key = SORTS.get(sort)
    if key is None:
        raise ValidationFailed(f"sort muss eine von {sorted(SORTS)} sein")
    stmt = (select(Receipt, ObjectRow, BELEG.label("evidence")).join(ObjectRow, ObjectRow.id == Receipt.id)
            .where(visible, *filter_clauses(f)))
    seite = keyset(session, stmt, key, ObjectRow.id, desc=desc, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor
