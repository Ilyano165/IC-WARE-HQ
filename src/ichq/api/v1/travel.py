"""Fahrtenbuch und Dienstreisen (ADR-020 Nr. 8). Fahrtdaten nur als Versionen; jede Fahrt liefert ihre ganze
Historie mit (Korrekturen sichtbar in der Fahrt). Keine Aussage zur steuerlichen Ordnungsmäßigkeit."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import Field

from ichq.api.security import TenantDB, require, tenant_db
from ichq.api.v1.common import Strict, object_out, object_ref, refs_for, writing
from ichq.authz.service import Principal
from ichq.core.errors import ValidationFailed
from ichq.db.session import TenantSession
from ichq.objects import service as objects
from ichq.objects.models import ObjectRow
from ichq.objects.visibility import can_see, visible_clause
from ichq.relations.service import links_of
from ichq.tenancy.service import company_currency, company_today
from ichq.travel import logbook, travels
from ichq.travel.models import Travel, Trip, TripVersion, Vehicle

router = APIRouter(prefix="/api/v1", tags=["travel"])
KM = 10_000_000
HINWEIS = "Fahrtenbuch-Daten wie erfasst — HQ prüft nicht, ob das Fahrtenbuch steuerlich ordnungsgemäß ist."


class VehicleIn(Strict):
    name: str = Field(min_length=1, max_length=100)
    license_plate: str = Field(min_length=1, max_length=20)
    usage: str = Field(default="mixed", pattern="^(company|mixed)$")


class VehiclePatch(Strict):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    usage: str | None = Field(default=None, pattern="^(company|mixed)$")
    archived: bool | None = None


class TripFields(Strict):
    trip_date: date | None = None
    start_km: int | None = Field(default=None, ge=0, le=KM)
    end_km: int | None = Field(default=None, ge=0, le=KM)
    purpose: str | None = Field(default=None, pattern="^(business|private|commute)$")
    start_place: str | None = Field(default=None, max_length=200)
    destination: str | None = Field(default=None, max_length=300)
    reason: str | None = Field(default=None, max_length=500, description="Reisezweck")
    business_partner: str | None = Field(default=None, max_length=300)


class TripIn(TripFields):
    vehicle: str = Field(min_length=1, max_length=64)
    driver: str | None = Field(default=None, max_length=64)
    trip_date: date
    start_km: int = Field(ge=0, le=KM)
    end_km: int = Field(ge=0, le=KM)
    purpose: str = Field(pattern="^(business|private|commute)$")


class CorrectionIn(TripFields):
    change_reason: str = Field(min_length=5, max_length=500)


class ReasonIn(Strict):
    reason: str = Field(min_length=5, max_length=500)


class TravelFields(Strict):
    destination: str | None = Field(default=None, min_length=1, max_length=300)
    purpose: str | None = Field(default=None, max_length=5000)
    start_date: date | None = None
    end_date: date | None = None
    project: str | None = Field(default=None, max_length=64)
    estimated_cost_minor: int | None = Field(default=None, ge=0, le=10**13)


class TravelIn(TravelFields):
    title: str = Field(min_length=1, max_length=300)
    destination: str = Field(min_length=1, max_length=300)
    start_date: date
    end_date: date
    traveller: str | None = Field(default=None, max_length=64)


class TravelPatch(TravelFields):
    title: str | None = Field(default=None, min_length=1, max_length=300)


class DecisionIn(Strict):
    approve: bool
    note: str = Field(default="", max_length=500)


def vehicle_out(v: Vehicle) -> dict[str, Any]:
    return {"id": v.public_id, "name": v.name, "license_plate": v.license_plate, "usage": v.usage,
            "archived": v.archived_at is not None}


def version_out(tv: TripVersion, refs: dict[Any, Any]) -> dict[str, Any]:
    return {"version": tv.version, "trip_date": tv.trip_date, "start_km": tv.start_km, "end_km": tv.end_km,
            "distance_km": tv.end_km - tv.start_km, "purpose": tv.purpose, "start_place": tv.start_place,
            "destination": tv.destination, "reason": tv.reason, "business_partner": tv.business_partner,
            "voided": tv.voided, "change_reason": tv.change_reason, "recorded_at": tv.recorded_at,
            "recorded_by": refs.get(tv.recorded_by_membership_id) if tv.recorded_by_membership_id else None,
            "days_recorded_after_trip": (tv.recorded_at.date() - tv.trip_date).days}


def trip_out(s: TenantSession, t: Trip, o: ObjectRow, *, history: bool, luecken: dict[Any, int] | None = None
             ) -> dict[str, Any]:
    alle = logbook.versions(s, t.id)
    refs = refs_for(s, {t.driver_membership_id, *(v.recorded_by_membership_id for v in alle)})
    v = s.get(Vehicle, t.vehicle_id)
    assert v is not None
    gaps = luecken if luecken is not None else logbook.km_gaps(s, t.vehicle_id)
    return {**object_out(s, o), "vehicle": vehicle_out(v),
            "driver": refs.get(t.driver_membership_id) if t.driver_membership_id else None,
            "current": version_out(alle[-1], refs), "version_count": len(alle),
            "corrected": len(alle) > 1, "first_recorded_at": alle[0].recorded_at, "km_gap": gaps.get(t.id, 0),
            "versions": [version_out(x, refs) for x in alle] if history else None, "note": HINWEIS}


def travel_out(s: TenantSession, p: Principal, t: Travel, o: ObjectRow, *, links: bool = False) -> dict[str, Any]:
    refs = refs_for(s, {t.traveller_membership_id, t.decided_by_membership_id})
    projekt = object_ref(objects.by_id(s, t.project_id)) if t.project_id and can_see(s, p, t.project_id) else None
    out = {**object_out(s, o), "traveller": refs.get(t.traveller_membership_id), "destination": t.destination,
           "purpose": t.purpose, "start_date": t.start_date, "end_date": t.end_date, "project": projekt,
           "estimated_cost_minor": t.estimated_cost_minor, "currency": t.currency, "status": t.status,
           "submitted_at": t.submitted_at, "decided_at": t.decided_at, "decision_note": t.decision_note,
           "decided_by": refs.get(t.decided_by_membership_id) if t.decided_by_membership_id else None,
           "allowances": "nicht berechnet — keine amtlichen Pauschalen hinterlegt",
           "own": t.traveller_membership_id == p.membership_id}
    if links:
        out["evidence"] = [x["object"] for x in links_of(s, p, o)
                           if x["link_type"] == "evidence" and x["direction"] == "incoming"]
    return out


# ---- Fahrzeuge ----------------------------------------------------------------------------------------------------
@router.get("/vehicles")
def list_vehicles(p: Principal = Depends(require("vehicles.read")), db: TenantDB = Depends(tenant_db),
                  archived: bool = False) -> dict[str, Any]:
    with db() as s:
        return {"items": [vehicle_out(v) for v in logbook.vehicles(s, archived=archived)]}


@router.post("/vehicles", status_code=201)
def create_vehicle(body: VehicleIn, p: Principal = Depends(require("vehicles.create")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        return vehicle_out(logbook.create_vehicle(s, p, name=body.name, plate=body.license_plate, usage=body.usage))


@router.patch("/vehicles/{vehicle}")
def update_vehicle(vehicle: str, body: VehiclePatch, p: Principal = Depends(require("vehicles.create")),
                   db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    with writing(db) as s:
        return vehicle_out(logbook.update_vehicle(s, p, vehicle, changes))


# ---- Fahrten ------------------------------------------------------------------------------------------------------
@router.get("/trips")
def list_trips(p: Principal = Depends(require("vehicles.read")), db: TenantDB = Depends(tenant_db),
               vehicle: Annotated[str | None, Query(max_length=64)] = None,
               driver: Annotated[str | None, Query(max_length=64, description="ID oder 'me'")] = None,
               date_from: date | None = None, date_to: date | None = None,
               purpose: Annotated[list[str] | None, Query(max_length=3)] = None, voided: bool = False
               ) -> dict[str, Any]:
    if purpose and not set(purpose) <= {"business", "private", "commute"}:
        raise ValidationFailed("purpose muss aus business, private, commute sein")
    with db() as s:
        fz = logbook.vehicle(s, vehicle) if vehicle else None
        wer = p.membership_id if driver == "me" else (objects.member(s, driver, active_only=False).id if driver
                                                      else None)
        f = logbook.TripFilter(vehicle_id=fz.id if fz else None, driver_membership_id=wer, date_from=date_from,
                               date_to=date_to, purpose=tuple(purpose or ()), voided=voided)
        rows = logbook.list_trips(s, visible_clause(p), f)
        luecken: dict[Any, int] = {}
        for vid in {t.vehicle_id for t, _o, _v in rows}:
            luecken.update(logbook.km_gaps(s, vid))
        return {"items": [trip_out(s, t, o, history=False, luecken=luecken) for t, o, _v in rows], "note": HINWEIS}


@router.post("/trips", status_code=201)
def create_trip(body: TripIn, p: Principal = Depends(require("vehicles.update")),
                db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        t, o = logbook.create_trip(s, p, vehicle_ref=body.vehicle, driver=body.driver, today=company_today(s),
                                   werte=body.model_dump(exclude={"vehicle", "driver"}))
        return trip_out(s, t, o, history=True)


@router.get("/trips/{ref}")
def get_trip(ref: str, p: Principal = Depends(require("vehicles.read")),
             db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        t, o = logbook.get(s, p, ref)
        return trip_out(s, t, o, history=True)


@router.post("/trips/{ref}/corrections", status_code=201)
def correct_trip(ref: str, body: CorrectionIn, p: Principal = Depends(require("vehicles.update")),
                 db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Korrektur als neue Version mit Grund — die bisherigen Versionen bleiben unverändert sichtbar."""
    with writing(db) as s:
        t, o = logbook.correct(s, p, ref, werte=body.model_dump(exclude={"change_reason"}, exclude_none=True),
                               grund=body.change_reason, today=company_today(s))
        return trip_out(s, t, o, history=True)


@router.post("/trips/{ref}/void", status_code=201)
def void_trip(ref: str, body: ReasonIn, p: Principal = Depends(require("vehicles.update")),
              db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        t, o = logbook.void(s, p, ref, body.reason)
        return trip_out(s, t, o, history=True)


# ---- Dienstreisen -------------------------------------------------------------------------------------------------
@router.get("/travels")
def list_travels(p: Principal = Depends(require("travel.read")), db: TenantDB = Depends(tenant_db),
                 status: Annotated[list[str] | None, Query(max_length=5)] = None,
                 traveller: Annotated[str | None, Query(max_length=64, description="ID oder 'me'")] = None
                 ) -> dict[str, Any]:
    with db() as s:
        wer = p.membership_id if traveller == "me" else (
            objects.member(s, traveller, active_only=False).id if traveller else None)
        rows = travels.list_travels(s, visible_clause(p), travels.TravelFilter(
            status=tuple(status or ()), traveller_membership_id=wer))
        return {"items": [travel_out(s, p, t, o) for t, o in rows]}


@router.post("/travels", status_code=201)
def create_travel(body: TravelIn, p: Principal = Depends(require("travel.create")),
                  db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        t, o = travels.create(s, p, title=body.title, werte=body.model_dump(exclude={"title"}, exclude_none=True),
                              currency=company_currency(s))
        return travel_out(s, p, t, o, links=True)


@router.get("/travels/{ref}")
def get_travel(ref: str, p: Principal = Depends(require("travel.read")),
               db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with db() as s:
        t, o = travels.get(s, p, ref)
        return travel_out(s, p, t, o, links=True)


@router.patch("/travels/{ref}")
def update_travel(ref: str, body: TravelPatch, p: Principal = Depends(require("travel.update")),
                  db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise ValidationFailed("Keine Änderung angegeben")
    with writing(db) as s:
        t, o = travels.update(s, p, ref, changes)
        return travel_out(s, p, t, o, links=True)


@router.post("/travels/{ref}/submit")
def submit_travel(ref: str, p: Principal = Depends(require("travel.update")),
                  db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        t, o = travels.submit(s, p, ref)
        return travel_out(s, p, t, o, links=True)


@router.post("/travels/{ref}/decision")
def decide_travel(ref: str, body: DecisionIn, p: Principal = Depends(require("travel.approve")),
                  db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    """Genehmigen oder (begründet) ablehnen. Die eigene Reise nie — Service und DB-CHECK."""
    with writing(db) as s:
        t, o = travels.decide(s, p, ref, approve=body.approve, note=body.note)
        return travel_out(s, p, t, o, links=True)


@router.post("/travels/{ref}/cancel")
def cancel_travel(ref: str, p: Principal = Depends(require("travel.update")),
                  db: TenantDB = Depends(tenant_db)) -> dict[str, Any]:
    with writing(db) as s:
        t, o = travels.cancel(s, p, ref)
        return travel_out(s, p, t, o, links=True)
