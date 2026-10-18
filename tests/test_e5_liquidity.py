"""E5 Liquidität (ADR-020 Nr. 9): keine vorgetäuschten Kontostände — manuelle Stände (nur anhängend, auch in der DB),
seither erfasste Bewegungen, erwartete Posten, Herkunft jeder Zahl, unvollständige Sicht, Rechte, Isolation."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok

POS = {"description": "Leistung", "quantity_milli": 1000, "unit": "Stk", "unit_price_minor": 10000, "tax_rate_bp": 0}


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _heute(c: Any) -> date:
    k = ok(c.post("/api/v1/customers", json={"name": "Datum-Probe", "allow_duplicate": True}), 201)["id"]
    r = ok(c.post("/api/v1/invoices", json={"customer": k}), 201)
    ok(c.post(f"/api/v1/invoices/{r['id']}/lines", json=POS), 201)
    return date.fromisoformat(ok(c.post(f"/api/v1/invoices/{r['id']}/issue", json={"due_date": "2099-12-31"}))
                              ["issue_date"])


def _rechnung(c: Any, due: date, cent: int) -> dict[str, Any]:
    k = ok(c.post("/api/v1/customers", json={"name": "Kunde", "allow_duplicate": True}), 201)["id"]
    r = ok(c.post("/api/v1/invoices", json={"customer": k}), 201)
    ok(c.post(f"/api/v1/invoices/{r['id']}/lines", json={**POS, "unit_price_minor": cent}), 201)
    return ok(c.post(f"/api/v1/invoices/{r['id']}/issue", json={"due_date": due.isoformat()}))


def _konto(c: Any, name: str, as_of: date, cent: int) -> dict[str, Any]:
    k = ok(c.post("/api/v1/liquidity/accounts", json={"name": name}), 201)
    return ok(c.post(f"/api/v1/liquidity/accounts/{k['id']}/balances",
                     json={"as_of": as_of.isoformat(), "balance_minor": cent, "note": "Auszug"}), 201)


def test_staende_sind_manuell_und_nur_anhaengend(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(c)
    k = _konto(c, "Sparkasse", heute - timedelta(days=5), 120000)
    stand = k["latest_balance"]
    assert (stand["balance_minor"], stand["source"], stand["recorded_by"]["id"]) == (120000, "manual",
                                                                                   cw.public_id(cw.admin_a))
    assert c.post(f"/api/v1/liquidity/accounts/{k['id']}/balances",
                  json={"as_of": (heute + timedelta(days=1)).isoformat(), "balance_minor": 1}).status_code == 422
    neu = ok(c.post(f"/api/v1/liquidity/accounts/{k['id']}/balances",           # Korrektur = neuer Stand
                    json={"as_of": (heute - timedelta(days=5)).isoformat(), "balance_minor": 110000}), 201)
    assert [b["balance_minor"] for b in neu["balances"]] == [110000, 120000]   # Historie bleibt
    assert ok(c.get("/api/v1/liquidity/accounts"))["items"][0]["latest_balance"]["balance_minor"] == 110000
    assert ok(c.get("/api/v1/liquidity"))["manual"]["total_minor"] == 110000         # jüngste Erfassung gilt
    with pytest.raises(DBAPIError, match="permission denied"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE liquidity_balances SET balance_minor = 1"))   # App-Rolle: kein Recht
    for sql in ("UPDATE liquidity_balances SET balance_minor = 1", "DELETE FROM liquidity_balances"):
        with pytest.raises(Exception, match="unveränderlich"):
            db(engines, sql)                                                  # Trigger: auch als Superuser
    arch = ok(c.patch(f"/api/v1/liquidity/accounts/{k['id']}", json={"archived": True}))
    assert arch["archived"] and ok(c.get("/api/v1/liquidity/accounts"))["items"] == []
    assert ok(c.get("/api/v1/liquidity"))["manual"]["accounts"] == []           # archivierte zählen nicht


def test_uebersicht_herleitung_mit_herkunft(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(c)
    _konto(c, "Bank", heute - timedelta(days=10), 100000)
    _konto(c, "Kasse", heute - timedelta(days=3), 5000)
    leer = ok(c.post("/api/v1/liquidity/accounts", json={"name": "Neues Konto"}), 201)
    bezahlt = _rechnung(c, heute + timedelta(days=30), 20000)
    ok(c.post(f"/api/v1/invoices/{bezahlt['id']}/payments", json={"amount_minor": 8000, "paid_on": heute.isoformat(),
                                                                  "method": "bank_transfer"}), 201)
    ok(c.post("/api/v1/receipts", json={"title": "Werkzeug", "amount_minor": 2500, "expense_date": heute.isoformat(),
                                        "payment_status": "paid", "paid_on": heute.isoformat()}), 201)
    ok(c.post("/api/v1/receipts", json={"title": "Miete", "amount_minor": 70000, "expense_date": heute.isoformat(),
                                        "due_date": (heute + timedelta(days=12)).isoformat()}), 201)
    ok(c.post("/api/v1/receipts", json={"title": "Zu spät", "amount_minor": 1, "expense_date": heute.isoformat(),
                                        "due_date": (heute + timedelta(days=200)).isoformat()}), 201)
    plan = ok(c.post("/api/v1/liquidity/forecasts", json={"expected_on": (heute + timedelta(days=40)).isoformat(),
                                                          "amount_minor": 30000, "label": "Förderung"}), 201)
    weg = ok(c.post("/api/v1/liquidity/forecasts", json={"expected_on": (heute + timedelta(days=5)).isoformat(),
                                                         "amount_minor": -99999, "label": "abgesagt"}), 201)
    ok(c.patch(f"/api/v1/liquidity/forecasts/{weg['id']}", json={"status": "cancelled"}))
    ok(c.post("/api/v1/liquidity/forecasts", json={"expected_on": (heute + timedelta(days=5)).isoformat(),
                                                   "amount_minor": 777, "label": "Dollar", "currency": "USD"}), 201)
    assert c.post("/api/v1/liquidity/forecasts", json={"expected_on": heute.isoformat(), "amount_minor": 0,
                                                       "label": "x"}).status_code == 422

    u = ok(c.get("/api/v1/liquidity?horizon_days=90&bucket=month"))
    m = u["manual"]
    assert (m["total_minor"], m["dates_differ"], m["oldest_as_of"]) == (105000, True,
                                                                         (heute - timedelta(days=10)).isoformat())
    assert [x["name"] for x in m["accounts_without_balance"]] == [leer["name"]]
    r = u["recorded"]
    assert (r["inflows"]["total_minor"], r["outflows"]["total_minor"]) == (8000, -2500)
    assert {x["type"] for x in r["inflows"]["items"] + r["outflows"]["items"]} == {"payment", "receipt"}
    assert u["estimated_today_minor"] == 105000 + 8000 - 2500
    e = u["expected"]
    # Probe-Rechnung (10000, fällig 2099) liegt hinter dem Horizont; bezahlte Rechnung mit Rest 12000
    assert [(x["type"], x["amount_minor"]) for x in e["receivables"]["items"]] == [("invoice", 12000)]
    assert [(x["title"], x["amount_minor"]) for x in e["payables"]["items"]] == [("Miete", -70000)]
    assert [(x["id"], x["amount_minor"]) for x in e["forecasts"]["items"]] == [(plan["id"], 30000)]
    assert u["other_currencies"] == [{"currency": "USD", "open_items": 1}]
    assert u["hidden_items"] == 0
    zeit = u["timeline"]
    assert zeit[0]["from"] == heute.isoformat() and zeit[-1]["to"] == (heute + timedelta(days=90)).isoformat()
    assert zeit[-1]["balance_minor"] == 110500 + 12000 - 70000 + 30000
    assert sum(z["inflow_minor"] + z["outflow_minor"] for z in zeit) == 12000 - 70000 + 30000
    assert c.get("/api/v1/liquidity?bucket=day").status_code == 422
    ohne = ok(c.get("/api/v1/liquidity?currency=CHF"))
    assert ohne["manual"]["accounts"] == [] and ohne["estimated_today_minor"] == 0


def test_ohne_stand_keine_schaetzung_aber_erwartungen(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    heute = _heute(c)
    u = ok(c.get("/api/v1/liquidity"))
    assert (u["manual"]["oldest_as_of"], u["recorded"]["since"], u["estimated_today_minor"]) == (None, None, 0)
    ok(c.post("/api/v1/liquidity/forecasts", json={"expected_on": (heute - timedelta(days=3)).isoformat(),
                                                   "amount_minor": -500, "label": "verpasst"}), 201)
    f = ok(c.get("/api/v1/liquidity"))["expected"]["forecasts"]["items"][0]
    assert (f["date"], f["due_date"], f["overdue"]) == (heute.isoformat(), (heute - timedelta(days=3)).isoformat(), True)


def test_rechte_unvollstaendige_sicht_isolation(cw: CoreWorld, engines: Engines) -> None:
    admin = cw.client(cw.admin_a)
    heute = _heute(admin)
    k = _konto(admin, "Bank", heute - timedelta(days=1), 1000)
    r = _rechnung(admin, heute + timedelta(days=9), 5000)
    ok(admin.post(f"/api/v1/invoices/{r['id']}/payments", json={"amount_minor": 700, "paid_on": heute.isoformat()}), 201)
    ok(admin.post("/api/v1/receipts", json={"title": "Geheim", "amount_minor": 400, "expense_date": heute.isoformat()}),
       201)
    ma = cw.client(cw.mitarbeiter)                                     # finance.read, aber nicht finance.update
    alles = ok(ma.get("/api/v1/liquidity"))
    assert (alles["manual"]["total_minor"], alles["estimated_today_minor"], alles["hidden_items"]) == (1000, 1700, 0)
    assert ma.post("/api/v1/liquidity/accounts", json={"name": "x"}).status_code == 403
    assert ma.post(f"/api/v1/liquidity/accounts/{k['id']}/balances",
                   json={"as_of": heute.isoformat(), "balance_minor": 1}).status_code == 403
    stb = ok(cw.client(cw.stb).get("/api/v1/liquidity"))                # sieht nur Freigegebenes
    assert stb["expected"]["payables"]["items"] == [] and stb["expected"]["receivables"]["items"] == []
    assert (stb["manual"]["total_minor"], stb["estimated_today_minor"], stb["hidden_items"]) == (1000, 1000, 4)
    assert cw.client(cw.ohne).get("/api/v1/liquidity").status_code == 403
    b = cw.client(cw.admin_b)
    assert ok(b.get("/api/v1/liquidity/accounts"))["items"] == []
    assert b.get(f"/api/v1/liquidity/accounts/{k['id']}").status_code == 404
    assert b.post(f"/api/v1/liquidity/accounts/{k['id']}/balances",
                  json={"as_of": heute.isoformat(), "balance_minor": 1}).status_code == 404
    with tenant_transaction(engines.app, cw.b) as s:
        assert s.execute(text("SELECT count(*) FROM liquidity_balances")).scalar_one() == 0
    konto_a = db(engines, "SELECT id FROM liquidity_accounts")[0][0]
    with pytest.raises(DBAPIError), tenant_transaction(engines.app, cw.b) as s:   # zusammengesetzter FK
        s.execute(text("INSERT INTO liquidity_balances (id, tenant_id, account_id, as_of, balance_minor) "
                       "VALUES (gen_random_uuid(), :t, :a, current_date, 1)"), {"t": cw.b, "a": konto_a})
