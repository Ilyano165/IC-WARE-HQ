"""Ausgaben mit Beleg (ADR-020): erfassen, Beleg anhängen, Zahlungsstatus, fehlende Belege, Stornieren."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, object_out, object_ref, refs_for, writing
from ichq.authz.service import Principal
from ichq.core.errors import ValidationFailed
from ichq.db.session import TenantSession
from ichq.finance import receipts
from ichq.finance.models_receipts import Receipt
from ichq.objects import service as objects
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import can_see, visible_clause
from ichq.tenancy.service import company_currency, company_today

router = APIRouter(prefix="/api/v1", tags=["receipts"])
Ref = Annotated[str | None, Field(default=None, max_length=64)]
BETRAG = 10**13


class ReceiptFields(Strict):
    expense_date: date | None = None
    supplier_name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=5000)
    amount_minor: int | None = Field(default=None, gt=0, le=BETRAG, description="Bruttobetrag laut Beleg in Cent")
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    tax_rate_bp: int | None = Field(default=None, ge=0, le=10_000, description="vom Nutzer erfasst, optional")
    project: Ref = None
    responsible: Ref = None
    payment_status: str | None = Field(default=None, pattern="^(unpaid|paid)$")
    paid_on: date | None = None
    due_date: date | None = None
    missing_reason: str | None = Field(default=None, max_length=500)
    follow_up_on: date | None = None


class ReceiptIn(ReceiptFields):
    title: str = Field(min_length=1, max_length=300)
    amount_minor: int = Field(gt=0, le=BETRAG)
    document: Ref = None


class ReceiptPatch(ReceiptFields):
    title: str | None = Field(default=None, min_length=1, max_length=300)


class DocumentIn(Strict):
    document: str | None = Field(default=None, max_length=64, description="öffentliche ID des Dokuments; null = lösen")


class VoidIn(Strict):
    reason: str = Field(min_length=3, max_length=500)


def receipt_out(s: TenantSession, p: Principal, r: Receipt, o: ObjectRow, beleg: str | None = None) -> dict[str, Any]:
    refs = refs_for(s, {r.responsible_membership_id})

    def sicht(oid: uuid.UUID | None) -> dict[str, Any] | None:
        return object_ref(objects.by_id(s, oid)) if oid and can_see(s, p, oid) else None
    return {**object_out(s, o), "expense_date": r.expense_date, "supplier_name": r.supplier_name,
            "category": r.category, "description": r.description, "amount_minor": r.amount_minor,
            "currency": r.currency, "tax_rate_bp": r.tax_rate_bp, "project": sicht(r.project_id),
            "responsible": refs.get(r.responsible_membership_id) if r.responsible_membership_id else None,
            "payment_status": r.payment_status, "paid_on": r.paid_on, "due_date": r.due_date,
            "document": sicht(r.document_id), "has_document": r.document_id is not None,
            "evidence": beleg or receipts.evidence(s, r), "missing_reason": r.missing_reason,
            "follow_up_on": r.follow_up_on, "voided_at": r.voided_at, "void_reason": r.void_reason}


@router.get("/receipts")
def list_receipts(p: Principal = Depends(require("finance.read")), db: TenantDB = Depends(tenant_db),
                  evidence: Annotated[list[str] | None, Query(max_length=4)] = None,
                  payment_status: Annotated[list[str] | None, Query(max_length=2)] = None,
                  project: Annotated[str | None, Query(max_length=64)] = None,
                  responsible: Annotated[str | None, Query(max_length=64, description="ID oder 'me'")] = None,
                  date_from: date | None = None, date_to: date | None = None, follow_up_due: bool = False,
                  voided: bool = False, q: Annotated[str | None, Query(max_length=100)] = None,
                  sort: Annotated[str, Query(pattern="^(expense_date|created_at|amount)$")] = "expense_date",
                  order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
                  cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    if evidence and not set(evidence) <= set(receipts.EVIDENCE):
        raise ValidationFailed(f"evidence muss aus {list(receipts.EVIDENCE)} sein")
    if payment_status and not set(payment_status) <= {"unpaid", "paid"}:
        raise ValidationFailed("payment_status muss unpaid oder paid sein")
    with db() as s:
        wer = p.membership_id if responsible == "me" else (
            objects.member(s, responsible, active_only=False).id if responsible else None)
        f = receipts.ReceiptFilter(
            evidence=tuple(evidence or ()), payment_status=tuple(payment_status or ()),
            project_id=objects.resolve(s, p, project, type_="project").id if project else None,
            responsible_membership_id=wer, date_from=date_from, date_to=date_to, voided=voided, q=q,
            follow_up_before=company_today(s) if follow_up_due else None)
        rows, weiter = receipts.list_receipts(s, visible_clause(p), f, sort=sort, desc=order == "desc",
                                              cursor=cursor, limit=limit)
        return {"items": [receipt_out(s, p, r, o, b) for r, o, b, *_ in rows], "next_cursor": weiter}


@router.post("/receipts", status_code=201)
def create_receipt(body: ReceiptIn, p: Principal = Depends(require("finance.create")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        r, o = receipts.create(s, p, title=body.title, werte=body.model_dump(exclude={"title"}, exclude_none=True),
                               currency=company_currency(s), today=company_today(s))
        return receipt_out(s, p, r, o)


@router.get("/receipts/{ref}")
def get_receipt(ref: str, p: Principal = Depends(require("finance.read")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        r, o = receipts.get(s, p, ref)
        return receipt_out(s, p, r, o)


@router.patch("/receipts/{ref}")
def update_receipt(ref: str, body: ReceiptPatch, p: Principal = Depends(require("finance.update")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    for pflicht in ("title", "amount_minor", "expense_date", "currency", "payment_status"):
        if pflicht in changes and changes[pflicht] is None:
            raise ValidationFailed(f"{pflicht} darf nicht leer sein")
    with writing(db) as s:
        r, o = receipts.update(s, p, ref, changes, company_today(s))
        return receipt_out(s, p, r, o)


@router.put("/receipts/{ref}/document")
def set_document(ref: str, body: DocumentIn, p: Principal = Depends(require("finance.update")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Belegdokument verknüpfen (oder mit ``null`` lösen). Zählt erst nach bestandener Virenprüfung als vorhanden."""
    with writing(db) as s:
        r, o = receipts.set_document(s, p, ref, body.document)
        return receipt_out(s, p, r, o)


@router.post("/receipts/{ref}/void")
def void_receipt(ref: str, body: VoidIn, p: Principal = Depends(require("finance.update")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Fehlerfassung stornieren — bleibt mit Grund sichtbar, zählt nirgends mehr mit, ist danach unveränderlich."""
    with writing(db) as s:
        r, o = receipts.void(s, p, ref, body.reason)
        return receipt_out(s, p, r, o)
