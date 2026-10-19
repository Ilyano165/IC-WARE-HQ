"""Widgets der Fachmodule (ADR-020) — ersetzen die bisherigen ``PLANNED``-Einträge. Regeln wie in ``loaders``:
Zahl = verlinkte Liste (dieselben ``filter_clauses``), Sichtbarkeit nur über ``visible_clause``, keine Zahl ohne
Datenquelle. Geldbeträge stehen nur als Text in Einträgen (Kennzahlen sind Stückzahlen), immer mit Herkunft.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select

from ichq.authz.service import Principal
from ichq.contracts import service as contracts
from ichq.crm.inquiries import InquiryFilter
from ichq.crm.inquiries import filter_clauses as inquiry_filter
from ichq.crm.models import INQUIRY_OPEN, Inquiry
from ichq.dashboard.loaders import N, _zaehle
from ichq.dashboard.registry import Context, Data, Item, Metric, register
from ichq.finance import closing, liquidity
from ichq.finance.deadlines import DeadlineFilter
from ichq.finance.deadlines import filter_clauses as deadline_filter
from ichq.finance.invoices import OFFEN, InvoiceFilter
from ichq.finance.invoices import filter_clauses as invoice_filter
from ichq.finance.models_deadlines import Deadline
from ichq.finance.models_invoices import Invoice
from ichq.finance.models_receipts import Receipt
from ichq.finance.profitability import profitability
from ichq.finance.receipts import ReceiptFilter
from ichq.finance.receipts import filter_clauses as receipt_filter
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import visible_clause
from ichq.projects.models import Project
from ichq.projects.service import ProjectFilter
from ichq.projects.service import filter_clauses as project_filter
from ichq.tenancy.service import company_currency
from ichq.travel import logbook, travels

LUECKE = ("missing", "unchecked", "rejected")


def geld(minor: int, waehrung: str = "EUR") -> str:
    """1234567 → „12.345,67 EUR“ (ohne Locale-Abhängigkeit des Servers)."""
    vz, betrag = ("-" if minor < 0 else ""), abs(minor)
    euro = f"{betrag // 100:,}".replace(",", ".")
    return f"{vz}{euro},{betrag % 100:02d} {waehrung}"


def _basis(p: Principal, tabelle: Any) -> Any:
    return select(tabelle.id).join(ObjectRow, ObjectRow.id == tabelle.id).where(visible_clause(p))


@register("open_invoices", "Rechnungen", ("invoices.read",))
def open_invoices(s: Any, p: Principal, ctx: Context) -> Data:
    f = {"open": InvoiceFilter(open_only=True), "overdue": InvoiceFilter(overdue_on=ctx.today),
         "drafts": InvoiceFilter(status=("draft",))}
    z = _zaehle(s, _basis(p, Invoice), {k: invoice_filter(v) for k, v in f.items()})
    rows = s.execute(select(Invoice, ObjectRow, OFFEN).join(ObjectRow, ObjectRow.id == Invoice.id)
                     .where(visible_clause(p), *invoice_filter(f["overdue"])).order_by(Invoice.due_date).limit(N)).all()
    return Data("invoices", (
        Metric("open", "Offene Forderungen", z["open"], {"open": True}),
        Metric("overdue", "Überfällig", z["overdue"], {"overdue": True}, "danger" if z["overdue"] else "neutral"),
        Metric("drafts", "Entwürfe", z["drafts"], {"status": ["draft"]})),
        tuple(Item(o.public_id, "invoice", f"{i.number} · {o.title}", detail=f"offen {geld(int(rest), i.currency)}",
                   date=i.due_date.isoformat() if i.due_date else None, tone="danger") for i, o, rest in rows),
        "Keine überfälligen Rechnungen.")


@register("missing_receipts", "Fehlende Belege", ("finance.read",))
def missing_receipts(s: Any, p: Principal, ctx: Context) -> Data:
    f = {"missing": ReceiptFilter(evidence=LUECKE), "follow_up": ReceiptFilter(follow_up_before=ctx.today)}
    z = _zaehle(s, _basis(p, Receipt), {k: receipt_filter(v) for k, v in f.items()})
    rows = s.execute(select(Receipt, ObjectRow).join(ObjectRow, ObjectRow.id == Receipt.id)
                     .where(visible_clause(p), *receipt_filter(f["missing"]))
                     .order_by(Receipt.expense_date.desc()).limit(N)).all()
    return Data("receipts", (
        Metric("missing", "Ohne geprüften Beleg", z["missing"], {"evidence": list(LUECKE)},
               "warn" if z["missing"] else "neutral"),
        Metric("follow_up", "Wiedervorlage fällig", z["follow_up"], {"follow_up_due": True},
               "warn" if z["follow_up"] else "neutral")),
        tuple(Item(o.public_id, "receipt", o.title, detail=geld(r.amount_minor, r.currency),
                   date=r.expense_date.isoformat()) for r, o in rows), "Alle Belege vorhanden und geprüft.")


@register("liquidity", "Liquidität", ("finance.read",))
def liquidity_widget(s: Any, p: Principal, ctx: Context) -> Data:
    w = company_currency(s)
    u = liquidity.overview(s, visible_clause(p), today=ctx.today, horizon_days=30, bucket="week", currency=w)
    m = u["manual"]
    if not m["accounts"]:
        return Data(None, (), (Item(None, None, "Kein Kontostand erfasst", detail="Ohne Stand keine Schätzung.",
                                    list="liquidity"),), "")
    ende = u["timeline"][-1]["balance_minor"] if u["timeline"] else u["estimated_today_minor"]
    hinweis = " · Stichtage unterschiedlich" if m["dates_differ"] else ""
    return Data(None, (), (
        Item(None, None, "Geschätzt heute", detail=f"{geld(u['estimated_today_minor'], w)} (manuell seit "
             f"{m['oldest_as_of']:%d.%m.%Y} + erfasst){hinweis}", list="liquidity",
             tone="danger" if u["estimated_today_minor"] < 0 else "neutral"),
        Item(None, None, "Geschätzt in 30 Tagen", detail=f"{geld(ende, w)} (inkl. offener Posten und Planposten)",
             list="liquidity", tone="danger" if ende < 0 else "neutral")), "")


@register("tax_deadlines", "Fristen", ("finance.read",))
def deadlines_widget(s: Any, p: Principal, ctx: Context) -> Data:
    f = {"overdue": DeadlineFilter(overdue_before=ctx.today), "reminder": DeadlineFilter(remind_by=ctx.today)}
    z = _zaehle(s, _basis(p, Deadline), {k: deadline_filter(v) for k, v in f.items()})
    rows = s.execute(select(Deadline, ObjectRow).join(ObjectRow, ObjectRow.id == Deadline.id)
                     .where(visible_clause(p), *deadline_filter(DeadlineFilter(
                         due_to=ctx.today + timedelta(days=30))))
                     .order_by(Deadline.due_on).limit(N)).all()
    return Data("deadlines", (
        Metric("overdue", "Überfällig", z["overdue"], {"overdue": True}, "danger" if z["overdue"] else "neutral"),
        Metric("reminder", "Erinnerung fällig", z["reminder"], {"reminder_due": True},
               "warn" if z["reminder"] else "neutral")),
        tuple(Item(o.public_id, "deadline", o.title, date=d.due_on.isoformat(),
                   detail="Quelle angegeben" if d.source_reference else "nicht amtlich bestätigt",
                   tone="danger" if d.due_on < ctx.today else "neutral") for d, o in rows),
        "Keine offenen Fristen in den nächsten 30 Tagen.")


@register("month_close", "Monatsabschluss", ("finance.read",), size="s")
def month_close(s: Any, p: Principal, ctx: Context) -> Data:
    vormonat = (ctx.today.replace(day=1) - timedelta(days=1)).replace(day=1)
    zu = closing.active(s, vormonat) is not None
    return Data(None, (), (Item(None, None, f"Vormonat {vormonat:%m/%Y}", detail="abgeschlossen" if zu else "offen",
                                tone="neutral" if zu else "warn", list="periods"),), "")


@register("projects", "Projekte", ("projects.read",))
def projects_widget(s: Any, p: Principal, ctx: Context) -> Data:
    f = {"active": ProjectFilter(status=("active",)), "on_hold": ProjectFilter(status=("on_hold",))}
    z = _zaehle(s, _basis(p, Project), {k: project_filter(v) for k, v in f.items()})
    rows = s.execute(select(Project, ObjectRow).join(ObjectRow, ObjectRow.id == Project.id)
                     .where(visible_clause(p), *project_filter(f["active"]))
                     .order_by(Project.end_date.asc().nulls_last()).limit(N)).all()
    return Data("projects", (Metric("active", "Aktiv", z["active"], {"status": ["active"]}),
                             Metric("on_hold", "Pausiert", z["on_hold"], {"status": ["on_hold"]})),
                tuple(Item(o.public_id, "project", o.title, date=pr.end_date.isoformat() if pr.end_date else None)
                      for pr, o in rows), "Keine aktiven Projekte.")


@register("project_profitability", "Projektprofitabilität", ("projects.read", "finance.read"))
def profitability_widget(s: Any, p: Principal, ctx: Context) -> Data:
    rows = s.execute(select(Project, ObjectRow).join(ObjectRow, ObjectRow.id == Project.id)
                     .where(visible_clause(p), *project_filter(ProjectFilter(status=("active",))))
                     .order_by(ObjectRow.created_at.desc()).limit(N)).all()
    items = []
    for pr, o in rows:
        r = profitability(s, visible_clause(p), pr)
        unvollst = "" if r["complete"] else " · unvollständig"
        items.append(Item(o.public_id, "project", o.title, detail=f"Marge {geld(r['margin_minor'], r['currency'])}"
                          f"{unvollst}", tone="danger" if r["margin_minor"] < 0 else
                          ("warn" if not r["complete"] else "neutral")))
    return Data(None, (), tuple(items), "Keine aktiven Projekte.")


@register("contracts", "Verträge", ("contracts.read",))
def contracts_widget(s: Any, p: Principal, ctx: Context) -> Data:
    treffer, _gekappt = contracts.notice_due(s, visible_clause(p), today=ctx.today, days=60)
    return Data("contracts_notice", (Metric("notice", "Kündigung in 60 Tagen", len(treffer), {"days": 60},
                                            "warn" if treffer else "neutral"),),
                tuple(Item(o.public_id, "contract", o.title, detail="kündbar bis (aus den Angaben)",
                           date=t.notice_deadline.isoformat() if t.notice_deadline else None, tone="warn")
                      for _c, o, t in treffer[:N]), "Keine Kündigungstermine in den nächsten 60 Tagen.")


@register("travel", "Dienstreisen", ("travel.read",))
def travel_widget(s: Any, p: Principal, ctx: Context) -> Data:
    rows = travels.list_travels(s, visible_clause(p), travels.TravelFilter(status=("submitted",)))
    return Data("travels", (Metric("submitted", "Zu entscheiden", len(rows), {"status": ["submitted"]},
                                   "warn" if rows else "neutral"),),
                tuple(Item(o.public_id, "travel", o.title, detail=t.destination, date=t.start_date.isoformat())
                      for t, o in rows[:N]), "Keine offenen Reiseanträge.")


@register("trips", "Fahrtenbuch", ("vehicles.read",))
def trips_widget(s: Any, p: Principal, ctx: Context) -> Data:
    monat = ctx.today.replace(day=1)
    rows = logbook.list_trips(s, visible_clause(p), logbook.TripFilter(date_from=monat))
    luecken = sum(1 for v in logbook.vehicles(s) for g in logbook.km_gaps(s, v.id).values() if g)
    return Data("trips", (Metric("month", "Fahrten diesen Monat", len(rows), {"date_from": monat.isoformat()}),
                          Metric("gaps", "Kilometer-Lücken", luecken, {}, "warn" if luecken else "neutral",
                                 linked=False)), (), "")


@register("crm", "Anfragen", ("customers.read",))
def crm_widget(s: Any, p: Principal, ctx: Context) -> Data:
    f = {"open": InquiryFilter(status=INQUIRY_OPEN), "follow_up": InquiryFilter(follow_up_before=ctx.today)}
    z = _zaehle(s, _basis(p, Inquiry), {k: inquiry_filter(v) for k, v in f.items()})
    return Data("inquiries", (
        Metric("open", "Offen", z["open"], {"status": list(INQUIRY_OPEN)}),
        Metric("follow_up", "Wiedervorlage fällig", z["follow_up"], {"follow_up_before": ctx.today.isoformat()},
               "warn" if z["follow_up"] else "neutral")), (), "")
