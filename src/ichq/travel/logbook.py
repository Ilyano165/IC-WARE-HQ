"""Fahrtenbuch: Fahrzeuge, Fahrten als Versionen, Korrektur mit Grund, Storno, Kilometer-Lücken.

Eine Fahrt hat nie „den“ Datensatz zum Überschreiben: jede Änderung ist eine neue Version in ``trip_versions`` mit
Grund, Zeitpunkt und Erfasser, und die API liefert die ganze Historie in der Fahrt mit. Lücken oder Überschneidungen
im Kilometerstand werden als Hinweis gezeigt, nicht verhindert — HQ bewertet die Ordnungsmäßigkeit nicht.
"""
from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, aliased

from ichq.activity.service import record as activity
from ichq.audit.service import record as audit
from ichq.authz.service import Principal
from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.core.ids import uuid7
from ichq.objects.models import ObjectRow
from ichq.objects.service import ARCHIVE_GUARDS, create_object, member, resolve
from ichq.travel.models import PURPOSE, Trip, TripVersion, Vehicle

TEXTE = ("start_place", "destination", "reason", "business_partner")
FELDER = ("trip_date", "start_km", "end_km", "purpose", *TEXTE)
ARCHIVE_GUARDS["trip"] = lambda _s, _o: "Fahrten werden nicht archiviert — Fehleintrag bitte stornieren"


# ---- Fahrzeuge ----------------------------------------------------------------------------------------------------
def vehicles(session: Session, *, archived: bool = False) -> list[Vehicle]:
    return list(session.scalars(select(Vehicle).where(
        Vehicle.archived_at.is_not(None) if archived else Vehicle.archived_at.is_(None)).order_by(Vehicle.name)))


def vehicle(session: Session, ref: str) -> Vehicle:
    v = session.scalars(select(Vehicle).where(Vehicle.public_id == ref)).one_or_none()
    if v is None:
        raise NotFound()
    return v


def create_vehicle(session: Session, p: Principal, *, name: str, plate: str, usage: str) -> Vehicle:
    kennzeichen = " ".join(plate.upper().split())
    if session.scalar(select(Vehicle.id).where(Vehicle.license_plate == kennzeichen)) is not None:
        raise Conflict("Fahrzeug mit diesem Kennzeichen gibt es schon")
    v = Vehicle(id=uuid7(), tenant_id=p.tenant_id, public_id=secrets.token_hex(16), name=" ".join(name.split()),
                license_plate=kennzeichen, usage=usage)
    session.add(v)
    session.flush()
    audit(session, "vehicle.created", actor_membership_id=p.membership_id, target_type="vehicle", target_id=v.public_id)
    return v


def update_vehicle(session: Session, p: Principal, ref: str, changes: dict[str, Any]) -> Vehicle:
    v = vehicle(session, ref)
    if changes.get("name"):
        v.name = " ".join(changes["name"].split())
    if changes.get("usage"):
        v.usage = changes["usage"]
    if "archived" in changes:
        v.archived_at = session.scalar(select(func.now())) if changes["archived"] else None
    session.flush()
    audit(session, "vehicle.updated", actor_membership_id=p.membership_id, target_type="vehicle",
          target_id=v.public_id, data={"fields": sorted(changes)})
    return v


# ---- Fahrten ------------------------------------------------------------------------------------------------------
def _pruefe(w: dict[str, Any], today: date) -> None:
    if w["purpose"] not in PURPOSE:
        raise ValidationFailed("purpose ist ungültig")
    if w["trip_date"] > today:
        raise ValidationFailed("trip_date darf nicht in der Zukunft liegen")
    if w["end_km"] < w["start_km"]:
        raise ValidationFailed("end_km muss mindestens start_km sein")
    if w["purpose"] == "business" and not ((w.get("destination") or "").strip() and (w.get("reason") or "").strip()):
        raise ValidationFailed("Dienstfahrt: Reiseziel und Reisezweck angeben")


def _gesperrt(session: Session, tenant_id: uuid.UUID, *daten: date) -> None:
    """Periodensperre (Migration 0015) vorab prüfen — dieselbe DB-Funktion wie der Trigger, verständlich als 409."""
    with session.no_autoflush:
        for d in daten:
            if session.scalar(text("SELECT ichq_period_closed(:t, :d)"), {"t": tenant_id, "d": d}):
                raise Conflict(f"Monat {d:%Y-%m} ist abgeschlossen — Fahrt erst nach Wiedereröffnen ändern")


def _version(session: Session, p: Principal, trip: Trip, nummer: int, w: dict[str, Any], *, voided: bool = False,
             grund: str | None = None) -> TripVersion:
    texte = {f: " ".join(str(w.get(f) or "").split()) for f in TEXTE}
    alt = session.scalar(select(TripVersion.trip_date).where(TripVersion.trip_id == trip.id)
                         .order_by(TripVersion.version.desc()).limit(1))
    _gesperrt(session, trip.tenant_id, w["trip_date"], *([alt] if alt else []))
    tv = TripVersion(id=uuid7(), tenant_id=trip.tenant_id, trip_id=trip.id, version=nummer, voided=voided,
                     change_reason=grund, recorded_by_membership_id=p.membership_id, trip_date=w["trip_date"],
                     start_km=w["start_km"], end_km=w["end_km"], purpose=w["purpose"], **texte)
    session.add(tv)
    session.flush()
    return tv


def versions(session: Session, trip_id: uuid.UUID) -> list[TripVersion]:
    return list(session.scalars(select(TripVersion).where(TripVersion.trip_id == trip_id)
                                .order_by(TripVersion.version)))


def current(session: Session, trip_id: uuid.UUID) -> TripVersion:
    v = session.scalars(select(TripVersion).where(TripVersion.trip_id == trip_id)
                        .order_by(TripVersion.version.desc()).limit(1)).one_or_none()
    if v is None:
        raise NotFound()
    return v


def create_trip(session: Session, p: Principal, *, vehicle_ref: str, werte: dict[str, Any], driver: str | None,
                today: date) -> tuple[Trip, ObjectRow]:
    _pruefe(werte, today)
    v = vehicle(session, vehicle_ref)
    if v.archived_at is not None:
        raise Conflict("Fahrzeug ist archiviert")
    titel = f"{werte['trip_date']:%d.%m.%Y} {v.license_plate} {werte['start_km']}–{werte['end_km']} km"
    o = create_object(session, type_="trip", title=titel, actor_membership_id=p.membership_id,
                      search_text=" ".join(str(werte.get(k) or "") for k in ("destination", "business_partner")))
    t = Trip(id=o.id, tenant_id=o.tenant_id, vehicle_id=v.id,
             driver_membership_id=member(session, driver).id if driver else p.membership_id)
    session.add(t)
    session.flush()
    _version(session, p, t, 1, werte)
    activity(session, o.id, "trip.created", actor_membership_id=p.membership_id)
    audit(session, "trip.created", actor_membership_id=p.membership_id, target_type="trip", target_id=o.public_id)
    return t, o


def get(session: Session, p: Principal, ref: str) -> tuple[Trip, ObjectRow]:
    o = resolve(session, p, ref, type_="trip")
    t = session.get(Trip, o.id)
    if t is None:
        raise NotFound()
    return t, o


def correct(session: Session, p: Principal, ref: str, *, werte: dict[str, Any], grund: str, today: date) -> tuple[
        Trip, ObjectRow]:
    """Korrektur = neue Version mit Grund. Die alte bleibt unverändert sichtbar."""
    t, o = get(session, p, ref)
    alt = current(session, t.id)
    if alt.voided:
        raise Conflict("Stornierte Fahrt — keine weitere Korrektur")
    neu = {f: werte.get(f, getattr(alt, f)) for f in FELDER}
    if all(neu[f] == getattr(alt, f) for f in FELDER):
        raise ValidationFailed("Keine Änderung angegeben")
    _pruefe(neu, today)
    _version(session, p, t, alt.version + 1, neu, grund=_grund(grund))
    activity(session, o.id, "trip.corrected", actor_membership_id=p.membership_id,
             data={"version": alt.version + 1, "fields": sorted(f for f in FELDER if neu[f] != getattr(alt, f))})
    audit(session, "trip.corrected", actor_membership_id=p.membership_id, target_type="trip", target_id=o.public_id)
    return t, o


def void(session: Session, p: Principal, ref: str, grund: str) -> tuple[Trip, ObjectRow]:
    t, o = get(session, p, ref)
    alt = current(session, t.id)
    if alt.voided:
        raise Conflict("Fahrt ist bereits storniert")
    _version(session, p, t, alt.version + 1, {f: getattr(alt, f) for f in FELDER}, voided=True, grund=_grund(grund))
    activity(session, o.id, "trip.voided", actor_membership_id=p.membership_id)
    audit(session, "trip.voided", actor_membership_id=p.membership_id, target_type="trip", target_id=o.public_id)
    return t, o


def _grund(grund: str) -> str:
    g = " ".join(grund.split())
    if len(g) < 5:
        raise ValidationFailed("Grund der Korrektur angeben (mindestens 5 Zeichen)")
    return g[:500]


# ---- Liste und Kilometer-Kontrolle -------------------------------------------------------------------------------
_V = aliased(TripVersion)
_AKTUELL = (select(func.max(_V.version)).where(_V.trip_id == TripVersion.trip_id).correlate(TripVersion)
            .scalar_subquery())


@dataclass(frozen=True)
class TripFilter:
    vehicle_id: uuid.UUID | None = None
    driver_membership_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    purpose: tuple[str, ...] = ()
    voided: bool = False


def list_trips(session: Session, visible: Any, f: TripFilter, limit: int = 200) -> list[Any]:
    stmt = (select(Trip, ObjectRow, TripVersion).join(ObjectRow, ObjectRow.id == Trip.id)
            .join(TripVersion, TripVersion.trip_id == Trip.id).where(visible, TripVersion.version == _AKTUELL,
                                                                     TripVersion.voided.is_(f.voided)))
    if f.vehicle_id is not None:
        stmt = stmt.where(Trip.vehicle_id == f.vehicle_id)
    if f.driver_membership_id is not None:
        stmt = stmt.where(Trip.driver_membership_id == f.driver_membership_id)
    if f.date_from is not None:
        stmt = stmt.where(TripVersion.trip_date >= f.date_from)
    if f.date_to is not None:
        stmt = stmt.where(TripVersion.trip_date <= f.date_to)
    if f.purpose:
        stmt = stmt.where(TripVersion.purpose.in_(f.purpose))
    return list(session.execute(stmt.order_by(TripVersion.trip_date.desc(), TripVersion.start_km.desc())
                                .limit(limit)).all())


def km_gaps(session: Session, vehicle_id: uuid.UUID) -> dict[uuid.UUID, int]:
    """Je Fahrt: Abstand zum Endstand der vorherigen (nicht stornierten) Fahrt desselben Fahrzeugs, nach
    Kilometerstand geordnet. ≠ 0 heißt Lücke (> 0) oder Überschneidung (< 0). Über ALLE Fahrten des Fahrzeugs —
    ausgegeben wird nur die Zahl, keine Daten fremder Fahrten."""
    rows = session.execute(select(TripVersion.trip_id, TripVersion.start_km, TripVersion.end_km)
                           .join(Trip, Trip.id == TripVersion.trip_id)
                           .where(Trip.vehicle_id == vehicle_id, TripVersion.version == _AKTUELL,
                                  TripVersion.voided.is_(False))
                           .order_by(TripVersion.start_km, TripVersion.end_km)).all()
    luecken, vorher = {}, None
    for tid, start, ende in rows:
        if vorher is not None and start != vorher:
            luecken[tid] = start - vorher
        vorher = ende
    return luecken
