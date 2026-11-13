"""E6 Fristen und Verträge (ADR-020 Nr. 10): selbst angelegte Fristen mit Quelle/„nicht bestätigt“, Erinnerung,
Wiederholung (genau eine Folgefrist), Kalenderrechnung, Vertragslaufzeit mit Verlängerung und Kündigungstermin,
Kündigung erfassen, Rechte, Isolation."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ichq.contracts import service as contracts
from ichq.contracts.models import Contract
from ichq.contracts.service import termine
from ichq.core.config import Settings
from ichq.core.errors import ValidationFailed
from ichq.core.kalender import plus_monate, verschiebe
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.tenancy.service import company_today
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _heute(cw: CoreWorld) -> date:
    with tenant_transaction(cw.engines.app, cw.a) as s:
        return company_today(s)


def test_kalender_kappt_monatsende() -> None:
    assert plus_monate(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert plus_monate(date(2028, 2, 29), 12) == date(2029, 2, 28)
    assert plus_monate(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert plus_monate(date(2026, 3, 31), -1) == date(2026, 2, 28)
    assert verschiebe(date(2026, 12, 31), -3, "months") == date(2026, 9, 30)
    assert verschiebe(date(2026, 12, 31), -2, "weeks") == date(2026, 12, 17)
    with pytest.raises(ValueError):
        verschiebe(date(2026, 1, 1), 1, "years")


def _vertrag(**w: Any) -> Contract:
    basis: dict[str, Any] = {"status": "active", "auto_renew": False, "renewal_months": None, "notice_value": None,
                             "notice_unit": None, "end_date": None, "terminated_on": None,
                             "termination_effective_on": None}
    return Contract(**{**basis, **w})


def test_vertragstermine_aus_angaben() -> None:
    heute = date(2026, 10, 18)
    fest = _vertrag(end_date=date(2026, 12, 31), notice_value=1, notice_unit="months")
    t = termine(fest, heute)
    assert (t.state, t.term_end, t.notice_deadline, t.renewals) == ("active", date(2026, 12, 31), date(2026, 11, 30), 0)
    # Kündigungstermin verpasst → automatische Verlängerung um 12 Monate, neuer Termin
    auto = _vertrag(end_date=date(2026, 12, 31), notice_value=3, notice_unit="months", auto_renew=True,
                    renewal_months=12)
    t = termine(auto, heute)
    assert (t.term_end, t.notice_deadline, t.renewals) == (date(2027, 12, 31), date(2027, 9, 30), 1)
    alt = _vertrag(end_date=date(2020, 1, 31), notice_value=0, notice_unit="days", auto_renew=True, renewal_months=1)
    assert termine(alt, heute).term_end == date(2026, 10, 31)          # Monatsende korrekt fortgeschrieben
    assert termine(_vertrag(end_date=date(2026, 1, 1)), heute).state == "ended"
    offen = termine(_vertrag(notice_value=2, notice_unit="weeks"), heute)
    assert (offen.state, offen.term_end, offen.notice_deadline) == ("active", date(2026, 11, 1), None)
    gek = _vertrag(status="terminated", terminated_on=date(2026, 9, 1), termination_effective_on=date(2026, 12, 31))
    assert termine(gek, heute).state == "terminated" and termine(gek, date(2027, 1, 1)).state == "ended"
    assert termine(_vertrag(status="draft", end_date=date(2027, 1, 1)), heute).state == "draft"


def test_frist_quelle_erinnerung_wiederholung(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(cw)
    ohne = ok(c.post("/api/v1/deadlines", json={"title": "Umsatzsteuer-Voranmeldung", "category": "tax",
                                                "due_on": (heute + timedelta(days=5)).isoformat(),
                                                "recurrence": "monthly", "remind_days_before": 7,
                                                "responsible": cw.public_id(cw.admin_a)}), 201)
    assert (ohne["source_status"], ohne["status"], ohne["overdue"]) == ("unconfirmed", "open", False)
    assert ohne["reminder_on"] == (heute - timedelta(days=2)).isoformat()
    assert ohne["next_due_on"] == plus_monate(heute + timedelta(days=5), 1).isoformat()
    mit = ok(c.patch(f"/api/v1/deadlines/{ohne['id']}", json={"source_reference": "  laut Steuerberater, Mail 3.10. "}))
    assert (mit["source_status"], mit["source_reference"]) == ("user_reference", "laut Steuerberater, Mail 3.10.")
    spaet = ok(c.post("/api/v1/deadlines", json={"title": "Versicherung", "category": "insurance",
                                                 "due_on": (heute - timedelta(days=1)).isoformat()}), 201)
    fern = ok(c.post("/api/v1/deadlines", json={"title": "Später", "due_on": (heute + timedelta(days=90)).isoformat(),
                                                "remind_days_before": 0}), 201)
    ids = lambda r: [x["id"] for x in ok(r)["items"]]  # noqa: E731
    assert ids(c.get("/api/v1/deadlines?overdue=true")) == [spaet["id"]]
    assert ids(c.get("/api/v1/deadlines?reminder_due=true")) == [spaet["id"], ohne["id"]]
    assert ids(c.get("/api/v1/deadlines?category=tax")) == [ohne["id"]]
    assert ids(c.get("/api/v1/deadlines?responsible=me")) == [ohne["id"]]
    assert ids(c.get("/api/v1/deadlines")) == [spaet["id"], ohne["id"], fern["id"]]
    erledigt = ok(c.post(f"/api/v1/deadlines/{ohne['id']}/complete", json={"note": "abgegeben"}))
    assert (erledigt["status"], erledigt["done_by"]["id"]) == ("done", cw.public_id(cw.admin_a))
    folge = erledigt["next"]
    assert folge["due_on"] == ohne["next_due_on"] and folge["source_reference"] == mit["source_reference"]
    assert folge["responsible"]["id"] == cw.public_id(cw.admin_a) and folge["status"] == "open"
    assert c.post(f"/api/v1/deadlines/{ohne['id']}/complete", json={}).status_code == 409   # nur einmal
    assert c.patch(f"/api/v1/deadlines/{ohne['id']}", json={"title": "x"}).status_code == 409
    assert c.post(f"/api/v1/deadlines/{fern['id']}/cancel", json={"note": ""}).status_code == 422
    abgesagt = ok(c.post(f"/api/v1/deadlines/{fern['id']}/cancel", json={"note": "entfällt"}))
    assert abgesagt["status"] == "cancelled" and abgesagt["next_due_on"] is None
    assert ids(c.get("/api/v1/deadlines?status=done&status=cancelled")) == [ohne["id"], fern["id"]]
    assert c.post("/api/v1/deadlines", json={"title": "x", "due_on": heute.isoformat(),
                                             "category": "steuer"}).status_code == 422


def test_folgefrist_eindeutig_in_der_db(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    a = ok(c.post("/api/v1/deadlines", json={"title": "Lohn", "due_on": "2026-11-10", "recurrence": "monthly"}), 201)
    folge = ok(c.post(f"/api/v1/deadlines/{a['id']}/complete", json={}))["next"]
    zweite = ok(c.post("/api/v1/deadlines", json={"title": "Zweite", "due_on": "2026-11-11"}), 201)
    with pytest.raises(DBAPIError, match="follows_deadline_id"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE deadlines SET follows_deadline_id = (SELECT id FROM objects WHERE public_id = :a) "
                       "WHERE id = (SELECT id FROM objects WHERE public_id = :z)"), {"a": a["id"], "z": zweite["id"]})
    with pytest.raises(DBAPIError, match="done_consistent"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE deadlines SET status = 'done' WHERE id = (SELECT id FROM objects WHERE public_id = :f)"),
                  {"f": folge["id"]})


def test_vertrag_anlegen_kuendigen_liste(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(cw)
    k = ok(c.post("/api/v1/customers", json={"name": "Vermieter GmbH", "allow_duplicate": True}), 201)
    v = ok(c.post("/api/v1/contracts", json={"title": "Mietvertrag Halle", "customer": k["id"],
                                             "contract_type": "Miete", "start_date": "2024-01-01",
                                             "end_date": (heute + timedelta(days=40)).isoformat(),
                                             "notice_value": 3, "notice_unit": "weeks",
                                             "amount_minor": 120000, "billing": "monthly"}), 201)
    assert (v["state"], v["customer"]["id"], v["currency"]) == ("active", k["id"], "EUR")
    assert v["notice_deadline"] == (heute + timedelta(days=40 - 21)).isoformat() and v["days_to_notice"] == 19
    fern = ok(c.post("/api/v1/contracts", json={"title": "Wartung", "counterparty_name": "Aufzug AG",
                                                "end_date": (heute + timedelta(days=400)).isoformat(),
                                                "notice_value": 1, "notice_unit": "months"}), 201)
    ok(c.post("/api/v1/contracts", json={"title": "Ohne Frist", "end_date": (heute + timedelta(days=5)).isoformat()}),
       201)
    verpasst = ok(c.post("/api/v1/contracts", json={"title": "Verpasst", "end_date": (heute + timedelta(days=10)).isoformat(),
                                                   "notice_value": 1, "notice_unit": "months"}), 201)
    assert verpasst["days_to_notice"] < 0                       # Termin verstrichen → nicht mehr „kündbar bis“
    assert [x["id"] for x in ok(c.get("/api/v1/contracts/notice-due?days=30"))["items"]] == [v["id"]]
    assert [x["id"] for x in ok(c.get("/api/v1/contracts?q=aufzug"))["items"]] == [fern["id"]]
    assert [x["id"] for x in ok(c.get(f"/api/v1/contracts?customer={k['id']}"))["items"]] == [v["id"]]
    assert c.post("/api/v1/contracts", json={"title": "x", "notice_value": 3}).status_code == 422
    assert c.post("/api/v1/contracts", json={"title": "x", "auto_renew": True}).status_code == 422
    assert c.post("/api/v1/contracts", json={"title": "x", "start_date": "2026-02-01",
                                             "end_date": "2026-01-01"}).status_code == 422
    assert c.patch(f"/api/v1/contracts/{v['id']}", json={"status": "terminated"}).status_code == 422
    with tenant_transaction(cw.engines.app, cw.a) as s, pytest.raises(ValidationFailed):   # zweite Linie im Service
        contracts.update(s, cw.principal(cw.admin_a), v["id"], {"status": "terminated"})
    zukunft = (heute + timedelta(days=1)).isoformat()
    assert c.post(f"/api/v1/contracts/{v['id']}/terminate",
                  json={"terminated_on": zukunft, "effective_on": zukunft}).status_code == 422
    g = ok(c.post(f"/api/v1/contracts/{v['id']}/terminate",
                  json={"terminated_on": heute.isoformat(), "effective_on": v["end_date"], "note": "per Einschreiben"}))
    assert (g["state"], g["status"], g["notice_deadline"], g["term_end"]) == ("terminated", "terminated", None,
                                                                              v["end_date"])
    assert c.patch(f"/api/v1/contracts/{v['id']}", json={"title": "y"}).status_code == 409
    assert c.post(f"/api/v1/contracts/{v['id']}/terminate",
                  json={"terminated_on": heute.isoformat(), "effective_on": v["end_date"]}).status_code == 409
    assert ok(c.get("/api/v1/contracts/notice-due?days=30"))["items"] == []
    akte = ok(c.get(f"/api/v1/activities?subject={v['id']}"))["items"]
    assert {"contract.created", "contract.terminated"} <= {x["verb"] for x in akte}


def test_rechte_und_isolation(cw: CoreWorld, engines: Engines) -> None:
    admin = cw.client(cw.admin_a)
    v = ok(admin.post("/api/v1/contracts", json={"title": "Geheimvertrag"}), 201)
    f = ok(admin.post("/api/v1/deadlines", json={"title": "Geheimfrist", "due_on": "2026-12-01"}), 201)
    ma = cw.client(cw.mitarbeiter)                     # finance.read, aber weder contracts.* noch finance.create
    assert ma.get("/api/v1/contracts").status_code == 403
    assert ok(ma.get(f"/api/v1/deadlines/{f['id']}"))["title"] == "Geheimfrist"
    assert ma.post("/api/v1/deadlines", json={"title": "x", "due_on": "2026-12-01"}).status_code == 403
    assert cw.client(cw.stb).get(f"/api/v1/deadlines/{f['id']}").status_code == 404     # kein read_all
    b = cw.client(cw.admin_b)
    assert b.get(f"/api/v1/contracts/{v['id']}").status_code == 404
    assert b.post(f"/api/v1/deadlines/{f['id']}/complete", json={}).status_code == 404
    assert ok(b.get("/api/v1/contracts"))["items"] == [] and ok(b.get("/api/v1/deadlines"))["items"] == []
    with tenant_transaction(engines.app, cw.b) as s:
        assert s.execute(text("SELECT count(*) FROM contracts")).scalar_one() == 0
        assert s.execute(text("SELECT count(*) FROM deadlines")).scalar_one() == 0
