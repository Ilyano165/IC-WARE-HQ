"""Rechnungen: Entwurf, Positionen, Ausstellen (Nummer), Versandvermerk, Storno, Liste mit Restbetrag/Überfälligkeit.

* Entwurf: frei änderbar, keine Nummer. Ausstellen vergibt die Nummer aus dem Nummernkreis der Firma und friert
  Kunde (Stand als ``customer_snapshot``), Beträge und Positionen ein — danach schützt die Datenbank (Migration 0011).
* Korrektur = Storno: eine Stornorechnung mit negierten Positionen, eigener Nummer und Verweis aufs Original.
  Stornieren geht nur ohne erfasste Zahlungen (sonst erst Zahlungen klären — keine stille Verrechnung).
* Steuersätze erfasst der Nutzer je Position; es gibt keinen Standardsatz (CLAUDE.md, Steuerregel 1).
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Date, and_, case, cast, func, literal, or_, select, text
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.crm.models import Customer
from ichq.db.paging import SortKey, keyset
from ichq.finance import rechnen
from ichq.finance.models_invoices import INVOICE_OPEN, MAX_TEXT, Invoice, InvoiceDispatch, InvoiceLine, Payment
from ichq.objects.models import ObjectRow
from ichq.objects.service import ARCHIVE_GUARDS, clean_title, create_object, member, resolve
from ichq.objects.visibility import can_see

MAX_LINES = 200
BEZAHLT = select(func.coalesce(func.sum(Payment.amount_minor), 0)).where(
    Payment.invoice_id == Invoice.id).correlate(Invoice).scalar_subquery()
# Restbetrag: nur echte Rechnungen, die ausgestellt und nicht storniert sind (Storno/Entwurf: 0)
OFFEN = case((and_(Invoice.kind == "invoice", Invoice.status.in_((*INVOICE_OPEN, "paid"))),
              Invoice.gross_minor - BEZAHLT), else_=0)
_FERN = cast(literal("9999-12-31"), Date)
SORTS: dict[str, SortKey] = {
    "created_at": SortKey("created_at", ObjectRow.created_at, "ts"),
    "due_date": SortKey("due_date", func.coalesce(Invoice.due_date, _FERN), "date"),
    "issue_date": SortKey("issue_date", func.coalesce(Invoice.issue_date, _FERN), "date"),
    "number": SortKey("number", func.coalesce(Invoice.number, ""), "text"),
}


def _nur_entwurf(inv: Invoice) -> None:
    if inv.status != "draft":
        raise Conflict("Ausgestellte Rechnungen sind unveränderlich — Korrektur nur per Storno")


def _wache(session: Session, o: ObjectRow) -> str | None:
    inv = session.get(Invoice, o.id)
    if inv is not None and inv.status != "draft":
        return "Ausgestellte Rechnungen werden nicht archiviert — bei Bedarf stornieren"
    return None


ARCHIVE_GUARDS["invoice"] = _wache
ARCHIVE_GUARDS["payment"] = lambda _s, _o: "Zahlungen werden nicht archiviert — bei Bedarf zurücknehmen"


def get(session: Session, principal: Principal, ref: str) -> tuple[Invoice, ObjectRow]:
    o = resolve(session, principal, ref, type_="invoice")
    inv = session.get(Invoice, o.id)
    if inv is None:
        raise NotFound()
    return inv, o


def lines(session: Session, invoice_id: uuid.UUID) -> list[InvoiceLine]:
    return list(session.scalars(select(InvoiceLine).where(InvoiceLine.invoice_id == invoice_id)
                                .order_by(InvoiceLine.position)))


def paid(session: Session, invoice_id: uuid.UUID) -> int:
    return int(session.scalar(select(func.coalesce(func.sum(Payment.amount_minor), 0))
                              .where(Payment.invoice_id == invoice_id)) or 0)


def totals(session: Session, inv: Invoice) -> rechnen.Summe:
    return rechnen.summe([(z.tax_rate_bp, rechnen.Zeile(z.net_minor, z.tax_minor)) for z in lines(session, inv.id)])


def _summen_setzen(session: Session, inv: Invoice) -> None:
    s = totals(session, inv)
    inv.net_minor, inv.tax_minor, inv.gross_minor = s.net_minor, s.tax_minor, s.gross_minor


def _bezug(session: Session, principal: Principal, werte: dict[str, Any], inv: Invoice) -> None:
    if "customer" in werte:
        inv.customer_id = resolve(session, principal, werte["customer"], type_="customer").id if werte[
            "customer"] else None
    if "project" in werte:
        inv.project_id = resolve(session, principal, werte["project"], type_="project").id if werte[
            "project"] else None
    if "responsible" in werte:
        inv.responsible_membership_id = member(session, werte["responsible"]).id if werte["responsible"] else None


def create_draft(session: Session, principal: Principal, *, werte: dict[str, Any],
                 currency: str) -> tuple[Invoice, ObjectRow]:
    if len(werte.get("notes") or "") > MAX_TEXT:
        raise ValidationFailed(f"notes: höchstens {MAX_TEXT} Zeichen")
    o = create_object(session, type_="invoice", title=werte.get("title") or "Rechnungsentwurf",
                      actor_membership_id=principal.membership_id)
    inv = Invoice(id=o.id, tenant_id=o.tenant_id, currency=werte.get("currency") or currency,
                  notes=(werte.get("notes") or "").strip(), service_date=werte.get("service_date"),
                  due_date=werte.get("due_date"))
    _bezug(session, principal, werte, inv)
    session.add(inv)
    session.flush()
    activity(session, o.id, "invoice.created", actor_membership_id=principal.membership_id)
    audit(session, "invoice.created", actor_membership_id=principal.membership_id, target_type="invoice",
          target_id=o.public_id)
    return inv, o


def update(session: Session, principal: Principal, ref: str, changes: dict[str, Any]) -> tuple[Invoice, ObjectRow]:
    """Entwurf: alles. Ausgestellt: nur Zuständigkeit (Mahnwesen) — alles andere verweigert schon der Service."""
    inv, o = get(session, principal, ref)
    if set(changes) - {"responsible"}:
        _nur_entwurf(inv)
    if len(changes.get("notes") or "") > MAX_TEXT:
        raise ValidationFailed(f"notes: höchstens {MAX_TEXT} Zeichen")
    if "title" in changes:
        o.title = clean_title(changes["title"])
    for f in ("service_date", "due_date", "currency"):
        if f in changes:
            setattr(inv, f, changes[f])
    if "notes" in changes:
        inv.notes = (changes["notes"] or "").strip()
    _bezug(session, principal, changes, inv)
    session.flush()
    audit(session, "invoice.updated", actor_membership_id=principal.membership_id, target_type="invoice",
          target_id=o.public_id, data={"fields": sorted(changes)})
    return inv, o


# ---- Positionen ---------------------------------------------------------------------------------------------------
def _pos_werte(w: dict[str, Any]) -> dict[str, Any]:
    beschreibung = " ".join(str(w.get("description") or "").split())
    if not beschreibung:
        raise ValidationFailed("description darf nicht leer sein")
    if not w.get("quantity_milli"):
        raise ValidationFailed("quantity_milli darf nicht 0 sein")
    z = rechnen.zeile(w["quantity_milli"], w["unit_price_minor"], w["tax_rate_bp"])
    return {"description": beschreibung[:1000], "quantity_milli": w["quantity_milli"], "unit": w.get("unit") or None,
            "unit_price_minor": w["unit_price_minor"], "tax_rate_bp": w["tax_rate_bp"],
            "net_minor": z.net_minor, "tax_minor": z.tax_minor}


def add_line(session: Session, principal: Principal, ref: str, w: dict[str, Any]) -> InvoiceLine:
    inv, _ = get(session, principal, ref)
    _nur_entwurf(inv)
    vorhanden = lines(session, inv.id)
    if len(vorhanden) >= MAX_LINES:
        raise ValidationFailed(f"höchstens {MAX_LINES} Positionen")
    z = InvoiceLine(id=uuid.uuid4(), tenant_id=inv.tenant_id, public_id=secrets.token_hex(16), invoice_id=inv.id,
                    position=max((x.position for x in vorhanden), default=0) + 1, **_pos_werte(w))
    session.add(z)
    session.flush()
    _summen_setzen(session, inv)
    session.flush()
    return z


def _zeile(session: Session, inv: Invoice, line_ref: str) -> InvoiceLine:
    z = session.scalars(select(InvoiceLine).where(InvoiceLine.public_id == line_ref,
                                                  InvoiceLine.invoice_id == inv.id)).one_or_none()
    if z is None:
        raise NotFound()
    return z


def update_line(session: Session, principal: Principal, ref: str, line_ref: str, w: dict[str, Any]) -> InvoiceLine:
    inv, _ = get(session, principal, ref)
    _nur_entwurf(inv)
    z = _zeile(session, inv, line_ref)
    alt = {"description": z.description, "quantity_milli": z.quantity_milli, "unit": z.unit,
           "unit_price_minor": z.unit_price_minor, "tax_rate_bp": z.tax_rate_bp}
    for k, v in _pos_werte({**alt, **w}).items():
        setattr(z, k, v)
    session.flush()
    _summen_setzen(session, inv)
    session.flush()
    return z


def delete_line(session: Session, principal: Principal, ref: str, line_ref: str) -> None:
    inv, _ = get(session, principal, ref)
    _nur_entwurf(inv)
    session.delete(_zeile(session, inv, line_ref))
    session.flush()
    _summen_setzen(session, inv)


# ---- Ausstellen, Versand, Storno ---------------------------------------------------------------------------------
def _nummer(session: Session, jahr: int) -> str:
    """Lückenloser Nummernkreis je Firma/Jahr: die Zeile ist bis zum Commit gesperrt; ein Abbruch rollt zurück."""
    zeile = session.execute(text("""
        INSERT INTO invoice_number_counters(tenant_id, year, next_value) VALUES (ichq_current_tenant(), :j, 2)
        ON CONFLICT (tenant_id, year) DO UPDATE SET next_value = invoice_number_counters.next_value + 1
        RETURNING next_value - 1 AS n, prefix"""), {"j": jahr}).one()
    return f"{zeile.prefix}{jahr}-{zeile.n:05d}"


def _kundenstand(session: Session, kunde_id: uuid.UUID) -> dict[str, Any]:
    c = session.get(Customer, kunde_id)
    o = session.get(ObjectRow, kunde_id)
    assert c is not None and o is not None
    return {"name": o.title, "legal_name": c.legal_name, "street": c.street, "postal_code": c.postal_code,
            "city": c.city, "country": c.country, "vat_id": c.vat_id}


def _ausstellen(session: Session, principal: Principal, inv: Invoice, o: ObjectRow, heute: date) -> None:
    jetzt = session.scalar(select(func.now()))           # erst Werte holen, dann gemeinsam setzen (Autoflush)
    nummer = _nummer(session, heute.year)
    assert inv.customer_id is not None
    stand = _kundenstand(session, inv.customer_id)
    inv.status, inv.number, inv.issue_date, inv.issued_at = "issued", nummer, heute, jetzt
    inv.issued_by_membership_id, inv.customer_snapshot = principal.membership_id, stand
    o.title = f"{'Storno' if inv.kind == 'cancellation' else 'Rechnung'} {nummer}"
    session.flush()


def issue(session: Session, principal: Principal, ref: str, *, today: date,
          due_date: date | None) -> tuple[Invoice, ObjectRow]:
    inv, o = get(session, principal, ref)
    _nur_entwurf(inv)
    if inv.customer_id is None:
        raise ValidationFailed("Ohne Kunden kann keine Rechnung ausgestellt werden")
    if not can_see(session, principal, inv.customer_id):     # Kunde muss für den Aussteller sichtbar sein
        raise ValidationFailed("Der Kunde dieser Rechnung ist für dich nicht sichtbar")
    if not lines(session, inv.id):
        raise ValidationFailed("Ohne Positionen kann keine Rechnung ausgestellt werden")
    faellig = due_date or inv.due_date
    if faellig is None:
        raise ValidationFailed("Fälligkeitsdatum fehlt (due_date)")
    if faellig < today:
        raise ValidationFailed("Fälligkeit darf nicht vor dem Ausstellungsdatum liegen")
    _summen_setzen(session, inv)
    inv.due_date = faellig
    session.flush()
    _ausstellen(session, principal, inv, o, today)
    activity(session, o.id, "invoice.issued", actor_membership_id=principal.membership_id)
    audit(session, "invoice.issued", actor_membership_id=principal.membership_id, target_type="invoice",
          target_id=o.public_id, data={"number": inv.number})
    return inv, o


def dispatch(session: Session, principal: Principal, ref: str, *, action: str, channel: str | None,
             note: str) -> InvoiceDispatch:
    inv, o = get(session, principal, ref)
    if inv.status == "draft":
        raise Conflict("Ein Entwurf wird nicht versendet — zuerst ausstellen")
    d = InvoiceDispatch(id=uuid.uuid4(), tenant_id=inv.tenant_id, invoice_id=inv.id, action=action, channel=channel,
                        note=" ".join(note.split())[:500], created_by_membership_id=principal.membership_id)
    session.add(d)
    if action == "sent" and inv.sent_at is None:
        jetzt = session.scalar(select(func.now()))
        inv.sent_at = jetzt
        if inv.status == "issued":
            inv.status = "sent"
    session.flush()
    activity(session, o.id, "invoice.dispatched", actor_membership_id=principal.membership_id,
             data={"action": action, "channel": channel})
    audit(session, "invoice.dispatched", actor_membership_id=principal.membership_id, target_type="invoice",
          target_id=o.public_id, data={"action": action, "channel": channel})
    return d


def dispatches(session: Session, invoice_id: uuid.UUID) -> list[InvoiceDispatch]:
    return list(session.scalars(select(InvoiceDispatch).where(InvoiceDispatch.invoice_id == invoice_id)
                                .order_by(InvoiceDispatch.created_at)))


def cancel(session: Session, principal: Principal, ref: str, *, today: date) -> tuple[Invoice, ObjectRow]:
    """Stornorechnung erzeugen und ausstellen; Original wird „storniert". Gibt die Stornorechnung zurück."""
    inv, o = get(session, principal, ref)
    if inv.kind != "invoice" or inv.status not in INVOICE_OPEN:
        raise Conflict("Nur ausgestellte, nicht bezahlte Rechnungen können storniert werden")
    if paid(session, inv.id) != 0:
        raise Conflict("Für diese Rechnung sind Zahlungen erfasst — erst zurücknehmen, dann stornieren")
    so = create_object(session, type_="invoice", title="Storno", actor_membership_id=principal.membership_id)
    storno = Invoice(id=so.id, tenant_id=inv.tenant_id, kind="cancellation", cancels_invoice_id=inv.id,
                     customer_id=inv.customer_id, project_id=inv.project_id, currency=inv.currency,
                     service_date=inv.service_date, due_date=today, notes=f"Storno zu {inv.number}")
    session.add(storno)
    session.flush()
    for i, z in enumerate(lines(session, inv.id), start=1):
        session.add(InvoiceLine(id=uuid.uuid4(), tenant_id=inv.tenant_id, public_id=secrets.token_hex(16),
                                invoice_id=storno.id, position=i, description=z.description,
                                quantity_milli=-z.quantity_milli, unit=z.unit, unit_price_minor=z.unit_price_minor,
                                tax_rate_bp=z.tax_rate_bp, net_minor=-z.net_minor, tax_minor=-z.tax_minor))
    session.flush()
    _summen_setzen(session, storno)
    _ausstellen(session, principal, storno, so, today)
    jetzt = session.scalar(select(func.now()))
    inv.status, inv.cancelled_at = "cancelled", jetzt
    session.flush()
    for oid in (o.id, so.id):
        activity(session, oid, "invoice.cancelled", actor_membership_id=principal.membership_id)
    audit(session, "invoice.cancelled", actor_membership_id=principal.membership_id, target_type="invoice",
          target_id=o.public_id, data={"number": inv.number, "cancellation": storno.number})
    return storno, so


# ---- Liste --------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class InvoiceFilter:
    status: tuple[str, ...] = ()
    customer_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    responsible_membership_id: uuid.UUID | None = None
    overdue_on: date | None = None          # überfällig zum Stichtag: offen, Restbetrag > 0, fällig davor
    open_only: bool = False                 # offene Forderungen (Restbetrag > 0)
    follow_up_before: date | None = None
    q: str | None = None
    archived: bool = False


def filter_clauses(f: InvoiceFilter) -> list[Any]:
    teile: list[Any] = [ObjectRow.archived_at.is_not(None) if f.archived else ObjectRow.archived_at.is_(None)]
    if f.status:
        teile.append(Invoice.status.in_(f.status))
    if f.customer_id is not None:
        teile.append(Invoice.customer_id == f.customer_id)
    if f.project_id is not None:
        teile.append(Invoice.project_id == f.project_id)
    if f.responsible_membership_id is not None:
        teile.append(Invoice.responsible_membership_id == f.responsible_membership_id)
    if f.open_only or f.overdue_on is not None:
        teile += [Invoice.kind == "invoice", Invoice.status.in_(INVOICE_OPEN), OFFEN > 0]
    if f.overdue_on is not None:
        teile.append(Invoice.due_date < f.overdue_on)
    if f.follow_up_before is not None:
        teile += [Invoice.next_follow_up < f.follow_up_before, Invoice.status.in_(INVOICE_OPEN)]
    if f.q:
        muster = f"%{f.q.lower()}%"
        teile.append(or_(func.lower(ObjectRow.title).like(muster), func.lower(Invoice.number).like(muster)))
    return teile


def list_invoices(session: Session, visible: Any, f: InvoiceFilter, *, sort: str, desc: bool, cursor: str | None,
                  limit: int | None) -> tuple[list[Any], str | None]:
    key = SORTS.get(sort)
    if key is None:
        raise ValidationFailed(f"sort muss eine von {sorted(SORTS)} sein")
    stmt = (select(Invoice, ObjectRow, OFFEN.label("open_minor"))
            .join(ObjectRow, ObjectRow.id == Invoice.id).where(visible, *filter_clauses(f)))
    seite = keyset(session, stmt, key, ObjectRow.id, desc=desc, cursor=cursor, limit=limit)
    return list(seite.rows), seite.next_cursor


def days_overdue(inv: Invoice, today: date) -> int:
    return max(0, (today - inv.due_date).days) if inv.due_date else 0


def default_due(today: date, days: int) -> date:
    return today + timedelta(days=days)
