"""Dienstreisen: Antrag (Entwurf → eingereicht) → genehmigt/abgelehnt; storniert. Belege hängen als Nachweis
(Verknüpfung ``evidence`` Ausgabe → Reise) an. Keine Pauschalen-Berechnung (keine amtlichen Werte hinterlegt).

Genehmigen braucht ``travel.approve`` und ist für die eigene Reise verboten — im Service UND per CHECK in der DB.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from ichq.objects.models import ObjectRow
from ichq.objects.service import clean_title, create_object, member, resolve
from ichq.travel.models import Travel

AENDERBAR = ("draft", "rejected")


def _setze(session: Session, p: Principal, t: Travel, w: dict[str, Any]) -> None:
    if w.get("destination"):
        t.destination = " ".join(w["destination"].split())[:300]
    if "purpose" in w:
        t.purpose = (w["purpose"] or "").strip()
    for f in ("start_date", "end_date", "currency"):
        if w.get(f) is not None:
            setattr(t, f, w[f])
    if "estimated_cost_minor" in w:
        t.estimated_cost_minor = w["estimated_cost_minor"]
    if "project" in w:
        t.project_id = resolve(session, p, w["project"], type_="project").id if w["project"] else None
    if t.end_date < t.start_date:
        raise ValidationFailed("end_date liegt vor start_date")


def create(session: Session, p: Principal, *, title: str, werte: dict[str, Any], currency: str) -> tuple[
        Travel, ObjectRow]:
    reisende = member(session, werte["traveller"]).id if werte.get("traveller") else p.membership_id
    o = create_object(session, type_="travel", title=title, actor_membership_id=p.membership_id,
                      search_text=werte.get("destination"))
    t = Travel(id=o.id, tenant_id=o.tenant_id, traveller_membership_id=reisende, destination="",
               start_date=werte["start_date"], end_date=werte["end_date"], currency=currency, status="draft")
    _setze(session, p, t, werte)
    if not t.destination:
        raise ValidationFailed("destination fehlt")
    session.add(t)
    session.flush()
    activity(session, o.id, "travel.created", actor_membership_id=p.membership_id)
    audit(session, "travel.created", actor_membership_id=p.membership_id, target_type="travel", target_id=o.public_id)
    return t, o


def get(session: Session, p: Principal, ref: str) -> tuple[Travel, ObjectRow]:
    o = resolve(session, p, ref, type_="travel")
    t = session.get(Travel, o.id)
    if t is None:
        raise NotFound()
    return t, o


def update(session: Session, p: Principal, ref: str, changes: dict[str, Any]) -> tuple[Travel, ObjectRow]:
    t, o = get(session, p, ref)
    if t.status not in AENDERBAR:
        raise Conflict("Nur Entwürfe und abgelehnte Anträge können geändert werden")
    if "title" in changes:
        o.title = clean_title(changes["title"])
    _setze(session, p, t, changes)
    session.flush()
    activity(session, o.id, "travel.updated", actor_membership_id=p.membership_id, data={"fields": sorted(changes)})
    return t, o


def _status(session: Session, p: Principal, t: Travel, o: ObjectRow, neu: str, note: str | None = None) -> None:
    alt = t.status
    jetzt = session.scalar(select(func.now()))                 # erst Wert holen, dann Felder gemeinsam setzen
    t.status = neu
    if neu == "submitted":
        t.submitted_at, t.decided_at, t.decided_by_membership_id, t.decision_note = jetzt, None, None, None
    if neu in ("approved", "rejected"):
        t.decided_at, t.decided_by_membership_id = jetzt, p.membership_id
        t.decision_note = " ".join((note or "").split())[:500] or None
    session.flush()
    activity(session, o.id, f"travel.{neu}", actor_membership_id=p.membership_id, data={"from": alt})
    audit(session, f"travel.{neu}", actor_membership_id=p.membership_id, target_type="travel", target_id=o.public_id,
          data={"from": alt})


def submit(session: Session, p: Principal, ref: str) -> tuple[Travel, ObjectRow]:
    t, o = get(session, p, ref)
    if t.status not in AENDERBAR:
        raise Conflict("Nur Entwürfe und abgelehnte Anträge können eingereicht werden")
    _status(session, p, t, o, "submitted")
    return t, o


def decide(session: Session, p: Principal, ref: str, *, approve: bool, note: str) -> tuple[Travel, ObjectRow]:
    t, o = get(session, p, ref)
    if t.status != "submitted":
        raise Conflict("Entschieden wird nur über eingereichte Anträge")
    if t.traveller_membership_id == p.membership_id:
        raise PermissionDenied("Die eigene Reise kann nicht selbst genehmigt werden")
    if not approve and len(" ".join(note.split())) < 3:
        raise ValidationFailed("Ablehnung bitte begründen")
    _status(session, p, t, o, "approved" if approve else "rejected", note)
    return t, o


def cancel(session: Session, p: Principal, ref: str) -> tuple[Travel, ObjectRow]:
    t, o = get(session, p, ref)
    if t.status == "cancelled":
        raise Conflict("Reise ist bereits storniert")
    _status(session, p, t, o, "cancelled")
    return t, o


@dataclass(frozen=True)
class TravelFilter:
    status: tuple[str, ...] = ()
    traveller_membership_id: uuid.UUID | None = None
    starts_from: date | None = None


def list_travels(session: Session, visible: Any, f: TravelFilter, limit: int = 200) -> list[Any]:
    stmt = select(Travel, ObjectRow).join(ObjectRow, ObjectRow.id == Travel.id).where(
        visible, ObjectRow.archived_at.is_(None))
    if f.status:
        stmt = stmt.where(Travel.status.in_(f.status))
    if f.traveller_membership_id is not None:
        stmt = stmt.where(Travel.traveller_membership_id == f.traveller_membership_id)
    if f.starts_from is not None:
        stmt = stmt.where(Travel.end_date >= f.starts_from)
    return list(session.execute(stmt.order_by(Travel.start_date.desc(), ObjectRow.id).limit(limit)).all())
