"""Liquidität (ADR-020 Nr. 9): manuelle Kontostände, Planposten, Übersicht mit Herkunft jeder Zahl.
Keine Bankanbindung — die Übersicht nennt Stichtage und Erfasser, nie einen „Live-Kontostand"."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import Strict, refs_for, writing
from ichq.authz.service import Principal
from ichq.core.errors import ValidationFailed
from ichq.db.session import TenantSession
from ichq.finance import liquidity
from ichq.finance.models_liquidity import LiquidityAccount, LiquidityBalance, LiquidityForecast
from ichq.objects.visibility import visible_clause
from ichq.tenancy.service import company_currency, company_today

router = APIRouter(prefix="/api/v1", tags=["liquidity"])
BETRAG = 10**13
Waehrung = Annotated[str | None, Field(default=None, pattern="^[A-Z]{3}$")]


class AccountIn(Strict):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(default="bank", pattern="^(bank|cash|other)$")
    currency: Waehrung = None


class AccountPatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    archived: bool | None = None


class BalanceIn(Strict):
    as_of: date
    balance_minor: int = Field(ge=-BETRAG, le=BETRAG, description="Kontostand laut Auszug in Cent (negativ = Soll)")
    note: str = Field(default="", max_length=300)


class ForecastIn(Strict):
    expected_on: date
    amount_minor: int = Field(ge=-BETRAG, le=BETRAG, description="+ Einzahlung, − Auszahlung (Cent), nicht 0")
    label: str = Field(min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=60)
    currency: Waehrung = None


class ForecastPatch(Strict):
    expected_on: date | None = None
    amount_minor: int | None = Field(default=None, ge=-BETRAG, le=BETRAG)
    label: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, pattern="^(open|done|cancelled)$")


def balance_out(b: LiquidityBalance, refs: dict[Any, Any]) -> dict[str, Any]:
    return {"as_of": b.as_of, "balance_minor": b.balance_minor, "note": b.note, "recorded_at": b.created_at,
            "recorded_by": refs.get(b.created_by_membership_id), "source": "manual"}


def account_out(s: TenantSession, a: LiquidityAccount, history: bool = False) -> dict[str, Any]:
    staende = liquidity.balances(s, a.id, 50 if history else 1)
    refs = refs_for(s, {b.created_by_membership_id for b in staende})
    out: dict[str, Any] = {"id": a.public_id, "name": a.name, "kind": a.kind, "currency": a.currency,
                           "archived": a.archived_at is not None,
                           "latest_balance": balance_out(staende[0], refs) if staende else None}
    if history:
        out["balances"] = [balance_out(b, refs) for b in staende]
    return out


def forecast_out(f: LiquidityForecast) -> dict[str, Any]:
    return {"id": f.public_id, "expected_on": f.expected_on, "amount_minor": f.amount_minor, "currency": f.currency,
            "label": f.label, "category": f.category, "status": f.status, "source": "forecast"}


@router.get("/liquidity")
def overview(p: Principal = Depends(require("finance.read")), db: TenantDB = Depends(tenant_db),
             horizon_days: Annotated[int, Query(ge=7, le=366)] = 90,
             bucket: Annotated[str, Query(pattern="^(week|month)$")] = "week",
             currency: Annotated[str | None, Query(pattern="^[A-Z]{3}$")] = None) -> dict[str, Any]:
    """Manuelle Stände + seither erfasste Bewegungen = geschätzter Stand; dazu erwartete Ein-/Auszahlungen."""
    with db() as s:
        return liquidity.overview(s, visible_clause(p), today=company_today(s), horizon_days=horizon_days,
                                  bucket=bucket, currency=currency or company_currency(s))


@router.get("/liquidity/accounts")
def list_accounts(p: Principal = Depends(require("finance.read")), db: TenantDB = Depends(tenant_db),
                  archived: bool = False) -> dict[str, Any]:
    with db() as s:
        return {"items": [account_out(s, a) for a in liquidity.accounts(s, archived=archived)]}


@router.post("/liquidity/accounts", status_code=201)
def create_account(body: AccountIn, p: Principal = Depends(require("finance.update")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        a = liquidity.create_account(s, p, name=body.name, kind=body.kind,
                                     currency=body.currency or company_currency(s))
        return account_out(s, a)


@router.get("/liquidity/accounts/{account}")
def get_account(account: str, p: Principal = Depends(require("finance.read")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        return account_out(s, liquidity.account(s, account), history=True)


@router.patch("/liquidity/accounts/{account}")
def update_account(account: str, body: AccountPatch, p: Principal = Depends(require("finance.update")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    with writing(db) as s:
        return account_out(s, liquidity.update_account(s, p, account, changes), history=True)


@router.post("/liquidity/accounts/{account}/balances", status_code=201)
def add_balance(account: str, body: BalanceIn, p: Principal = Depends(require("finance.update")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Kontostand laut Auszug erfassen. Nur anhängend: ein falscher Stand wird durch einen neuen ersetzt."""
    with writing(db) as s:
        a = liquidity.account(s, account)
        liquidity.add_balance(s, p, account, as_of=body.as_of, balance_minor=body.balance_minor, note=body.note,
                              today=company_today(s))
        return account_out(s, a, history=True)


@router.get("/liquidity/forecasts")
def list_forecasts(p: Principal = Depends(require("finance.read")), db: TenantDB = Depends(tenant_db),
                   status: Annotated[list[str] | None, Query(max_length=3)] = None) -> dict[str, Any]:
    if status and not set(status) <= {"open", "done", "cancelled"}:
        raise ValidationFailed("status muss aus open, done, cancelled sein")
    with db() as s:
        return {"items": [forecast_out(f) for f in liquidity.forecasts(s, status=tuple(status or ("open",)))]}


@router.post("/liquidity/forecasts", status_code=201)
def create_forecast(body: ForecastIn, p: Principal = Depends(require("finance.update")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    if body.amount_minor == 0:
        raise ValidationFailed("amount_minor darf nicht 0 sein")
    with writing(db) as s:
        return forecast_out(liquidity.create_forecast(s, p, body.model_dump(), company_currency(s)))


@router.patch("/liquidity/forecasts/{item}")
def update_forecast(item: str, body: ForecastPatch, p: Principal = Depends(require("finance.update")),
                    db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    for pflicht in ("expected_on", "amount_minor", "label", "status"):
        if pflicht in changes and changes[pflicht] is None:
            raise ValidationFailed(f"{pflicht} darf nicht leer sein")
    if changes.get("amount_minor") == 0:
        raise ValidationFailed("amount_minor darf nicht 0 sein")
    with writing(db) as s:
        return forecast_out(liquidity.update_forecast(s, p, item, changes))
