"""E8 Fahrtenbuch und Dienstreisen (ADR-020 Nr. 8): Fahrten nur als Versionen, Korrektur mit Grund sichtbar in der
Fahrt, Erfassungs- neben Fahrtzeitpunkt, unveränderlich in der DB (auch Superuser), Versionen lückenlos, Kilometer-
Lücken als Hinweis, Periodensperre, Dienstreise-Genehmigung ohne Selbstgenehmigung, Belege als Nachweis, Rechte,
Isolation."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ichq.core.config import Settings
from ichq.core.errors import ValidationFailed
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.tenancy.service import company_today
from ichq.travel import logbook
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok

FAHRER = ["vehicles.read", "vehicles.update", "travel.read", "travel.update", "travel.create"]


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _heute(cw: CoreWorld) -> date:
    with tenant_transaction(cw.engines.app, cw.a) as s:
        return company_today(s)


def _fahrt(c: Any, auto: str, tag: date, start: int, ende: int, **w: Any) -> dict[str, Any]:
    return ok(c.post("/api/v1/trips", json={"vehicle": auto, "trip_date": tag.isoformat(), "start_km": start,
                                            "end_km": ende, "purpose": "business", "destination": "Baustelle Köln",
                                            "reason": "Aufmaß", "business_partner": "Bauherr GmbH", **w}), 201)


def test_fahrt_korrektur_als_version_sichtbar_in_der_fahrt(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(cw)
    auto = ok(c.post("/api/v1/vehicles", json={"name": "Caddy", "license_plate": "k-ic 123"}), 201)
    assert auto["license_plate"] == "K-IC 123"
    assert c.post("/api/v1/vehicles", json={"name": "x", "license_plate": "K-IC 123"}).status_code == 409
    f = _fahrt(c, auto["id"], heute - timedelta(days=3), 10000, 10042)
    cur = f["current"]
    assert (f["version_count"], cur["distance_km"], cur["days_recorded_after_trip"]) == (1, 42, 3)   # nachgetragen
    assert f["first_recorded_at"] and cur["recorded_by"]["id"] == cw.public_id(cw.admin_a)
    assert c.post("/api/v1/trips", json={"vehicle": auto["id"], "trip_date": heute.isoformat(), "start_km": 1,
                                         "end_km": 2, "purpose": "business"}).status_code == 422   # Ziel/Zweck fehlt
    assert c.post(f"/api/v1/trips/{f['id']}/corrections", json={"end_km": 10045}).status_code == 422  # Grund fehlt
    k = ok(c.post(f"/api/v1/trips/{f['id']}/corrections",
                  json={"end_km": 10045, "change_reason": "Tacho falsch abgelesen"}), 201)
    assert [(v["version"], v["end_km"], v["change_reason"]) for v in k["versions"]] == [
        (1, 10042, None), (2, 10045, "Tacho falsch abgelesen")]
    assert k["corrected"] and k["current"]["end_km"] == 10045
    assert c.post(f"/api/v1/trips/{f['id']}/corrections",
                  json={"end_km": 10045, "change_reason": "nichts geändert"}).status_code == 422
    # Datenbank: nur anhängend, Versionen lückenlos, auch der Superuser ändert nichts
    tid = db(engines, "SELECT id FROM objects WHERE public_id = %s", (f["id"],))[0][0]
    with pytest.raises(DBAPIError), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE trip_versions SET end_km = 1 WHERE trip_id = :t"), {"t": tid})
    for sql in ("UPDATE trip_versions SET end_km = 1", "DELETE FROM trip_versions", "DELETE FROM trips"):
        with pytest.raises(Exception, match=r"unveränderlich|nicht geändert"):
            db(engines, sql)
    with pytest.raises(Exception, match="Version muss 3"):
        db(engines, "INSERT INTO trip_versions (id, tenant_id, trip_id, version, trip_date, start_km, end_km, purpose,"
                    " change_reason) VALUES (gen_random_uuid(), %s, %s, 7, current_date, 1, 2, 'private', 'x')",
           (cw.a, tid))
    s_ = ok(c.post(f"/api/v1/trips/{f['id']}/void", json={"reason": "doppelt erfasst"}), 201)
    assert s_["current"]["voided"] and s_["version_count"] == 3
    assert c.post(f"/api/v1/trips/{f['id']}/corrections", json={"end_km": 1, "change_reason": "danach"}
                  ).status_code == 409
    assert ok(c.get("/api/v1/trips"))["items"] == []
    assert [x["id"] for x in ok(c.get("/api/v1/trips?voided=true"))["items"]] == [f["id"]]
    assert c.post(f"/api/v1/objects/{f['id']}/archive").status_code == 409


def test_kilometer_luecken_und_periodensperre(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(cw)
    auto = ok(c.post("/api/v1/vehicles", json={"name": "Sprinter", "license_plate": "K-IC 9"}), 201)["id"]
    a = _fahrt(c, auto, heute - timedelta(days=2), 500, 520)
    b = _fahrt(c, auto, heute - timedelta(days=1), 530, 560, purpose="private", destination="", reason="")
    cc = _fahrt(c, auto, heute, 555, 600)
    luecken = {x["id"]: x["km_gap"] for x in ok(c.get(f"/api/v1/trips?vehicle={auto}"))["items"]}
    assert luecken == {a["id"]: 0, b["id"]: 10, cc["id"]: -5}                 # Lücke 10 km, Überschneidung 5 km
    assert [x["id"] for x in ok(c.get("/api/v1/trips?purpose=private"))["items"]] == [b["id"]]
    assert c.post("/api/v1/trips", json={"vehicle": auto, "trip_date": (heute + timedelta(days=1)).isoformat(),
                                         "start_km": 1, "end_km": 2, "purpose": "private"}).status_code == 422
    vormonat = (heute.replace(day=1) - timedelta(days=1))
    alt = _fahrt(c, auto, vormonat, 100, 120)
    ok(c.post("/api/v1/periods/close", json={"month": vormonat.strftime("%Y-%m"), "confirm_warnings": True}))
    r = c.post(f"/api/v1/trips/{alt['id']}/corrections", json={"end_km": 121, "change_reason": "Tippfehler"})
    assert r.status_code == 409 and "abgeschlossen" in r.text
    assert c.post(f"/api/v1/trips/{alt['id']}/void", json={"reason": "doppelt erfasst"}).status_code == 409
    assert c.post(f"/api/v1/trips/{a['id']}/corrections", json={"trip_date": vormonat.isoformat(),
                                                               "change_reason": "Datum verrutscht"}).status_code == 409
    assert c.post("/api/v1/trips", json={"vehicle": auto, "trip_date": vormonat.isoformat(), "start_km": 1,
                                         "end_km": 2, "purpose": "private"}).status_code == 409
    tid = db(engines, "SELECT id FROM objects WHERE public_id = %s", (alt["id"],))[0][0]
    with pytest.raises(DBAPIError, match="abgeschlossen"), tenant_transaction(engines.app, cw.a) as s:   # App-Rolle direkt
        s.execute(text("INSERT INTO trip_versions (id, tenant_id, trip_id, version, trip_date, start_km, end_km, "
                       "purpose, change_reason) VALUES (gen_random_uuid(), :t, :i, 2, :d, 100, 125, 'private', 'x')"),
                  {"t": cw.a, "i": tid, "d": vormonat})
    with tenant_transaction(engines.app, cw.a) as s, pytest.raises(ValidationFailed):     # zweite Linie im Service
        logbook.correct(s, cw.principal(cw.admin_a), a["id"], werte={"end_km": 521}, grund="  x  ", today=heute)


def test_dienstreise_genehmigung_ohne_selbstgenehmigung(cw: CoreWorld, engines: Engines) -> None:
    fahrer = cw._mitglied(cw.a, "fahrer@alpha.test", "Fritz Fahrer", FAHRER)
    f = cw.client(fahrer)
    admin = cw.client(cw.admin_a)
    r = ok(f.post("/api/v1/travels", json={"title": "Messe Hannover", "destination": "Hannover",
                                           "start_date": "2026-11-10", "end_date": "2026-11-12",
                                           "estimated_cost_minor": 45000}), 201)
    assert (r["status"], r["traveller"]["id"]) == ("draft", cw.public_id(fahrer))
    assert "nicht berechnet" in r["allowances"]
    assert f.post(f"/api/v1/travels/{r['id']}/decision", json={"approve": True}).status_code == 403   # kein Recht
    ok(f.post(f"/api/v1/travels/{r['id']}/submit"))
    assert f.patch(f"/api/v1/travels/{r['id']}", json={"destination": "Berlin"}).status_code == 409
    assert admin.post(f"/api/v1/travels/{r['id']}/decision", json={"approve": False}).status_code == 422
    abgelehnt = ok(admin.post(f"/api/v1/travels/{r['id']}/decision", json={"approve": False, "note": "zu teuer"}))
    assert (abgelehnt["status"], abgelehnt["decision_note"]) == ("rejected", "zu teuer")
    ok(f.patch(f"/api/v1/travels/{r['id']}", json={"estimated_cost_minor": 30000}))
    ok(f.post(f"/api/v1/travels/{r['id']}/submit"))
    gut = ok(admin.post(f"/api/v1/travels/{r['id']}/decision", json={"approve": True}))
    assert (gut["status"], gut["decided_by"]["id"]) == ("approved", cw.public_id(cw.admin_a))
    # Selbstgenehmigung: Service (403) und DB-CHECK
    eigen = ok(admin.post("/api/v1/travels", json={"title": "Eigene", "destination": "Bonn", "start_date": "2026-11-01",
                                                    "end_date": "2026-11-01"}), 201)
    ok(admin.post(f"/api/v1/travels/{eigen['id']}/submit"))
    assert admin.post(f"/api/v1/travels/{eigen['id']}/decision", json={"approve": True}).status_code == 403
    with pytest.raises(DBAPIError, match="no_self_approval"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE travels SET status = 'approved', decided_at = now(), "
                       "decided_by_membership_id = traveller_membership_id"))
    # Beleg als Nachweis
    beleg = ok(admin.post("/api/v1/receipts", json={"title": "Hotel", "amount_minor": 12000}), 201)
    ok(admin.post(f"/api/v1/objects/{beleg['id']}/links", json={"target": r["id"], "link_type": "evidence"}), 201)
    assert [x["id"] for x in ok(admin.get(f"/api/v1/travels/{r['id']}"))["evidence"]] == [beleg["id"]]
    assert [x["id"] for x in ok(f.get(f"/api/v1/travels/{r['id']}"))["evidence"]] == []  # Beleg nicht sichtbar
    assert [x["id"] for x in ok(admin.get("/api/v1/travels?status=submitted"))["items"]] == [eigen["id"]]
    assert ok(f.post(f"/api/v1/travels/{r['id']}/cancel"))["status"] == "cancelled"


def test_rechte_sichtbarkeit_isolation(cw: CoreWorld, engines: Engines) -> None:
    admin = cw.client(cw.admin_a)
    heute = _heute(cw)
    auto = ok(admin.post("/api/v1/vehicles", json={"name": "Caddy", "license_plate": "K-1"}), 201)["id"]
    fahrer = cw._mitglied(cw.a, "fahrer@alpha.test", "Fritz Fahrer", FAHRER)
    f = cw.client(fahrer)
    assert f.post("/api/v1/vehicles", json={"name": "x", "license_plate": "K-2"}).status_code == 403
    eigene = _fahrt(f, auto, heute, 1, 5)
    chef = _fahrt(admin, auto, heute, 5, 9)
    assert [x["id"] for x in ok(f.get("/api/v1/trips"))["items"]] == [eigene["id"]]   # nur Eigenes (kein read_all)
    assert f.get(f"/api/v1/trips/{chef['id']}").status_code == 404
    assert cw.client(cw.ohne).get("/api/v1/trips").status_code == 403
    b = cw.client(cw.admin_b)
    assert b.get(f"/api/v1/trips/{eigene['id']}").status_code == 404
    assert ok(b.get("/api/v1/vehicles"))["items"] == []
    assert b.post("/api/v1/trips", json={"vehicle": auto, "trip_date": heute.isoformat(), "start_km": 1, "end_km": 2,
                                         "purpose": "private"}).status_code == 404
    with tenant_transaction(engines.app, cw.b) as s:
        assert s.execute(text("SELECT count(*) FROM trip_versions")).scalar_one() == 0
