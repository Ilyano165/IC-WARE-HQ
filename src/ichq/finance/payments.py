"""Zahlungseingänge, Rücknahmen und Bearbeitungshistorie offener Rechnungen (Kontakte, Mahnstufen, Wiedervorlage).

* Zahlungen werden manuell erfasst (keine Bankanbindung) und nie gelöscht. Eine falsche Zahlung hebt eine Gegenbuchung
  mit negativem Betrag auf — beide bleiben sichtbar.
* Der Status der Rechnung folgt aus der Summe: bezahlt / teilweise bezahlt / offen (ausgestellt bzw. versendet).
* Überzahlung wird abgelehnt (Restbetrag ist die Obergrenze) — Gutschriften/Erstattungen sind nicht gebaut.
* Mahnungen werden NIE automatisch versendet; hier wird nur dokumentiert, was ein Mensch getan hat.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.finance import invoices, sperre
from ichq.finance.models_invoices import INVOICE_OPEN, Invoice, InvoiceFollowup, Payment
from ichq.objects.models import ObjectRow
from ichq.objects.service import create_object, resolve


def status_nachziehen(session: Session, inv: Invoice) -> None:
    if inv.status in ("draft", "cancelled") or inv.kind != "invoice":
        return
    summe = invoices.paid(session, inv.id)
    if summe >= inv.gross_minor > 0:
        neu = "paid"
    elif summe > 0:
        neu = "partially_paid"
    else:
        neu = "sent" if inv.sent_at is not None else "issued"
    if neu != inv.status:
        inv.status = neu
        session.flush()


def record(session: Session, principal: Principal, ref: str, *, amount_minor: int, paid_on: date, method: str,
           reference: str | None, today: date) -> tuple[Payment, ObjectRow]:
    inv, o = invoices.get(session, principal, ref)
    if inv.kind != "invoice" or inv.status not in INVOICE_OPEN:
        raise Conflict("Zahlungen nur auf offene, ausgestellte Rechnungen")
    if amount_minor <= 0:
        raise ValidationFailed("amount_minor muss positiv sein")
    offen = inv.gross_minor - invoices.paid(session, inv.id)
    if amount_minor > offen:
        raise ValidationFailed(f"Betrag übersteigt den offenen Rest ({offen} Cent) — "
                               "Überzahlungen sind nicht vorgesehen")
    if paid_on > today:
        raise ValidationFailed("paid_on darf nicht in der Zukunft liegen")
    sperre.pruefe(session, paid_on)
    po = create_object(session, type_="payment", title=f"Zahlung zu {inv.number}",
                       actor_membership_id=principal.membership_id)
    pay = Payment(id=po.id, tenant_id=inv.tenant_id, invoice_id=inv.id, paid_on=paid_on, amount_minor=amount_minor,
                  currency=inv.currency, method=method, reference=(reference or "").strip()[:200] or None)
    session.add(pay)
    session.flush()
    status_nachziehen(session, inv)
    activity(session, o.id, "payment.received", actor_membership_id=principal.membership_id)
    audit(session, "payment.recorded", actor_membership_id=principal.membership_id, target_type="invoice",
          target_id=o.public_id, data={"payment": po.public_id})
    return pay, po


def reverse(session: Session, principal: Principal, ref: str, payment_ref: str, *,
            today: date) -> tuple[Payment, ObjectRow]:
    inv, o = invoices.get(session, principal, ref)
    po = resolve(session, principal, payment_ref, type_="payment")
    alt = session.get(Payment, po.id)
    if alt is None or alt.invoice_id != inv.id:
        raise NotFound()
    if alt.reverses_payment_id is not None:
        raise Conflict("Eine Rücknahme kann nicht zurückgenommen werden — Zahlung neu erfassen")
    if session.scalar(select(Payment.id).where(Payment.reverses_payment_id == alt.id)) is not None:
        raise Conflict("Diese Zahlung wurde bereits zurückgenommen")
    ro = create_object(session, type_="payment", title=f"Rücknahme Zahlung zu {inv.number}",
                       actor_membership_id=principal.membership_id)
    rev = Payment(id=ro.id, tenant_id=inv.tenant_id, invoice_id=inv.id, paid_on=today, amount_minor=-alt.amount_minor,
                  currency=alt.currency, method=alt.method, reference="Rücknahme", reverses_payment_id=alt.id)
    session.add(rev)
    session.flush()
    status_nachziehen(session, inv)
    activity(session, o.id, "payment.reversed", actor_membership_id=principal.membership_id)
    audit(session, "payment.reversed", actor_membership_id=principal.membership_id, target_type="invoice",
          target_id=o.public_id, data={"payment": po.public_id, "reversal": ro.public_id})
    return rev, ro


def list_payments(session: Session, invoice_id: uuid.UUID) -> list[tuple[Payment, ObjectRow]]:
    return [(p, o) for p, o in session.execute(
        select(Payment, ObjectRow).join(ObjectRow, ObjectRow.id == Payment.id)
        .where(Payment.invoice_id == invoice_id).order_by(Payment.paid_on, Payment.created_at)).all()]


def add_followup(session: Session, principal: Principal, ref: str, w: dict[str, Any]) -> InvoiceFollowup:
    """Kontaktversuch/Erinnerung/Mahnstufe dokumentieren und Wiedervorlage setzen — versendet NICHTS."""
    inv, o = invoices.get(session, principal, ref)
    if inv.kind != "invoice" or inv.status not in INVOICE_OPEN:
        raise Conflict("Bearbeitung nur für offene, ausgestellte Rechnungen")
    stufe = w.get("dunning_level")
    if w["kind"] == "dunning_level" and stufe is None:
        raise ValidationFailed("dunning_level fehlt")
    f = InvoiceFollowup(id=uuid.uuid4(), tenant_id=inv.tenant_id, invoice_id=inv.id, kind=w["kind"],
                        channel=w.get("channel"), note=(w.get("note") or "").strip()[:5000], dunning_level=stufe,
                        next_follow_up=w.get("next_follow_up"), created_by_membership_id=principal.membership_id)
    session.add(f)
    if stufe is not None:
        inv.dunning_level = stufe
    if "next_follow_up" in w:
        inv.next_follow_up = w.get("next_follow_up")
    session.flush()
    activity(session, o.id, "invoice.followup", actor_membership_id=principal.membership_id,
             data={"kind": w["kind"], "dunning_level": stufe})
    audit(session, "invoice.followup", actor_membership_id=principal.membership_id, target_type="invoice",
          target_id=o.public_id, data={"kind": w["kind"], "dunning_level": stufe})
    return f


def followups(session: Session, invoice_id: uuid.UUID) -> list[InvoiceFollowup]:
    return list(session.scalars(select(InvoiceFollowup).where(InvoiceFollowup.invoice_id == invoice_id)
                                .order_by(InvoiceFollowup.created_at)))
