"""Verträge (ADR-020): Verwaltungsakte mit Laufzeit und Kündigungsfrist. Termine sind Kalenderrechnung aus den
Angaben — keine Rechtsprüfung; Vertragsdokumente hängen als Anhang (``/objects/{ref}/links``, Typ ``attachment``)."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import DEFAULT, Cursor, Limit, Strict, object_out, object_ref, refs_for, writing
from ichq.authz.service import Principal
from ichq.contracts import service as contracts
from ichq.contracts.models import CONTRACT_STATUS, Contract
from ichq.core.errors import ValidationFailed
from ichq.db.session import TenantSession
from ichq.objects import service as objects
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import can_see, visible_clause
from ichq.tenancy.service import company_currency, company_today

router = APIRouter(prefix="/api/v1", tags=["contracts"])
BETRAG = 10**13


class ContractFields(Strict):
    customer: str | None = Field(default=None, max_length=64)
    counterparty_name: str | None = Field(default=None, max_length=200)
    contract_type: str | None = Field(default=None, max_length=60)
    reference: str | None = Field(default=None, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    notice_value: int | None = Field(default=None, ge=0, le=3650)
    notice_unit: str | None = Field(default=None, pattern="^(days|weeks|months)$")
    auto_renew: bool | None = None
    renewal_months: int | None = Field(default=None, ge=1, le=120)
    amount_minor: int | None = Field(default=None, ge=0, le=BETRAG)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    billing: str | None = Field(default=None, pattern="^(none|once|monthly|quarterly|yearly)$")
    status: str | None = Field(default=None, pattern="^(draft|active)$")
    responsible: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=20_000)


class ContractIn(ContractFields):
    title: str = Field(min_length=1, max_length=300)


class ContractPatch(ContractFields):
    title: str | None = Field(default=None, min_length=1, max_length=300)


class TerminateIn(Strict):
    terminated_on: date
    effective_on: date
    note: str = Field(default="", max_length=500)


def contract_out(s: TenantSession, p: Principal, c: Contract, o: ObjectRow, today: date) -> dict[str, Any]:
    t = contracts.termine(c, today)
    refs = refs_for(s, {c.responsible_membership_id})
    kunde = object_ref(objects.by_id(s, c.customer_id)) if c.customer_id and can_see(s, p, c.customer_id) else None
    return {**object_out(s, o), "customer": kunde, "has_customer": c.customer_id is not None,
            "counterparty_name": c.counterparty_name, "contract_type": c.contract_type, "reference": c.reference,
            "start_date": c.start_date, "end_date": c.end_date, "notice_value": c.notice_value,
            "notice_unit": c.notice_unit, "auto_renew": c.auto_renew, "renewal_months": c.renewal_months,
            "amount_minor": c.amount_minor, "currency": c.currency, "billing": c.billing, "status": c.status,
            "terminated_on": c.terminated_on, "termination_effective_on": c.termination_effective_on,
            "termination_note": c.termination_note,
            "responsible": refs.get(c.responsible_membership_id) if c.responsible_membership_id else None,
            "notes": c.notes, "state": t.state, "term_end": t.term_end, "notice_deadline": t.notice_deadline,
            "days_to_notice": (t.notice_deadline - today).days if t.notice_deadline else None,
            "renewals": t.renewals, "computed_from": "Angaben im Vertrag — keine rechtliche Prüfung"}


@router.get("/contracts")
def list_contracts(p: Principal = Depends(require("contracts.read")), db: TenantDB = Depends(tenant_db),
                   status: Annotated[list[str] | None, Query(max_length=3)] = None,
                   customer: Annotated[str | None, Query(max_length=64)] = None,
                   responsible: Annotated[str | None, Query(max_length=64, description="ID oder 'me'")] = None,
                   ending_before: date | None = None, archived: bool = False,
                   q: Annotated[str | None, Query(max_length=100)] = None,
                   sort: Annotated[str, Query(pattern="^(end_date|created_at|title)$")] = "end_date",
                   order: Annotated[str, Query(pattern="^(asc|desc)$")] = "asc",
                   cursor: Cursor = None, limit: Limit = DEFAULT) -> dict[str, Any]:
    if status and not set(status) <= set(CONTRACT_STATUS):
        raise ValidationFailed(f"status muss aus {list(CONTRACT_STATUS)} sein")
    with db() as s:
        wer = p.membership_id if responsible == "me" else (
            objects.member(s, responsible, active_only=False).id if responsible else None)
        f = contracts.ContractFilter(
            status=tuple(status or ()), responsible_membership_id=wer, ending_before=ending_before, archived=archived,
            customer_id=objects.resolve(s, p, customer, type_="customer").id if customer else None, q=q)
        rows, weiter = contracts.list_contracts(s, visible_clause(p), f, sort=sort, desc=order == "desc",
                                                cursor=cursor, limit=limit)
        heute = company_today(s)
        return {"items": [contract_out(s, p, c, o, heute) for c, o, *_ in rows], "next_cursor": weiter}


@router.get("/contracts/notice-due")
def notice_due(p: Principal = Depends(require("contracts.read")), db: TenantDB = Depends(tenant_db),
               days: Annotated[int, Query(ge=0, le=366)] = 60) -> dict[str, Any]:
    """Laufende Verträge, deren Kündigungstermin (aus den Angaben) in höchstens ``days`` Tagen liegt."""
    with db() as s:
        heute = company_today(s)
        treffer, gekappt = contracts.notice_due(s, visible_clause(p), today=heute, days=days)
        return {"items": [contract_out(s, p, c, o, heute) for c, o, _t in treffer], "truncated": gekappt}


@router.post("/contracts", status_code=201)
def create_contract(body: ContractIn, p: Principal = Depends(require("contracts.create")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        c, o = contracts.create(s, p, title=body.title, werte=body.model_dump(exclude={"title"}, exclude_none=True),
                                currency=company_currency(s))
        return contract_out(s, p, c, o, company_today(s))


@router.get("/contracts/{ref}")
def get_contract(ref: str, p: Principal = Depends(require("contracts.read")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        c, o = contracts.get(s, p, ref)
        return contract_out(s, p, c, o, company_today(s))


@router.patch("/contracts/{ref}")
def update_contract(ref: str, body: ContractPatch, p: Principal = Depends(require("contracts.update")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    for pflicht in ("title", "auto_renew", "currency", "billing", "status"):
        if pflicht in changes and changes[pflicht] is None:
            raise ValidationFailed(f"{pflicht} darf nicht leer sein")
    with writing(db) as s:
        c, o = contracts.update(s, p, ref, changes)
        return contract_out(s, p, c, o, company_today(s))


@router.post("/contracts/{ref}/terminate")
def terminate_contract(ref: str, body: TerminateIn, p: Principal = Depends(require("contracts.update")),
                       db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Kündigung erfassen (zugegangen am, wirksam zum). HQ verschickt nichts und prüft die Wirksamkeit nicht."""
    with writing(db) as s:
        heute = company_today(s)
        c, o = contracts.terminate(s, p, ref, terminated_on=body.terminated_on, effective_on=body.effective_on,
                                   note=body.note, today=heute)
        return contract_out(s, p, c, o, heute)
