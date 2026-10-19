"""Rechnungen (ADR-020): Entwurf, Positionen, Ausstellen, Versandvermerk, Storno, Zahlungen, Mahn-/Kontakthistorie."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field
from sqlalchemy import select

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, object_out, object_ref, refs_for, writing
from ichq.authz.service import Principal, decide
from ichq.core.errors import ValidationFailed
from ichq.db.session import TenantSession
from ichq.finance import invoices, payments
from ichq.finance.models_invoices import INVOICE_STATUS, Invoice, InvoiceLine
from ichq.objects import service as objects
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import can_see, visible_clause
from ichq.tenancy.service import company_currency, company_today

router = APIRouter(prefix="/api/v1", tags=["invoices"])
Ref = Annotated[str | None, Field(default=None, max_length=64)]
Kanal = Annotated[str, Field(pattern="^(phone|email|letter|in_person|other)$")]
BETRAG = 10**13


class InvoiceFields(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    customer: Ref = None
    project: Ref = None
    responsible: Ref = None
    service_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    notes: str | None = Field(default=None, max_length=5000)


class LineIn(Strict):
    description: str = Field(min_length=1, max_length=1000)
    quantity_milli: int = Field(ge=-10**9, le=10**9, description="Menge in Tausendsteln (1 Stück = 1000)")
    unit: str | None = Field(default=None, max_length=20)
    unit_price_minor: int = Field(ge=-BETRAG, le=BETRAG)
    tax_rate_bp: int = Field(ge=0, le=10_000,
                             description="Steuersatz in Basispunkten, vom Nutzer erfasst (1900 = 19 %)")


class LinePatch(Strict):
    description: str | None = Field(default=None, min_length=1, max_length=1000)
    quantity_milli: int | None = Field(default=None, ge=-10**9, le=10**9)
    unit: str | None = Field(default=None, max_length=20)
    unit_price_minor: int | None = Field(default=None, ge=-BETRAG, le=BETRAG)
    tax_rate_bp: int | None = Field(default=None, ge=0, le=10_000)


class IssueIn(Strict):
    due_date: date | None = None


class DispatchIn(Strict):
    action: str = Field(pattern="^(sent|printed)$")
    channel: Kanal | None = None
    note: str = Field(default="", max_length=500)


class PaymentIn(Strict):
    amount_minor: int = Field(gt=0, le=BETRAG)
    paid_on: date
    method: str = Field(default="bank_transfer", pattern="^(bank_transfer|cash|card|direct_debit|other)$")
    reference: str | None = Field(default=None, max_length=200)


class FollowupIn(Strict):
    kind: str = Field(pattern="^(contact_attempt|reminder_noted|dunning_level|note)$")
    channel: Kanal | None = None
    note: str = Field(default="", max_length=5000)
    dunning_level: int | None = Field(default=None, ge=0, le=9)
    next_follow_up: date | None = None


def line_out(z: InvoiceLine) -> dict[str, Any]:
    return {"id": z.public_id, "position": z.position, "description": z.description,
            "quantity_milli": z.quantity_milli, "unit": z.unit, "unit_price_minor": z.unit_price_minor,
            "tax_rate_bp": z.tax_rate_bp, "net_minor": z.net_minor, "tax_minor": z.tax_minor}


def _sichtbar(s: TenantSession, p: Principal, oid: uuid.UUID | None) -> dict[str, Any] | None:
    return object_ref(objects.by_id(s, oid)) if oid and can_see(s, p, oid) else None


def invoice_out(s: TenantSession, p: Principal, inv: Invoice, o: ObjectRow, *, offen: int | None = None,
                detail: bool = False) -> dict[str, Any]:
    refs = refs_for(s, {inv.responsible_membership_id})
    bezahlt = invoices.paid(s, inv.id)
    heute = company_today(s)
    rest = (inv.gross_minor - bezahlt) if inv.kind == "invoice" and inv.status not in ("draft", "cancelled") else 0
    rest = offen if offen is not None else rest
    ueberfaellig = (inv.kind == "invoice" and inv.status in ("issued", "sent", "partially_paid") and rest > 0
                    and inv.due_date is not None and inv.due_date < heute)
    aus = {**object_out(s, o), "kind": inv.kind, "status": inv.status, "number": inv.number,
           "customer": _sichtbar(s, p, inv.customer_id), "project": _sichtbar(s, p, inv.project_id),
           "issue_date": inv.issue_date, "service_date": inv.service_date, "due_date": inv.due_date,
           "currency": inv.currency, "net_minor": inv.net_minor, "tax_minor": inv.tax_minor,
           "gross_minor": inv.gross_minor, "paid_minor": bezahlt, "open_minor": rest, "overdue": ueberfaellig,
           "days_overdue": invoices.days_overdue(inv, heute) if ueberfaellig else 0,
           "dunning_level": inv.dunning_level, "next_follow_up": inv.next_follow_up,
           "responsible": refs.get(inv.responsible_membership_id) if inv.responsible_membership_id else None,
           "sent_at": inv.sent_at, "cancelled_at": inv.cancelled_at}
    if detail:
        summe = invoices.totals(s, inv)
        storno = s.scalar(select(Invoice.id).where(Invoice.cancels_invoice_id == inv.id))
        aus |= {"notes": inv.notes, "customer_snapshot": inv.customer_snapshot,
                "lines": [line_out(z) for z in invoices.lines(s, inv.id)],
                "tax_by_rate": [{"tax_rate_bp": k, "net_minor": n, "tax_minor": t}
                                for k, (n, t) in summe.tax_by_rate.items()],
                "cancels": _sichtbar(s, p, inv.cancels_invoice_id), "cancelled_by": _sichtbar(s, p, storno),
                "followups": [_followup_out(s, f) for f in payments.followups(s, inv.id)],
                "dispatches": [{"action": d.action, "channel": d.channel, "note": d.note, "created_at": d.created_at,
                                "by": _wer(s, d.created_by_membership_id)} for d in invoices.dispatches(s, inv.id)]}
        if decide(p, "finance.read"):
            aus["payments"] = [{"id": po.public_id, "paid_on": pay.paid_on, "amount_minor": pay.amount_minor,
                                "method": pay.method, "reference": pay.reference,
                                "reversal": pay.reverses_payment_id is not None} for pay, po in
                               payments.list_payments(s, inv.id)]
    return aus


def _followup_out(s: TenantSession, f: Any) -> dict[str, Any]:
    return {"kind": f.kind, "channel": f.channel, "note": f.note, "dunning_level": f.dunning_level,
            "next_follow_up": f.next_follow_up, "created_at": f.created_at,
            "by": _wer(s, f.created_by_membership_id)}


def _wer(s: TenantSession, mid: uuid.UUID | None) -> dict[str, str] | None:
    return refs_for(s, {mid}).get(mid) if mid else None


@router.get("/invoices")
def list_invoices(p: Principal = Depends(require("invoices.read")), db: TenantDB = Depends(tenant_db),
                  status: Annotated[list[str] | None, Query(max_length=6)] = None,
                  customer: Annotated[str | None, Query(max_length=64)] = None,
                  project: Annotated[str | None, Query(max_length=64)] = None,
                  responsible: Annotated[str | None, Query(max_length=64, description="ID oder 'me'")] = None,
                  overdue: bool = False, open: bool = False, follow_up_due: bool = False,
                  q: Annotated[str | None, Query(max_length=100)] = None, archived: bool = False,
                  sort: Annotated[str, Query(pattern="^(created_at|due_date|issue_date|number)$")] = "created_at",
                  order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
                  cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    if status and not set(status) <= set(INVOICE_STATUS):
        raise ValidationFailed(f"status muss aus {list(INVOICE_STATUS)} sein")
    with db() as s:
        heute = company_today(s)
        wer = p.membership_id if responsible == "me" else (
            objects.member(s, responsible, active_only=False).id if responsible else None)
        f = invoices.InvoiceFilter(
            status=tuple(status or ()), q=q, archived=archived, open_only=open,
            customer_id=objects.resolve(s, p, customer, type_="customer").id if customer else None,
            project_id=objects.resolve(s, p, project, type_="project").id if project else None,
            responsible_membership_id=wer, overdue_on=heute if overdue else None,
            follow_up_before=heute if follow_up_due else None)
        rows, weiter = invoices.list_invoices(s, visible_clause(p), f, sort=sort, desc=order == "desc",
                                              cursor=cursor, limit=limit)
        return {"items": [invoice_out(s, p, inv, o, offen=rest) for inv, o, rest, *_ in rows], "next_cursor": weiter}


@router.post("/invoices", status_code=201)
def create_invoice(body: InvoiceFields, p: Principal = Depends(require("invoices.create")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        inv, o = invoices.create_draft(s, p, werte=body.model_dump(exclude_none=True), currency=company_currency(s))
        return invoice_out(s, p, inv, o, detail=True)


@router.get("/invoices/{ref}")
def get_invoice(ref: str, p: Principal = Depends(require("invoices.read")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        inv, o = invoices.get(s, p, ref)
        return invoice_out(s, p, inv, o, detail=True)


@router.patch("/invoices/{ref}")
def update_invoice(ref: str, body: InvoiceFields, p: Principal = Depends(require("invoices.update")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes or ("title" in changes and changes["title"] is None) or changes.get("currency", "X") is None:
        raise ValidationFailed("Keine gültige Änderung angegeben")
    with writing(db) as s:
        inv, o = invoices.update(s, p, ref, changes)
        return invoice_out(s, p, inv, o, detail=True)


@router.post("/invoices/{ref}/lines", status_code=201)
def add_line(ref: str, body: LineIn, p: Principal = Depends(require("invoices.update")),
             db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return line_out(invoices.add_line(s, p, ref, body.model_dump()))


@router.patch("/invoices/{ref}/lines/{line}")
def update_line(ref: str, line: str, body: LinePatch, p: Principal = Depends(require("invoices.update")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "unit"}
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    with writing(db) as s:
        return line_out(invoices.update_line(s, p, ref, line, changes))


@router.delete("/invoices/{ref}/lines/{line}", status_code=204)
def delete_line(ref: str, line: str, p: Principal = Depends(require("invoices.update")),
                db: TenantDB = Depends(tenant_db)) -> Response:
    with writing(db) as s:
        invoices.delete_line(s, p, ref, line)
    return Response(status_code=204)


@router.post("/invoices/{ref}/issue")
def issue_invoice(ref: str, body: IssueIn, p: Principal = Depends(require("invoices.approve")),
                  db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Ausstellen: Nummer vergeben, Kunde/Beträge/Positionen einfrieren. Danach nur noch Storno."""
    with writing(db) as s:
        inv, o = invoices.issue(s, p, ref, today=company_today(s), due_date=body.due_date)
        return invoice_out(s, p, inv, o, detail=True)


@router.post("/invoices/{ref}/dispatches", status_code=201)
def add_dispatch(ref: str, body: DispatchIn, p: Principal = Depends(require("invoices.update")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Versand/Druck VERMERKEN (HQ verschickt nichts selbst). Erster Versandvermerk setzt „versendet"."""
    with writing(db) as s:
        invoices.dispatch(s, p, ref, action=body.action, channel=body.channel, note=body.note)
        inv, o = invoices.get(s, p, ref)
        return invoice_out(s, p, inv, o, detail=True)


@router.post("/invoices/{ref}/cancel")
def cancel_invoice(ref: str, p: Principal = Depends(require("invoices.approve")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Stornorechnung erzeugen und ausstellen; gibt die Stornorechnung zurück."""
    with writing(db) as s:
        inv, o = invoices.cancel(s, p, ref, today=company_today(s))
        return invoice_out(s, p, inv, o, detail=True)


@router.post("/invoices/{ref}/payments", status_code=201)
def record_payment(ref: str, body: PaymentIn, p: Principal = Depends(require("finance.create")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        payments.record(s, p, ref, amount_minor=body.amount_minor, paid_on=body.paid_on, method=body.method,
                        reference=body.reference, today=company_today(s))
        inv, o = invoices.get(s, p, ref)
        return invoice_out(s, p, inv, o, detail=True)


@router.post("/invoices/{ref}/payments/{payment}/reverse", status_code=201)
def reverse_payment(ref: str, payment: str, p: Principal = Depends(require("finance.update")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Falsch erfasste Zahlung per Gegenbuchung aufheben — beide Buchungen bleiben sichtbar."""
    with writing(db) as s:
        payments.reverse(s, p, ref, payment, today=company_today(s))
        inv, o = invoices.get(s, p, ref)
        return invoice_out(s, p, inv, o, detail=True)


@router.post("/invoices/{ref}/followups", status_code=201)
def add_followup(ref: str, body: FollowupIn, p: Principal = Depends(require("invoices.update")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Kontaktversuch, Erinnerung, Mahnstufe oder Notiz dokumentieren; Wiedervorlage setzen. Versendet nichts."""
    with writing(db) as s:
        payments.add_followup(s, p, ref, body.model_dump(exclude_unset=True) | {"kind": body.kind})
        inv, o = invoices.get(s, p, ref)
        return invoice_out(s, p, inv, o, detail=True)
