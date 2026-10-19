"""E7 Monatsabschluss und Export (ADR-020 Nr. 7, 11): Prüfliste mit Bestätigung, Sperre in Service UND Datenbank,
Beleg nachreichen bleibt erlaubt, Wiedereröffnen nur mit Grund und Historie, Export mit Prüfbericht, Prüfsumme,
CSV-Injection-Schutz, Historie (unveränderlich), Wiederholung, Rechte, Isolation."""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ichq.core.config import Settings
from ichq.core.errors import ValidationFailed
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.finance import closing
from ichq.finance.export import SPALTEN, zelle
from ichq.tenancy.service import company_today
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok

PDF = {"content": b"%PDF-1.4 beleg", "headers": {"content-type": "application/pdf"}}


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _tage(cw: CoreWorld) -> tuple[date, date, str]:
    with tenant_transaction(cw.engines.app, cw.a) as s:
        heute = company_today(s)
    vormonat = (heute.replace(day=1) - timedelta(days=1)).replace(day=15)
    return heute, vormonat, vormonat.strftime("%Y-%m")


def _ausgabe(c: Any, tag: date, **w: Any) -> dict[str, Any]:
    return ok(c.post("/api/v1/receipts", json={"title": "Material", "amount_minor": 1000,
                                               "expense_date": tag.isoformat(), **w}), 201)


def _rid(engines: Engines, ref: str) -> Any:
    return db(engines, "SELECT id FROM objects WHERE public_id = %s", (ref,))[0][0]


def test_abschluss_sperrt_und_laesst_beleg_nachreichen(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    heute, tag, monat = _tage(cw)
    a = _ausgabe(c, tag)
    p = ok(c.get(f"/api/v1/periods/check?month={monat}"))
    assert (p["closed"], p["counts"]["receipts"], p["counts"]["receipts_missing_evidence"]) == (False, 1, 1)
    assert "receipts_missing_evidence" in {w["code"] for w in p["warnings"]}
    assert c.post("/api/v1/periods/close", json={"month": monat}).status_code == 409          # erst bestätigen
    assert c.post("/api/v1/periods/close", json={"month": heute.strftime("%Y-%m"),
                                                 "confirm_warnings": True}).status_code == 422  # laufender Monat
    zu = ok(c.post("/api/v1/periods/close", json={"month": monat, "confirm_warnings": True, "note": "Okt."}))
    assert zu["closed"] and zu["history"][0]["closed_by"]["id"] == cw.public_id(cw.admin_a)
    assert "receipts_missing_evidence" in {w["code"] for w in zu["history"][0]["warnings_at_close"]}
    assert c.post("/api/v1/periods/close", json={"month": monat, "confirm_warnings": True}).status_code == 409
    # Service: verständliche 409
    assert c.post("/api/v1/receipts", json={"title": "x", "amount_minor": 1,
                                            "expense_date": tag.isoformat()}).status_code == 409
    assert c.patch(f"/api/v1/receipts/{a['id']}", json={"amount_minor": 1}).status_code == 409
    assert c.patch(f"/api/v1/receipts/{a['id']}", json={"expense_date": heute.isoformat()}).status_code == 409
    assert c.post(f"/api/v1/receipts/{a['id']}/void", json={"reason": "doppelt"}).status_code == 409
    assert c.patch(f"/api/v1/receipts/{a['id']}", json={"payment_status": "paid",
                                                                 "paid_on": tag.isoformat()}).status_code == 409
    # Erlaubt: Beleg nachreichen, Vermerk, im offenen Monat bezahlen
    doc = ok(c.post("/api/v1/documents?filename=bon.pdf", **PDF), 201)
    assert ok(c.put(f"/api/v1/receipts/{a['id']}/document", json={"document": doc["id"]}))["evidence"] == "unchecked"
    assert ok(c.patch(f"/api/v1/receipts/{a['id']}", json={"missing_reason": "kommt"}))["missing_reason"] == "kommt"
    assert ok(c.patch(f"/api/v1/receipts/{a['id']}", json={"payment_status": "paid"}))["paid_on"] == heute.isoformat()
    # Datenbank: auch direkt gesperrt
    rid = _rid(engines, a["id"])
    with pytest.raises(DBAPIError, match="abgeschlossen"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE receipts SET amount_minor = 1 WHERE id = :i"), {"i": rid})
    with pytest.raises(DBAPIError, match="abgeschlossen"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE receipts SET voided_at = now(), void_reason = 'x' WHERE id = :i"), {"i": rid})
    entwurf = ok(c.post("/api/v1/invoices", json={"customer": ok(c.post("/api/v1/customers", json={
        "name": "K", "allow_duplicate": True}), 201)["id"]}), 201)
    with pytest.raises(DBAPIError, match="abgeschlossen"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE invoices SET issue_date = :d WHERE id = :i"),
                  {"d": tag, "i": _rid(engines, entwurf["id"])})
    with pytest.raises(Exception, match="nicht gelöscht"):
        db(engines, "DELETE FROM month_closes")                                       # auch als Superuser
    # Wiedereröffnen: nur mit Grund, Historie bleibt
    assert c.post("/api/v1/periods/reopen", json={"month": monat, "reason": "kurz"}).status_code == 422
    with tenant_transaction(engines.app, cw.a) as s, pytest.raises(ValidationFailed):     # zweite Linie im Service
        closing.reopen(s, cw.principal(cw.admin_a), tag.replace(day=1), "   zu   kurz   ")
    auf = ok(c.post("/api/v1/periods/reopen", json={"month": monat, "reason": "Rechnung des Lieferanten fehlte"}))
    assert not auf["closed"] and auf["history"][0]["reopen_reason"] == "Rechnung des Lieferanten fehlte"
    assert ok(c.patch(f"/api/v1/receipts/{a['id']}", json={"amount_minor": 1200}))["amount_minor"] == 1200
    with pytest.raises(Exception, match="unveränderlich"):
        db(engines, "UPDATE month_closes SET reopen_reason = 'anders'")               # nur einmal wiedereröffnen
    assert c.post("/api/v1/periods/reopen", json={"month": monat, "reason": "nochmal öffnen bitte"}).status_code == 404
    wieder = ok(c.post("/api/v1/periods/close", json={"month": monat, "confirm_warnings": True}))
    assert wieder["closed"] and len(wieder["history"]) == 2
    jahr = ok(c.get(f"/api/v1/periods?year={tag.year}"))["items"]
    eintrag = next(x for x in jahr if x["period"] == monat)
    assert (eintrag["closed"], eintrag["reopen_count"]) == (True, 1)
    akte = {x["action"] for x in ok(c.get("/api/v1/audit?limit=100"))["items"]}
    assert {"period.closed", "period.reopened"} <= akte


def test_zahlung_im_gesperrten_monat(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    _heute, tag, monat = _tage(cw)
    k = ok(c.post("/api/v1/customers", json={"name": "K", "allow_duplicate": True}), 201)["id"]
    r = ok(c.post("/api/v1/invoices", json={"customer": k}), 201)
    ok(c.post(f"/api/v1/invoices/{r['id']}/lines", json={"description": "x", "quantity_milli": 1000,
                                                         "unit_price_minor": 5000, "tax_rate_bp": 0}), 201)
    a = ok(c.post(f"/api/v1/invoices/{r['id']}/issue", json={"due_date": "2099-01-01"}))
    zahlung = ok(c.post(f"/api/v1/invoices/{a['id']}/payments", json={"amount_minor": 100, "paid_on": a["issue_date"]}),
                 201)["payments"][0]["id"]
    ok(c.post("/api/v1/periods/close", json={"month": monat, "confirm_warnings": True}))
    with pytest.raises(Exception, match="abgeschlossen"):
        db(engines, "UPDATE payments SET paid_on = %s WHERE id = %s", (tag, _rid(engines, zahlung)))
    andere = cw.client(cw.admin_b)                              # Sperre gilt nur für die eigene Firma
    fremd = _ausgabe(andere, tag)
    db(engines, "UPDATE receipts SET amount_minor = 7 WHERE id = %s", (_rid(engines, fremd["id"]),))  # ohne RLS
    ma = cw.client(cw.mitarbeiter)
    assert ok(ma.get(f"/api/v1/periods/check?month={monat}"))["closed"] is True
    assert ma.post("/api/v1/periods/reopen", json={"month": monat, "reason": "möchte ich ändern"}).status_code == 403
    assert ok(andere.get(f"/api/v1/periods/check?month={monat}"))["closed"] is False


def test_zelle_schuetzt_vor_formeln() -> None:
    assert [zelle(x) for x in ("=SUMME(A1)", "+1", "-2", "@x", "normal", None, 5)] == [
        "'=SUMME(A1)", "'+1", "'-2", "'@x", "normal", "", "5"]


def test_export_bericht_pruefsumme_historie_wiederholung(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    heute, tag, monat = _tage(cw)
    k = ok(c.post("/api/v1/customers", json={"name": "Bauherr GmbH", "allow_duplicate": True}), 201)["id"]
    r = ok(c.post("/api/v1/invoices", json={"customer": k}), 201)
    for preis, satz in ((10000, 1900), (5000, 700)):
        ok(c.post(f"/api/v1/invoices/{r['id']}/lines", json={"description": "x", "quantity_milli": 1000,
                                                             "unit_price_minor": preis, "tax_rate_bp": satz}), 201)
    rech = ok(c.post(f"/api/v1/invoices/{r['id']}/issue", json={"due_date": "2099-01-01"}))
    ok(c.post(f"/api/v1/invoices/{r['id']}/payments", json={"amount_minor": 2000, "paid_on": heute.isoformat()}), 201)
    boese = _ausgabe(c, tag, title="=HYPERLINK(\"http://x\")", tax_rate_bp=1900, supplier_name="+Lieferant")
    weg = _ausgabe(c, heute, title="Doppelt")
    ok(c.post(f"/api/v1/receipts/{weg['id']}/void", json={"reason": "doppelt"}))
    ok(c.post("/api/v1/periods/close", json={"month": monat, "confirm_warnings": True}))
    von = tag.replace(day=1)
    e = ok(c.post("/api/v1/exports", json={"period_from": von.isoformat(), "period_to": heute.isoformat()}), 201)
    assert (e["format"], e["datev_compatible"], e["row_count"]) == ("ichq-buchungen-v1", False, 5)
    assert e["report"]["counts"] == {"invoice_rows": 2, "payments": 1, "receipts": 2}
    codes = [f["code"] for f in e["report"]["findings"]]
    assert codes.count("receipt_evidence") == 1 and "period_open" in codes            # Storno zählt nicht
    assert e["report"]["open_periods"] == [heute.strftime("%Y-%m")]
    d = c.get(f"/api/v1/exports/{e['id']}/download")
    assert d.status_code == 200 and d.headers["content-type"].startswith("text/csv")
    assert "attachment" in d.headers["content-disposition"] and d.headers["cache-control"] == "no-store"
    roh = d.content.decode("utf-8")
    assert roh.startswith("﻿")
    inhalt = roh[1:]
    assert hashlib.sha256(inhalt.encode()).hexdigest() == e["sha256"] == d.headers["x-content-sha256"]
    zeilen = [z.split(";") for z in inhalt.split("\r\n") if z]
    assert zeilen[0] == list(SPALTEN)
    rechnung = [z for z in zeilen if z[0] == "invoice"]
    assert {(z[2], z[6], z[7], z[8], z[9]) for z in rechnung} == {(rech["number"], "1900", "10000", "1900", "11900"),
                                                                  (rech["number"], "700", "5000", "350", "5350")}
    ausgabe = next(z for z in zeilen if z[1] == boese["id"])
    assert ausgabe[5].startswith("\"'=HYPERLINK") and ausgabe[4] == "'+Lieferant" and ausgabe[14] == "ja"
    assert next(z for z in zeilen if z[1] == weg["id"])[11] == "storniert"
    assert "export.downloaded" in {x["action"] for x in ok(c.get("/api/v1/audit?limit=100"))["items"]}
    gleich = ok(c.post(f"/api/v1/exports/{e['id']}/repeat"), 201)
    assert gleich["report"]["changed_since_original"] is False and gleich["sha256"] == e["sha256"]
    _ausgabe(c, heute, title="Neu")
    anders = ok(c.post(f"/api/v1/exports/{e['id']}/repeat"), 201)
    assert anders["report"]["changed_since_original"] is True and anders["report"]["repeat_of"] == e["id"]
    assert [x["id"] for x in ok(c.get("/api/v1/exports"))["items"]] == [anders["id"], gleich["id"], e["id"]]
    with pytest.raises(Exception, match="unveränderlich"):
        db(engines, "UPDATE exports SET content = 'gefälscht'")
    assert c.post("/api/v1/exports", json={"period_from": "2025-01-01", "period_to": "2026-12-31"}).status_code == 422
    assert c.post("/api/v1/exports", json={"period_from": "2026-02-01", "period_to": "2026-01-01"}).status_code == 422
    assert cw.client(cw.mitarbeiter).get("/api/v1/exports").status_code == 403
    assert cw.client(cw.admin_b).get(f"/api/v1/exports/{e['id']}/download").status_code == 404
    assert ok(cw.client(cw.admin_b).get("/api/v1/exports"))["items"] == []
