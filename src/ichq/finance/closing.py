"""Monatsabschluss: Prüfliste vor dem Abschluss, abschließen (nur vergangene Monate), wiedereröffnen mit Grund.

Die eigentliche Sperre sitzt in der Datenbank (Trigger, Migration 0015). Hier stehen die Prüfungen, die vor dem
Abschluss angezeigt werden — sie blockieren nicht, müssen aber ausdrücklich bestätigt werden (``confirm_warnings``).
Zählungen laufen über ALLE Datensätze der Firma (nicht nur die sichtbaren): Abschließen erfordert ``finance.approve``.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.core.ids import uuid7
from ichq.core.kalender import plus_monate
from ichq.documents.models import Document
from ichq.finance.models_closing import MonthClose
from ichq.finance.models_invoices import Invoice, Payment
from ichq.finance.models_receipts import Receipt
from ichq.finance.receipts import BELEG


def period_of(text: str) -> date:
    """``YYYY-MM`` → erster Tag des Monats."""
    try:
        jahr, monat = text.split("-")
        return date(int(jahr), int(monat), 1)
    except ValueError as e:
        raise ValidationFailed("Monat im Format YYYY-MM angeben") from e


def _ende(p: date) -> date:
    return date.fromordinal(plus_monate(p, 1).toordinal() - 1)


def active(session: Session, p: date) -> MonthClose | None:
    return session.scalars(select(MonthClose).where(MonthClose.period == p, MonthClose.reopened_at.is_(None))
                           ).one_or_none()


def history(session: Session, p: date) -> list[MonthClose]:
    return list(session.scalars(select(MonthClose).where(MonthClose.period == p).order_by(MonthClose.closed_at)))


def checks(session: Session, p: date) -> dict[str, Any]:
    """Kennzahlen und Warnungen für einen Monat (alle Datensätze der Firma)."""
    von, bis = p, _ende(p)
    def n(stmt: Any) -> int:
        return int(session.scalar(stmt) or 0)
    ausgaben = select(func.count()).select_from(Receipt).where(Receipt.voided_at.is_(None),
                                                              Receipt.expense_date.between(von, bis))
    zahlen = {
        "receipts": n(ausgaben),
        "receipts_missing_evidence": n(ausgaben.where(BELEG != "complete")),
        "invoices_issued": n(select(func.count()).select_from(Invoice).where(Invoice.issue_date.between(von, bis))),
        "invoice_drafts_total": n(select(func.count()).select_from(Invoice).where(Invoice.status == "draft")),
        "payments": n(select(func.count()).select_from(Payment).where(Payment.paid_on.between(von, bis))),
        "documents_unchecked": n(select(func.count()).select_from(Document).where(
            Document.scan_status.not_in(("clean", "infected")))),
    }
    warnungen = []
    if zahlen["receipts_missing_evidence"]:
        warnungen.append({"code": "receipts_missing_evidence", "count": zahlen["receipts_missing_evidence"],
                          "text": "Ausgaben ohne geprüften Beleg"})
    if zahlen["invoice_drafts_total"]:
        warnungen.append({"code": "invoice_drafts", "count": zahlen["invoice_drafts_total"],
                          "text": "Rechnungsentwürfe (noch nicht ausgestellt)"})
    if zahlen["documents_unchecked"]:
        warnungen.append({"code": "documents_unchecked", "count": zahlen["documents_unchecked"],
                          "text": "Dokumente noch in der Virenprüfung"})
    return {"counts": zahlen, "warnings": warnungen}


def close(session: Session, principal: Principal, p: date, *, today: date, note: str,
          confirm_warnings: bool) -> MonthClose:
    if p >= today.replace(day=1):
        raise ValidationFailed("Nur vergangene Monate können abgeschlossen werden")
    if active(session, p) is not None:
        raise Conflict("Monat ist bereits abgeschlossen")
    pruefung = checks(session, p)
    if pruefung["warnings"] and not confirm_warnings:
        raise Conflict("Es gibt offene Punkte — prüfen und mit confirm_warnings bestätigen")
    m = MonthClose(id=uuid7(), tenant_id=principal.tenant_id, period=p, closed_by_membership_id=principal.membership_id,
                   close_note=" ".join(note.split())[:500], warnings=pruefung["warnings"])
    session.add(m)
    session.flush()
    audit(session, "period.closed", actor_membership_id=principal.membership_id, target_type="period",
          target_id=p.strftime("%Y-%m"), data={"warnings": [w["code"] for w in pruefung["warnings"]]})
    return m


def reopen(session: Session, principal: Principal, p: date, reason: str) -> MonthClose:
    grund = " ".join(reason.split())
    if len(grund) < 10:
        raise ValidationFailed("Grund für das Wiedereröffnen angeben (mindestens 10 Zeichen)")
    m = active(session, p)
    if m is None:
        raise NotFound()
    jetzt = session.scalar(select(func.now()))                 # erst Wert holen, dann Felder gemeinsam setzen
    m.reopened_at, m.reopened_by_membership_id, m.reopen_reason = jetzt, principal.membership_id, grund[:500]
    session.flush()
    audit(session, "period.reopened", actor_membership_id=principal.membership_id, target_type="period",
          target_id=p.strftime("%Y-%m"), data={"reason": grund[:500]})
    return m


def overview(session: Session, jahr: int) -> list[dict[str, Any]]:
    aktiv = {m.period: m for m in session.scalars(select(MonthClose).where(
        MonthClose.reopened_at.is_(None), MonthClose.period.between(date(jahr, 1, 1), date(jahr, 12, 1))))}
    wieder = dict(session.execute(select(MonthClose.period, func.count()).where(
        MonthClose.reopened_at.is_not(None), MonthClose.period.between(date(jahr, 1, 1), date(jahr, 12, 1)))
        .group_by(MonthClose.period)).all())
    return [{"period": date(jahr, m, 1), "closed": date(jahr, m, 1) in aktiv,
             "closed_at": aktiv[date(jahr, m, 1)].closed_at if date(jahr, m, 1) in aktiv else None,
             "reopen_count": int(wieder.get(date(jahr, m, 1), 0))} for m in range(1, 13)]
