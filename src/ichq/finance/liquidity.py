"""Liquiditätsübersicht — jede Zahl mit Herkunft, drei Arten streng getrennt:

1. **manuell** — zuletzt erfasster Kontostand je Konto (Datum + Erfasser). Kein Live-Kontostand.
2. **erfasst** — seit dem (ältesten) Stand in HQ erfasste Zahlungseingänge und bezahlte Ausgaben.
3. **erwartet** — offene Forderungen (nach Fälligkeit), unbezahlte Ausgaben, offene Planposten.

„Geschätzt heute" = manuell + erfasst; die Zeitleiste addiert die Erwartungen je Woche/Monat. Haben die Konten
unterschiedliche Stichtage, ist die Schätzung unscharf — das wird ausgewiesen, nicht versteckt. Gerechnet wird nur in
einer Währung (Standard: Firmenwährung); Posten anderer Währungen werden gezählt, aber nicht umgerechnet.
Sichtbarkeit: Rechnungen, Zahlungen und Ausgaben zählen nur, wenn der Aufrufer sie sehen darf (wie die Listen).
"""
from __future__ import annotations

import secrets
import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, not_, select
from sqlalchemy.orm import Session

from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import NotFound, ValidationFailed
from ichq.core.ids import uuid7
from ichq.finance.invoices import OFFEN
from ichq.finance.models_invoices import INVOICE_OPEN, Invoice, Payment
from ichq.finance.models_liquidity import LiquidityAccount, LiquidityBalance, LiquidityForecast
from ichq.finance.models_receipts import Receipt
from ichq.objects.models import ObjectRow

MAX_POSTEN = 50


# ---- Konten, Stände, Planposten -----------------------------------------------------------------------------------
def accounts(session: Session, *, archived: bool = False) -> list[LiquidityAccount]:
    stmt = select(LiquidityAccount).order_by(LiquidityAccount.name)
    stmt = stmt.where(LiquidityAccount.archived_at.is_not(None) if archived else LiquidityAccount.archived_at.is_(None))
    return list(session.scalars(stmt))


def account(session: Session, ref: str) -> LiquidityAccount:
    a = session.scalars(select(LiquidityAccount).where(LiquidityAccount.public_id == ref)).one_or_none()
    if a is None:
        raise NotFound()
    return a


def create_account(session: Session, p: Principal, *, name: str, kind: str, currency: str) -> LiquidityAccount:
    a = LiquidityAccount(id=uuid7(), tenant_id=p.tenant_id, public_id=secrets.token_hex(16),
                         name=" ".join(name.split())[:100], kind=kind, currency=currency)
    session.add(a)
    session.flush()
    audit(session, "liquidity.account_created", actor_membership_id=p.membership_id, target_type="liquidity_account",
          target_id=a.public_id)
    return a


def update_account(session: Session, p: Principal, ref: str, changes: dict[str, Any]) -> LiquidityAccount:
    a = account(session, ref)
    if "name" in changes:
        a.name = " ".join(changes["name"].split())[:100]
    if "archived" in changes:
        a.archived_at = session.scalar(select(func.now())) if changes["archived"] else None
    session.flush()
    audit(session, "liquidity.account_updated", actor_membership_id=p.membership_id, target_type="liquidity_account",
          target_id=a.public_id, data={"fields": sorted(changes)})
    return a


def add_balance(session: Session, p: Principal, ref: str, *, as_of: date, balance_minor: int, note: str,
                today: date) -> LiquidityBalance:
    a = account(session, ref)
    if as_of > today:
        raise ValidationFailed("as_of darf nicht in der Zukunft liegen")
    b = LiquidityBalance(id=uuid7(), tenant_id=a.tenant_id, account_id=a.id, as_of=as_of,
                         balance_minor=balance_minor, note=" ".join(note.split())[:300],
                         created_by_membership_id=p.membership_id)
    session.add(b)
    session.flush()
    audit(session, "liquidity.balance_recorded", actor_membership_id=p.membership_id, target_type="liquidity_account",
          target_id=a.public_id, data={"as_of": as_of.isoformat()})
    return b


def balances(session: Session, account_id: uuid.UUID, limit: int = 50) -> list[LiquidityBalance]:
    return list(session.scalars(select(LiquidityBalance).where(LiquidityBalance.account_id == account_id)
                                .order_by(LiquidityBalance.as_of.desc(), LiquidityBalance.created_at.desc())
                                .limit(limit)))


def latest_balance(session: Session, account_id: uuid.UUID, stichtag: date) -> LiquidityBalance | None:
    return session.scalars(select(LiquidityBalance).where(LiquidityBalance.account_id == account_id,
                                                          LiquidityBalance.as_of <= stichtag)
                           .order_by(LiquidityBalance.as_of.desc(), LiquidityBalance.created_at.desc())
                           .limit(1)).one_or_none()


def forecasts(session: Session, *, status: tuple[str, ...] = ("open",)) -> list[LiquidityForecast]:
    return list(session.scalars(select(LiquidityForecast).where(LiquidityForecast.status.in_(status))
                                .order_by(LiquidityForecast.expected_on)))


def create_forecast(session: Session, p: Principal, w: dict[str, Any], currency: str) -> LiquidityForecast:
    f = LiquidityForecast(id=uuid7(), tenant_id=p.tenant_id, public_id=secrets.token_hex(16),
                          expected_on=w["expected_on"], amount_minor=w["amount_minor"],
                          currency=w.get("currency") or currency, label=" ".join(w["label"].split())[:200],
                          category=(w.get("category") or None), created_by_membership_id=p.membership_id)
    session.add(f)
    session.flush()
    audit(session, "liquidity.forecast_created", actor_membership_id=p.membership_id, target_type="liquidity_forecast",
          target_id=f.public_id)
    return f


def update_forecast(session: Session, p: Principal, ref: str, changes: dict[str, Any]) -> LiquidityForecast:
    f = session.scalars(select(LiquidityForecast).where(LiquidityForecast.public_id == ref)).one_or_none()
    if f is None:
        raise NotFound()
    for k in ("expected_on", "amount_minor", "status", "category"):
        if k in changes:
            setattr(f, k, changes[k])
    if "label" in changes:
        f.label = " ".join(changes["label"].split())[:200]
    session.flush()
    audit(session, "liquidity.forecast_updated", actor_membership_id=p.membership_id, target_type="liquidity_forecast",
          target_id=f.public_id, data={"fields": sorted(changes)})
    return f


# ---- Übersicht ----------------------------------------------------------------------------------------------------
def _posten(art: str, ref: str, titel: str, datum: date, betrag: int, **extra: Any) -> dict[str, Any]:
    return {"type": art, "id": ref, "title": titel, "date": datum, "amount_minor": betrag, **extra}


def _summe(posten: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total_minor": sum(x["amount_minor"] for x in posten), "count": len(posten), "items": posten[:MAX_POSTEN]}


def overview(session: Session, visible: Any, *, today: date, horizon_days: int, bucket: str,
             currency: str) -> dict[str, Any]:
    if bucket not in ("week", "month"):
        raise ValidationFailed("bucket muss week oder month sein")
    ende = today + timedelta(days=horizon_days)
    # 1. manuell
    konten: list[dict[str, Any]] = []
    ohne_stand: list[dict[str, str]] = []
    for a in accounts(session):
        if a.currency != currency:
            continue
        b = latest_balance(session, a.id, today)
        if b is None:
            ohne_stand.append({"id": a.public_id, "name": a.name})
        else:
            konten.append({"id": a.public_id, "name": a.name, "as_of": b.as_of, "balance_minor": b.balance_minor,
                           "days_old": (today - b.as_of).days})
    seit: date | None = min((k["as_of"] for k in konten), default=None)
    manuell = {"total_minor": sum(k["balance_minor"] for k in konten), "accounts": konten,
               "accounts_without_balance": ohne_stand, "oldest_as_of": seit,
               "dates_differ": len({k["as_of"] for k in konten}) > 1}
    # 2. erfasst seit dem ältesten Stand (bis heute)
    ein: list[dict[str, Any]] = []
    aus: list[dict[str, Any]] = []
    if seit is not None:
        for pay, o in session.execute(select(Payment, ObjectRow).join(ObjectRow, ObjectRow.id == Payment.id).where(
                visible, Payment.currency == currency, Payment.paid_on > seit, Payment.paid_on <= today)
                .order_by(Payment.paid_on)).all():
            ein.append(_posten("payment", o.public_id, o.title, pay.paid_on, pay.amount_minor))
        for r, o in session.execute(select(Receipt, ObjectRow).join(ObjectRow, ObjectRow.id == Receipt.id).where(
                visible, Receipt.voided_at.is_(None), Receipt.payment_status == "paid", Receipt.currency == currency,
                Receipt.paid_on > seit, Receipt.paid_on <= today).order_by(Receipt.paid_on)).all():
            assert r.paid_on is not None
            aus.append(_posten("receipt", o.public_id, o.title, r.paid_on, -r.amount_minor))
    erfasst = {"since": seit, "inflows": _summe(ein), "outflows": _summe(aus)}
    heute_geschaetzt = manuell["total_minor"] + sum(x["amount_minor"] for x in ein + aus)
    # 3. erwartet bis zum Horizont; Überfälliges zählt ab heute (markiert)
    ford: list[dict[str, Any]] = []
    for inv, o, rest in session.execute(select(Invoice, ObjectRow, OFFEN).join(ObjectRow, ObjectRow.id == Invoice.id)
                                        .where(visible, Invoice.kind == "invoice", Invoice.status.in_(INVOICE_OPEN),
                                               OFFEN > 0, Invoice.currency == currency, Invoice.due_date <= ende)
                                        .order_by(Invoice.due_date)).all():
        assert inv.due_date is not None
        ford.append(_posten("invoice", o.public_id, o.title, max(inv.due_date, today), int(rest),
                            due_date=inv.due_date, overdue=inv.due_date < today))
    verb: list[dict[str, Any]] = []
    for r, o in session.execute(select(Receipt, ObjectRow).join(ObjectRow, ObjectRow.id == Receipt.id).where(
            visible, Receipt.voided_at.is_(None), Receipt.payment_status == "unpaid", Receipt.currency == currency,
            func.coalesce(Receipt.due_date, Receipt.expense_date) <= ende)).all():
        faellig = r.due_date or r.expense_date
        verb.append(_posten("receipt", o.public_id, o.title, max(faellig, today), -r.amount_minor,
                            due_date=faellig, overdue=faellig < today))
    plan = [_posten("forecast", f.public_id, f.label, max(f.expected_on, today), f.amount_minor,
                    due_date=f.expected_on, overdue=f.expected_on < today)
            for f in forecasts(session) if f.currency == currency and f.expected_on <= ende]
    erwartet = {"receivables": _summe(ford), "payables": _summe(verb), "forecasts": _summe(plan)}
    return {"currency": currency, "today": today, "horizon_end": ende, "manual": manuell, "recorded": erfasst,
            "estimated_today_minor": heute_geschaetzt, "expected": erwartet,
            "timeline": _zeitleiste(today, ende, bucket, heute_geschaetzt, ford + verb + plan),
            "other_currencies": _andere(session, visible, currency),
            "hidden_items": _verborgen(session, visible, seit, today)}


def _grenzen(today: date, ende: date, bucket: str) -> list[tuple[date, date]]:
    teile, start = [], today
    while start <= ende:
        if bucket == "week":
            bis = start + timedelta(days=6 - start.weekday())
        else:
            naechster = (start.replace(day=1) + timedelta(days=32)).replace(day=1)
            bis = naechster - timedelta(days=1)
        bis = min(bis, ende)
        teile.append((start, bis))
        start = bis + timedelta(days=1)
    return teile


def _zeitleiste(today: date, ende: date, bucket: str, start: int, posten: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stand, zeilen = start, []
    for von, bis in _grenzen(today, ende, bucket):
        drin = [x for x in posten if von <= x["date"] <= bis]
        rein = sum(x["amount_minor"] for x in drin if x["amount_minor"] > 0)
        raus = sum(x["amount_minor"] for x in drin if x["amount_minor"] < 0)
        stand += rein + raus
        zeilen.append({"from": von, "to": bis, "inflow_minor": rein, "outflow_minor": raus, "balance_minor": stand})
    return zeilen


def _verborgen(session: Session, visible: Any, seit: date | None, today: date) -> int:
    """Offene Posten, die der Aufrufer nicht sehen darf — dann ist seine Übersicht unvollständig (wird angezeigt)."""
    n = session.scalar(select(func.count()).select_from(Invoice).join(ObjectRow, ObjectRow.id == Invoice.id).where(
        not_(visible), Invoice.kind == "invoice", Invoice.status.in_(INVOICE_OPEN))) or 0
    n += session.scalar(select(func.count()).select_from(Receipt).join(ObjectRow, ObjectRow.id == Receipt.id).where(
        not_(visible), Receipt.voided_at.is_(None), Receipt.payment_status == "unpaid")) or 0
    if seit is not None:
        n += session.scalar(select(func.count()).select_from(Receipt).join(ObjectRow, ObjectRow.id == Receipt.id)
                            .where(not_(visible), Receipt.voided_at.is_(None), Receipt.paid_on > seit,
                                   Receipt.paid_on <= today)) or 0
        n += session.scalar(select(func.count()).select_from(Payment).join(ObjectRow, ObjectRow.id == Payment.id)
                            .where(not_(visible), Payment.paid_on > seit, Payment.paid_on <= today)) or 0
    return int(n)


def _andere(session: Session, visible: Any, currency: str) -> list[dict[str, Any]]:
    """Offene Posten in anderen Währungen: nur gezählt — HQ rechnet ohne Kurs nicht um."""
    rows = session.execute(select(Invoice.currency, func.count()).join(ObjectRow, ObjectRow.id == Invoice.id).where(
        visible, Invoice.kind == "invoice", Invoice.status.in_(INVOICE_OPEN), Invoice.currency != currency)
        .group_by(Invoice.currency)).all()
    rows2 = session.execute(select(Receipt.currency, func.count()).join(ObjectRow, ObjectRow.id == Receipt.id).where(
        visible, Receipt.voided_at.is_(None), Receipt.payment_status == "unpaid", Receipt.currency != currency)
        .group_by(Receipt.currency)).all()
    rows3 = session.execute(select(LiquidityForecast.currency, func.count()).where(
        LiquidityForecast.status == "open", LiquidityForecast.currency != currency)
        .group_by(LiquidityForecast.currency)).all()
    zusammen: dict[str, int] = {}
    for w, n in [*rows, *rows2, *rows3]:
        zusammen[w] = zusammen.get(w, 0) + int(n)
    return [{"currency": w, "open_items": n} for w, n in sorted(zusammen.items())]
