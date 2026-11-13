"""E9: Projektprofitabilität mit Kennzeichnung unvollständiger Zahlen, Dashboard-Widgets der Fachmodule
(Zahl = Liste), Benachrichtigungsregeln der Fachmodule (einmal je fachlichem Datum). Erwartungen ausgeschrieben."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.notifications import handlers
from ichq.tenancy.service import company_today
from tests.conftest import World
from tests.core_helpers import STEUERBERATER, CoreWorld, ok

LISTEN = {"invoices": "/api/v1/invoices", "receipts": "/api/v1/receipts", "deadlines": "/api/v1/deadlines",
          "projects": "/api/v1/projects", "contracts_notice": "/api/v1/contracts/notice-due",
          "travels": "/api/v1/travels", "trips": "/api/v1/trips", "inquiries": "/api/v1/inquiries"}


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _heute(cw: CoreWorld) -> date:
    with tenant_transaction(cw.engines.app, cw.a) as s:
        return company_today(s)


def _rechnung(c: Any, cent: int, faellig: date, **extra: Any) -> dict[str, Any]:
    k = ok(c.post("/api/v1/customers", json={"name": "Kunde", "allow_duplicate": True}), 201)["id"]
    r = ok(c.post("/api/v1/invoices", json={"customer": k, **extra}), 201)
    ok(c.post(f"/api/v1/invoices/{r['id']}/lines", json={"description": "x", "quantity_milli": 1000,
                                                         "unit_price_minor": cent, "tax_rate_bp": 1900}), 201)
    return ok(c.post(f"/api/v1/invoices/{r['id']}/issue", json={"due_date": faellig.isoformat()}))


def test_profitabilitaet_mit_luecken(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(cw)
    p = ok(c.post("/api/v1/projects", json={"name": "Dach Müller", "budget_minor": 100000}), 201)
    ok(c.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(cw.admin_a)}", json={"hourly_cost_minor": 6000}))
    ok(c.put(f"/api/v1/projects/{p['id']}/members/{cw.public_id(cw.mitarbeiter)}", json={}))
    ok(c.post(f"/api/v1/projects/{p['id']}/time-entries", json={"work_date": heute.isoformat(), "minutes": 90}), 201)
    ok(c.post(f"/api/v1/projects/{p['id']}/time-entries", json={"work_date": heute.isoformat(), "minutes": 30,
                                                                "member": cw.public_id(cw.mitarbeiter)}), 201)
    _rechnung(c, 50000, heute + timedelta(days=14), project=p["id"])
    storno = _rechnung(c, 20000, heute + timedelta(days=14), project=p["id"])
    ok(c.post(f"/api/v1/invoices/{storno['id']}/cancel"))                       # netto hebt sich auf
    entwurf = ok(c.post("/api/v1/invoices", json={"customer": ok(c.post("/api/v1/customers", json={
        "name": "E", "allow_duplicate": True}), 201)["id"], "project": p["id"]}), 201)
    ok(c.post(f"/api/v1/invoices/{entwurf['id']}/lines", json={"description": "x", "quantity_milli": 1000,
                                                               "unit_price_minor": 777, "tax_rate_bp": 0}), 201)
    ok(c.post("/api/v1/receipts", json={"title": "Material", "amount_minor": 11900, "tax_rate_bp": 1900,
                                        "project": p["id"]}), 201)
    ok(c.post("/api/v1/receipts", json={"title": "Kleinkram", "amount_minor": 500, "project": p["id"]}), 201)
    weg = ok(c.post("/api/v1/receipts", json={"title": "Fehler", "amount_minor": 99999, "project": p["id"]}), 201)
    ok(c.post(f"/api/v1/receipts/{weg['id']}/void", json={"reason": "falsch"}))
    r = ok(c.get(f"/api/v1/projects/{p['id']}/profitability"))
    assert (r["revenue_net_minor"], r["receipts_net_minor"], r["labour_cost_minor"]) == (50000, 10500, 9000)
    assert (r["cost_minor"], r["margin_minor"], r["minutes_total"]) == (19500, 30500, 120)
    assert r["receipts_gross_counted_minor"] == 500 and r["budget_used_minor"] == 19500
    assert r["complete"] is False
    assert {(g["code"], g["count"]) for g in r["gaps"]} == {("time_without_rate", 30), ("receipt_without_tax_rate", 1)}
    assert cw.client(cw.stb).get(f"/api/v1/projects/{p['id']}/profitability").status_code == 403  # ohne projects.read
    assert cw.client(cw.admin_b).get(f"/api/v1/projects/{p['id']}/profitability").status_code == 404


def _anzahl(c: Any, pfad: str, params: dict[str, Any]) -> int:
    n, cursor = 0, None
    while True:
        seite = ok(c.get(pfad, params={**params, "limit": 100, **({"cursor": cursor} if cursor else {})}))
        n += len(seite["items"])
        cursor = seite.get("next_cursor")
        if not cursor:
            return n


def test_widgets_zahl_gleich_liste(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(cw)
    _rechnung(c, 1000, heute + timedelta(days=3))
    ok(c.post("/api/v1/invoices", json={"customer": ok(c.post("/api/v1/customers", json={
        "name": "Entwurf", "allow_duplicate": True}), 201)["id"]}), 201)
    ok(c.post("/api/v1/receipts", json={"title": "ohne Beleg", "amount_minor": 100, "follow_up_on":
                                        (heute - timedelta(days=1)).isoformat()}), 201)
    doc = ok(c.post("/api/v1/documents?filename=bon.pdf", content=b"%PDF-1.4 x",
                    headers={"content-type": "application/pdf"}), 201)
    ok(c.post("/api/v1/receipts", json={"title": "in Prüfung", "amount_minor": 100, "document": doc["id"]}), 201)
    ok(c.post("/api/v1/deadlines", json={"title": "USt", "due_on": (heute - timedelta(days=1)).isoformat()}), 201)
    ok(c.post("/api/v1/deadlines", json={"title": "Lohn", "due_on": (heute + timedelta(days=3)).isoformat()}), 201)
    ok(c.post("/api/v1/projects", json={"name": "Aktiv", "status": "active"}), 201)
    ok(c.post("/api/v1/contracts", json={"title": "Miete", "end_date": (heute + timedelta(days=40)).isoformat(),
                                         "notice_value": 1, "notice_unit": "months"}), 201)
    reise = ok(c.post("/api/v1/travels", json={"title": "Messe", "destination": "Köln", "start_date": "2030-01-01",
                                               "end_date": "2030-01-02"}), 201)
    ok(c.post(f"/api/v1/travels/{reise['id']}/submit"))
    ok(c.post("/api/v1/inquiries", json={"title": "Anfrage", "follow_up_on": (heute - timedelta(days=2)).isoformat()}),
       201)
    d = ok(c.get("/api/v1/dashboard"))
    werte = {(w["key"], m["key"]): m["value"] for w in d["widgets"] for m in w["metrics"]}
    erwartet = {("open_invoices", "open"): 1, ("open_invoices", "overdue"): 0, ("open_invoices", "drafts"): 1,
                ("missing_receipts", "missing"): 2, ("missing_receipts", "follow_up"): 1,
                ("tax_deadlines", "overdue"): 1, ("tax_deadlines", "reminder"): 2, ("projects", "active"): 1,
                ("contracts", "notice"): 1, ("travel", "submitted"): 1, ("crm", "open"): 1, ("crm", "follow_up"): 1}
    for k, v in erwartet.items():
        assert werte[k] == v, k
    geprueft = 0
    for w in d["widgets"]:
        for m in w["metrics"]:
            if w.get("list") in LISTEN and m["linked"]:
                assert _anzahl(c, LISTEN[w["list"]], m["filter"]) == m["value"], (w["key"], m["key"])
                geprueft += 1
    assert geprueft >= 14
    liq = next(w for w in d["widgets"] if w["key"] == "liquidity")
    assert liq["items"][0]["title"] == "Kein Kontostand erfasst" and liq["metrics"] == []   # keine erfundene Zahl
    assert [p["key"] for p in d["planned"]] == ["datev_export"]
    kanzlei = cw._mitglied(cw.a, "kanzlei@alpha.test", "Kanzlei", [*STEUERBERATER, "dashboard.read"])
    stb = ok(cw.client(kanzlei).get("/api/v1/dashboard"))           # finance.read ohne read_all: nur Freigegebenes
    stb_werte = {(w["key"], m["key"]): m["value"] for w in stb["widgets"] for m in w["metrics"]}
    assert stb_werte[("missing_receipts", "missing")] == 0 and stb_werte[("open_invoices", "open")] == 0
    assert stb_werte[("tax_deadlines", "overdue")] == 0


def test_benachrichtigungen_der_fachmodule(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(cw)
    fahrer = cw._mitglied(cw.a, "fahrer@alpha.test", "Fritz Fahrer", ["travel.read", "travel.update", "travel.create"])
    r = _rechnung(c, 1000, heute + timedelta(days=30))
    ok(c.post("/api/v1/contracts", json={"title": "Wartung", "end_date": (heute + timedelta(days=40)).isoformat(),
                                         "notice_value": 3, "notice_unit": "weeks"}), 201)
    ok(c.post("/api/v1/deadlines", json={"title": "USt-VA", "due_on": (heute + timedelta(days=5)).isoformat(),
                                         "remind_days_before": 7}), 201)
    ok(c.post("/api/v1/deadlines", json={"title": "Später", "due_on": (heute + timedelta(days=50)).isoformat()}), 201)
    reise = ok(cw.client(fahrer).post("/api/v1/travels", json={"title": "Kunde", "destination": "Bonn",
                                                               "start_date": "2030-01-01", "end_date": "2030-01-01"}), 201)
    ok(cw.client(fahrer).post(f"/api/v1/travels/{reise['id']}/submit"))
    eigene = ok(c.post("/api/v1/travels", json={"title": "Eigene Reise", "destination": "Köln",
                                                "start_date": "2030-02-01", "end_date": "2030-02-01"}), 201)
    ok(c.post(f"/api/v1/travels/{eigene['id']}/submit"))
    with tenant_transaction(engines.app, cw.a) as s:
        heute_ergebnis = handlers.scan(s, heute)
    assert {k: heute_ergebnis[k] for k in ("invoice.overdue", "contract.expiring", "deadline.reminder")} == {
        "invoice.overdue": 0, "contract.expiring": 1, "deadline.reminder": 1}
    assert heute_ergebnis["travel.submitted"] >= 1                              # alle Genehmiger außer der Reisenden
    with tenant_transaction(engines.app, cw.a) as s:
        assert sum(handlers.scan(s, heute).values()) == 0                      # dedup: zweiter Lauf stellt nichts zu
    with tenant_transaction(engines.app, cw.a) as s:
        spaeter = handlers.scan(s, heute + timedelta(days=31))
    assert spaeter["invoice.overdue"] == 1 and spaeter["deadline.reminder"] == 0     # Frist schon gemeldet
    titel = [n["title"] for n in ok(c.get("/api/v1/notifications?limit=100"))["items"]]
    assert any(t.startswith("Rechnung überfällig: " + r["number"]) for t in titel)
    assert any(t.startswith("Kündigung bis ") for t in titel) and any(t.startswith("Frist fällig") for t in titel)
    assert any(t.startswith("Reise zu entscheiden") for t in titel)
    assert "Reise zu entscheiden: Kunde" in titel
    assert "Reise zu entscheiden: Eigene Reise" not in titel                    # nie an die reisende Person
