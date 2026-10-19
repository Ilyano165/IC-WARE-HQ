"""Projektprofitabilität aus echten Zeilen — mit ausdrücklicher Kennzeichnung, wo die Zahl unvollständig ist.

* Erlös: Netto der ausgestellten Rechnungen und Stornos zum Projekt (Entwürfe zählen nicht).
* Ausgaben: Belege zum Projekt. Netto nur, wenn der Nutzer einen Steuersatz erfasst hat
  (kaufmännisch gerundet aus brutto); sonst wird brutto gezählt und als unvollständig markiert.
* Personalkosten: Projektzeiten × kalkulatorischer Stundensatz des Teammitglieds; Zeiten ohne Satz zählen NICHT und
  werden als fehlende Daten ausgewiesen (Minuten).
* Nur Projektwährung; Posten anderer Währungen und für den Aufrufer unsichtbare Rechnungen/Belege werden gezählt.
Ergebnis ist eine Rechenhilfe, keine Kostenrechnung im betriebswirtschaftlichen Sinn.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, func, not_, select
from sqlalchemy.orm import Session

from ichq.finance.models_invoices import Invoice
from ichq.finance.models_receipts import Receipt
from ichq.finance.rechnen import runde_div
from ichq.objects.models import ObjectRow
from ichq.projects.models import Project, ProjectMember, TimeEntry


def _rechnungen(session: Session, visible: Any, pid: uuid.UUID, waehrung: str) -> tuple[int, int, int]:
    basis = and_(Invoice.project_id == pid, Invoice.status != "draft")
    netto = session.scalar(select(func.coalesce(func.sum(Invoice.net_minor), 0))
                           .join(ObjectRow, ObjectRow.id == Invoice.id)
                           .where(basis, visible, Invoice.currency == waehrung)) or 0
    fremd = session.scalar(select(func.count()).select_from(Invoice).join(ObjectRow, ObjectRow.id == Invoice.id)
                           .where(basis, visible, Invoice.currency != waehrung)) or 0
    verborgen = session.scalar(select(func.count()).select_from(Invoice).join(ObjectRow, ObjectRow.id == Invoice.id)
                               .where(basis, not_(visible))) or 0
    return int(netto), int(fremd), int(verborgen)


def _ausgaben(session: Session, visible: Any, pid: uuid.UUID, waehrung: str) -> dict[str, int]:
    basis = and_(Receipt.project_id == pid, Receipt.voided_at.is_(None))
    netto, ohne_satz, brutto_ohne = 0, 0, 0
    for brutto, satz in session.execute(select(Receipt.amount_minor, Receipt.tax_rate_bp)
                                        .join(ObjectRow, ObjectRow.id == Receipt.id)
                                        .where(basis, visible, Receipt.currency == waehrung)).all():
        if satz is None:
            ohne_satz, brutto_ohne = ohne_satz + 1, brutto_ohne + brutto
        else:
            netto += runde_div(brutto * 10_000, 10_000 + satz)
    fremd = session.scalar(select(func.count()).select_from(Receipt).join(ObjectRow, ObjectRow.id == Receipt.id)
                           .where(basis, visible, Receipt.currency != waehrung)) or 0
    verborgen = session.scalar(select(func.count()).select_from(Receipt).join(ObjectRow, ObjectRow.id == Receipt.id)
                               .where(basis, not_(visible))) or 0
    return {"net_minor": netto + brutto_ohne, "without_tax_rate": ohne_satz, "gross_counted_minor": brutto_ohne,
            "other_currency": int(fremd), "hidden": int(verborgen)}


def _personal(session: Session, pid: uuid.UUID) -> dict[str, int]:
    rows = session.execute(select(TimeEntry.minutes, ProjectMember.hourly_cost_minor)
                           .outerjoin(ProjectMember, and_(ProjectMember.project_id == TimeEntry.project_id,
                                                          ProjectMember.membership_id == TimeEntry.membership_id))
                           .where(TimeEntry.project_id == pid)).all()
    kosten, ohne = 0, 0
    for minuten, satz in rows:
        if satz is None:
            ohne += minuten
        else:
            kosten += runde_div(minuten * satz, 60)
    return {"cost_minor": kosten, "minutes_total": sum(m for m, _ in rows), "minutes_without_rate": ohne}


def profitability(session: Session, visible: Any, project: Project) -> dict[str, Any]:
    w = project.currency
    erloes, rech_fremd, rech_verborgen = _rechnungen(session, visible, project.id, w)
    aus = _ausgaben(session, visible, project.id, w)
    pers = _personal(session, project.id)
    kosten = aus["net_minor"] + pers["cost_minor"]
    luecken = []
    if pers["minutes_without_rate"]:
        luecken.append({"code": "time_without_rate", "count": pers["minutes_without_rate"],
                        "text": "Projektzeit (Minuten) ohne Stundensatz — nicht als Kosten gezählt"})
    if aus["without_tax_rate"]:
        luecken.append({"code": "receipt_without_tax_rate", "count": aus["without_tax_rate"],
                        "text": "Ausgaben ohne Steuersatz — brutto gezählt"})
    for code, n, text in (("other_currency", rech_fremd + aus["other_currency"], "Posten in anderer Währung"),
                          ("hidden", rech_verborgen + aus["hidden"], "Posten, die du nicht sehen darfst")):
        if n:
            luecken.append({"code": code, "count": n, "text": f"{text} — nicht enthalten"})
    return {"currency": w, "revenue_net_minor": erloes, "receipts_net_minor": aus["net_minor"],
            "receipts_gross_counted_minor": aus["gross_counted_minor"], "labour_cost_minor": pers["cost_minor"],
            "minutes_total": pers["minutes_total"], "cost_minor": kosten, "margin_minor": erloes - kosten,
            "budget_minor": project.budget_minor,
            "budget_used_minor": kosten if project.budget_minor is not None else None,
            "complete": not luecken, "gaps": luecken,
            "note": "Rechenhilfe aus erfassten Daten — keine Kostenrechnung, keine Steuerberatung"}
