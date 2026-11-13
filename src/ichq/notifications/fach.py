"""Geplante Benachrichtigungsregeln der Fachmodule (ADR-020) — laufen in ``ichq notifications-scan``.

Jede Regel stellt nur über ``deliver`` zu (Recht der Art + Objekt-Sichtbarkeit beim Zustellen) und trägt einen
``dedup_key``, der an das fachliche Datum gebunden ist: ein erneuter Lauf am selben oder nächsten Tag stellt nichts
doppelt zu; ändert sich das Datum (neue Fälligkeit), gibt es genau eine neue Mitteilung. Inhalte: nur Titel.
"""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ichq.authz.service import decide
from ichq.contracts import service as contracts
from ichq.finance.invoices import OFFEN
from ichq.finance.models_deadlines import Deadline
from ichq.finance.models_invoices import INVOICE_OPEN, Invoice
from ichq.notifications.service import deliver
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import principal_for_membership
from ichq.travel.models import Travel

GRENZE = 1000
VERTRAG_TAGE = 30
MAX_EMPFAENGER = 50


def _empfaenger(o: ObjectRow, zustaendig: uuid.UUID | None) -> uuid.UUID | None:
    return zustaendig or o.created_by_membership_id


def ueberfaellige_rechnungen(session: Session, heute: date) -> int:
    rows = session.execute(select(Invoice, ObjectRow).join(ObjectRow, ObjectRow.id == Invoice.id).where(
        Invoice.kind == "invoice", Invoice.status.in_(INVOICE_OPEN), OFFEN > 0, Invoice.due_date < heute,
        ObjectRow.archived_at.is_(None)).order_by(Invoice.due_date, Invoice.id).limit(GRENZE)).all()
    n = 0
    for inv, o in rows:
        an = _empfaenger(o, inv.responsible_membership_id or inv.issued_by_membership_id)
        if an is not None and inv.due_date is not None:
            n += deliver(session, an, "invoice.overdue", title=f"Rechnung überfällig: {inv.number}"[:200], obj=o,
                         dedup_key=f"invoice_overdue:{inv.id}:{inv.due_date.isoformat()}")
    return n


def kuendigungstermine(session: Session, heute: date) -> int:
    treffer, _gekappt = contracts.notice_due(session, text("true"), today=heute, days=VERTRAG_TAGE)
    n = 0
    for c, o, t in treffer:
        an = _empfaenger(o, c.responsible_membership_id)
        if an is not None and t.notice_deadline is not None:
            n += deliver(session, an, "contract.expiring",
                         title=f"Kündigung bis {t.notice_deadline:%d.%m.%Y}: {o.title}"[:200], obj=o,
                         dedup_key=f"notice:{c.id}:{t.notice_deadline.isoformat()}")
    return n


def fristen(session: Session, heute: date) -> int:
    rows = session.execute(select(Deadline, ObjectRow).join(ObjectRow, ObjectRow.id == Deadline.id).where(
        Deadline.status == "open", Deadline.due_on - Deadline.remind_days_before <= heute,
        ObjectRow.archived_at.is_(None)).order_by(Deadline.due_on, Deadline.id).limit(GRENZE)).all()
    n = 0
    for d, o in rows:
        an = _empfaenger(o, d.responsible_membership_id)
        if an is not None:
            art = "überfällig" if d.due_on < heute else f"fällig {d.due_on:%d.%m.%Y}"
            n += deliver(session, an, "deadline.reminder", title=f"Frist {art}: {o.title}"[:200], obj=o,
                         dedup_key=f"deadline:{d.id}:{d.due_on.isoformat()}")
    return n


def reiseantraege(session: Session, heute: date) -> int:
    """Eingereichte Reisen an alle, die genehmigen dürfen (außer der reisenden Person) — höchstens 50 je Antrag."""
    antraege = session.execute(select(Travel, ObjectRow).join(ObjectRow, ObjectRow.id == Travel.id).where(
        Travel.status == "submitted").order_by(Travel.submitted_at).limit(GRENZE)).all()
    if not antraege:
        return 0
    mitglieder = session.scalars(text("SELECT id FROM memberships WHERE status = 'active' ORDER BY created_at, id "
                                      "LIMIT 500")).all()
    genehmiger = [m for m in mitglieder
                  if (p := principal_for_membership(session, m)) is not None and decide(p, "travel.approve")]
    n = 0
    for t, o in antraege:
        zugestellt = 0
        for mid in genehmiger:
            if mid == t.traveller_membership_id or zugestellt >= MAX_EMPFAENGER:
                continue
            assert t.submitted_at is not None
            if deliver(session, mid, "travel.submitted", title=f"Reise zu entscheiden: {o.title}"[:200], obj=o,
                       dedup_key=f"travel:{t.id}:{t.submitted_at.isoformat()}"):
                zugestellt += 1
        n += zugestellt
    return n


RULES = {"invoice.overdue": ueberfaellige_rechnungen, "contract.expiring": kuendigungstermine,
         "deadline.reminder": fristen, "travel.submitted": reiseantraege}
