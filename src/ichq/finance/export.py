"""Export für den Steuerberater im internen Format ``ichq-buchungen-v1`` (docs/export-format.md).

Kein DATEV-Format und keine Kompatibilitätsaussage: das Format ist dokumentiert, aber mit keinem Importprogramm
getestet. Jeder Export wird mit Prüfbericht, Prüfsumme und Inhalt gespeichert (Historie, unveränderlich per Trigger)
und kann wiederholt werden; eine Wiederholung zeigt, ob sich die Daten seitdem geändert haben (andere Prüfsumme).
Exportiert werden ALLE Datensätze der Firma im Zeitraum (``finance.export``), nicht nur die sichtbaren.
"""
from __future__ import annotations

import csv
import hashlib
import io
import secrets
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import NotFound, ValidationFailed
from ichq.core.ids import uuid7
from ichq.documents.models import Document
from ichq.finance import invoices as rechnungen
from ichq.finance.models_closing import Export, MonthClose
from ichq.finance.models_invoices import Invoice, Payment
from ichq.finance.models_receipts import Receipt
from ichq.finance.receipts import BELEG
from ichq.objects.models import ObjectRow

FORMAT = "ichq-buchungen-v1"
SPALTEN = ("satzart", "id", "nummer", "datum", "partner", "bezeichnung", "steuersatz_bp", "netto_cent", "steuer_cent",
           "brutto_cent", "waehrung", "status", "beleg", "bezug", "periode_abgeschlossen")
MAX_TAGE = 400
_GEFAEHRLICH = ("=", "+", "-", "@", "\t", "\r")


def zelle(wert: Any) -> str:
    """Text so ausgeben, dass Tabellenprogramme ihn nicht als Formel ausführen (CSV-Injection)."""
    if wert is None:
        return ""
    if isinstance(wert, int):
        return str(wert)
    t = str(wert)
    return "'" + t if t.startswith(_GEFAEHRLICH) else t


def _gesperrt(session: Session, von: date, bis: date) -> set[date]:
    return set(session.scalars(select(MonthClose.period).where(
        MonthClose.reopened_at.is_(None), MonthClose.period.between(von.replace(day=1), bis))))


def rows(session: Session, von: date, bis: date) -> tuple[list[list[Any]], dict[str, Any]]:
    gesperrt = _gesperrt(session, von, bis)

    def zu(d: date | None) -> str:
        return "ja" if d and d.replace(day=1) in gesperrt else "nein"
    zeilen: list[list[Any]] = []
    befunde: list[dict[str, Any]] = []
    for inv, o in session.execute(select(Invoice, ObjectRow).join(ObjectRow, ObjectRow.id == Invoice.id).where(
            Invoice.status != "draft", Invoice.issue_date.between(von, bis))
            .order_by(Invoice.issue_date, Invoice.number)).all():
        partner = (inv.customer_snapshot or {}).get("name")
        bezug = None
        if inv.cancels_invoice_id:
            orig = session.get(Invoice, inv.cancels_invoice_id)
            bezug = orig.number if orig else None
        for satz, (netto, steuer) in sorted(rechnungen.totals(session, inv).tax_by_rate.items()):
            zeilen.append([inv.kind, o.public_id, inv.number, inv.issue_date, partner, o.title, satz, netto, steuer,
                           netto + steuer, inv.currency, inv.status, "", bezug, zu(inv.issue_date)])
    for pay, o, nummer in session.execute(select(Payment, ObjectRow, Invoice.number)
                                          .join(ObjectRow, ObjectRow.id == Payment.id)
                                          .join(Invoice, Invoice.id == Payment.invoice_id)
                                          .where(Payment.paid_on.between(von, bis))
                                          .order_by(Payment.paid_on, ObjectRow.created_at)).all():
        zeilen.append(["payment", o.public_id, None, pay.paid_on, None, pay.reference or "", None, None, None,
                       pay.amount_minor, pay.currency, pay.method, "", nummer, zu(pay.paid_on)])
    for r, o, beleg in session.execute(select(Receipt, ObjectRow, BELEG).join(ObjectRow, ObjectRow.id == Receipt.id)
                                       .where(Receipt.expense_date.between(von, bis))
                                       .order_by(Receipt.expense_date, ObjectRow.created_at)).all():
        doc = session.scalar(select(ObjectRow.public_id).join(Document, Document.id == ObjectRow.id)
                             .where(ObjectRow.id == r.document_id)) if r.document_id else None
        status = "storniert" if r.voided_at else ("bezahlt" if r.payment_status == "paid" else "offen")
        zeilen.append(["receipt", o.public_id, None, r.expense_date, r.supplier_name, o.title, r.tax_rate_bp, None,
                       None, r.amount_minor, r.currency, status, beleg, doc, zu(r.expense_date)])
        if not r.voided_at and beleg != "complete":
            befunde.append({"code": "receipt_evidence", "id": o.public_id, "text": f"Beleg {beleg}: {o.title}"})
        if not r.voided_at and r.tax_rate_bp is None:
            befunde.append({"code": "receipt_tax_rate_missing", "id": o.public_id,
                            "text": f"Kein Steuersatz erfasst: {o.title}"})
    monate, m = [], von.replace(day=1)
    while m <= bis:
        monate.append(m)
        m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
    offen = [x.strftime("%Y-%m") for x in monate if x not in gesperrt]
    if offen:
        befunde.append({"code": "period_open", "text": f"Nicht abgeschlossene Monate: {', '.join(offen)}"})
    return zeilen, {"findings": befunde, "open_periods": offen, "counts": {
        "invoice_rows": sum(1 for z in zeilen if z[0] in ("invoice", "cancellation")),
        "payments": sum(1 for z in zeilen if z[0] == "payment"),
        "receipts": sum(1 for z in zeilen if z[0] == "receipt")}}


def csv_text(zeilen: list[list[Any]]) -> str:
    puffer = io.StringIO()
    w = csv.writer(puffer, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(SPALTEN)
    for z in zeilen:
        w.writerow([zelle(v.isoformat() if isinstance(v, date) else v) for v in z])
    return puffer.getvalue()


def create(session: Session, principal: Principal, *, von: date, bis: date, repeats: Export | None = None) -> Export:
    if bis < von:
        raise ValidationFailed("period_to liegt vor period_from")
    if (bis - von).days > MAX_TAGE:
        raise ValidationFailed(f"Zeitraum höchstens {MAX_TAGE} Tage")
    zeilen, bericht = rows(session, von, bis)
    inhalt = csv_text(zeilen)
    summe = hashlib.sha256(inhalt.encode()).hexdigest()
    if repeats is not None:
        bericht["repeat_of"] = repeats.public_id
        bericht["changed_since_original"] = summe != repeats.sha256
    e = Export(id=uuid7(), tenant_id=principal.tenant_id, public_id=secrets.token_hex(16), format=FORMAT,
               period_from=von, period_to=bis, row_count=len(zeilen), sha256=summe, content=inhalt, report=bericht,
               repeats_export_id=repeats.id if repeats else None, created_by_membership_id=principal.membership_id)
    session.add(e)
    session.flush()
    audit(session, "export.created", actor_membership_id=principal.membership_id, target_type="export",
          target_id=e.public_id, data={"from": von.isoformat(), "to": bis.isoformat(), "rows": len(zeilen),
                                       "findings": len(bericht["findings"])})
    return e


def get(session: Session, ref: str) -> Export:
    e = session.scalars(select(Export).where(Export.public_id == ref)).one_or_none()
    if e is None:
        raise NotFound()
    return e


def history(session: Session, limit: int = 50) -> list[Export]:
    return list(session.scalars(select(Export).order_by(Export.created_at.desc()).limit(limit)))
