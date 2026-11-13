"""E4 Ausgaben/Belege (ADR-020): Belegprinzip — Status aus Dokument + Virenprüfung, fehlende Belege, Filter,
Zahlungsstatus, Stornieren statt Löschen (auch in der DB), Rechte, Isolation."""
from __future__ import annotations

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

PDF = {"content": b"%PDF-1.4 beleg", "headers": {"content-type": "application/pdf"}}


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _ausgabe(c: Any, **extra: Any) -> dict[str, Any]:
    return ok(c.post("/api/v1/receipts", json={"title": "Baumarkt", "amount_minor": 4999, "expense_date": "2026-10-01",
                                               "supplier_name": "Hornbach", "category": "Material", **extra}), 201)


def _scan(engines: Engines, doc: str, status: str) -> None:
    db(engines, "UPDATE documents SET scan_status = %s WHERE id = (SELECT id FROM objects WHERE public_id = %s)",
       (status, doc))


def test_belegstatus_folgt_dokument_und_virenpruefung(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    a = _ausgabe(c, missing_reason="Kassenbon verloren, Ersatzbeleg angefragt", follow_up_on="2026-10-05")
    assert (a["evidence"], a["has_document"], a["payment_status"]) == ("missing", False, "unpaid")
    assert [x["id"] for x in ok(c.get("/api/v1/receipts?evidence=missing"))["items"]] == [a["id"]]
    assert [x["id"] for x in ok(c.get("/api/v1/receipts?follow_up_due=true"))["items"]] == [a["id"]]
    doc = ok(c.post("/api/v1/documents?filename=bon.pdf", **PDF), 201)
    b = ok(c.put(f"/api/v1/receipts/{a['id']}/document", json={"document": doc["id"]}))
    assert b["evidence"] == "unchecked"                                # Quarantäne zählt NICHT als Beleg
    liste = ok(c.get("/api/v1/receipts?evidence=unchecked"))["items"]       # Listenfilter rechnet in SQL
    assert [(x["id"], x["evidence"]) for x in liste] == [(a["id"], "unchecked")]
    assert ok(c.get("/api/v1/receipts?evidence=complete"))["items"] == []
    _scan(engines, doc["id"], "clean")
    assert ok(c.get(f"/api/v1/receipts/{a['id']}"))["evidence"] == "complete"
    assert ok(c.get("/api/v1/receipts?evidence=missing&evidence=unchecked"))["items"] == []
    assert ok(c.get("/api/v1/receipts?follow_up_due=true"))["items"] == []          # vollständig ⇒ keine Wiedervorlage
    assert ok(c.put(f"/api/v1/receipts/{a['id']}/document", json={"document": None}))["evidence"] == "missing"
    boes = ok(c.post("/api/v1/documents?filename=virus.pdf", **PDF), 201)
    _scan(engines, boes["id"], "infected")
    assert ok(c.put(f"/api/v1/receipts/{a['id']}/document", json={"document": boes["id"]}))["evidence"] == "rejected"
    # Beleg direkt beim Anlegen
    mit = _ausgabe(c, document=doc["id"])
    assert mit["evidence"] == "complete" and mit["document"]["id"] == doc["id"]
    assert c.put(f"/api/v1/receipts/{a['id']}/document", json={"document": a["id"]}).status_code == 404  # kein Dokument


def test_filter_zeitraum_projekt_zustaendig_suche(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    p = ok(c.post("/api/v1/projects", json={"name": "Dach"}), 201)
    a = _ausgabe(c, project=p["id"], responsible=cw.public_id(cw.admin_a))
    b = _ausgabe(c, title="Tankstelle", supplier_name="Aral", category="Fahrzeug", expense_date="2026-09-15",
                 amount_minor=8000)
    assert [x["id"] for x in ok(c.get(f"/api/v1/receipts?project={p['id']}"))["items"]] == [a["id"]]
    assert [x["id"] for x in ok(c.get("/api/v1/receipts?responsible=me"))["items"]] == [a["id"]]
    sept = ok(c.get("/api/v1/receipts?date_from=2026-09-01&date_to=2026-09-30"))["items"]
    assert [x["id"] for x in sept] == [b["id"]]
    assert [x["id"] for x in ok(c.get("/api/v1/receipts?q=aral"))["items"]] == [b["id"]]
    assert [x["id"] for x in ok(c.get("/api/v1/receipts?sort=amount&order=desc"))["items"]] == [b["id"], a["id"]]
    assert c.get("/api/v1/receipts?evidence=weg").status_code == 422
    assert c.post("/api/v1/receipts", json={"title": "x", "amount_minor": 0}).status_code == 422
    assert c.post("/api/v1/receipts", json={"title": "x", "amount_minor": 1, "expense_date": "2099-01-01"}).status_code == 422


def test_zahlungsstatus(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    a = _ausgabe(c, due_date="2026-11-01")
    bezahlt = ok(c.patch(f"/api/v1/receipts/{a['id']}", json={"payment_status": "paid"}))
    assert bezahlt["payment_status"] == "paid" and bezahlt["paid_on"]
    assert c.patch(f"/api/v1/receipts/{a['id']}", json={"paid_on": "2099-01-01"}).status_code == 422
    offen = ok(c.patch(f"/api/v1/receipts/{a['id']}", json={"payment_status": "unpaid"}))
    assert (offen["payment_status"], offen["paid_on"]) == ("unpaid", None)
    assert [x["id"] for x in ok(c.get("/api/v1/receipts?payment_status=unpaid"))["items"]] == [a["id"]]


def test_stornieren_statt_loeschen_auch_in_der_db(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    a = _ausgabe(c)
    assert c.post(f"/api/v1/objects/{a['id']}/archive").status_code == 409
    assert c.post(f"/api/v1/receipts/{a['id']}/void", json={"reason": ""}).status_code == 422
    v = ok(c.post(f"/api/v1/receipts/{a['id']}/void", json={"reason": "doppelt erfasst"}))
    assert v["voided_at"] and v["void_reason"] == "doppelt erfasst"
    assert ok(c.get("/api/v1/receipts"))["items"] == []
    assert [x["id"] for x in ok(c.get("/api/v1/receipts?voided=true"))["items"]] == [a["id"]]
    assert c.patch(f"/api/v1/receipts/{a['id']}", json={"amount_minor": 1}).status_code == 409
    assert c.post(f"/api/v1/receipts/{a['id']}/void", json={"reason": "nochmal"}).status_code == 409
    rid = db(engines, "SELECT id FROM objects WHERE public_id = %s", (a["id"],))[0][0]
    with pytest.raises(DBAPIError, match="unveränderlich"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE receipts SET amount_minor = 1 WHERE id = :i"), {"i": rid})
    with pytest.raises(Exception, match="nicht gelöscht"):
        db(engines, "DELETE FROM receipts WHERE id = %s", (rid,))      # auch als Superuser


def test_rechte_sichtbereich_isolation(cw: CoreWorld, engines: Engines) -> None:
    admin = cw.client(cw.admin_a)
    a = _ausgabe(admin)
    assert cw.client(cw.mitarbeiter).post("/api/v1/receipts", json={"title": "x", "amount_minor": 1}).status_code == 403
    assert ok(cw.client(cw.mitarbeiter).get(f"/api/v1/receipts/{a['id']}"))["amount_minor"] == 4999
    stb = cw.client(cw.stb)                                   # finance.read ohne read_all
    assert stb.get(f"/api/v1/receipts/{a['id']}").status_code == 404
    ok(admin.post(f"/api/v1/objects/{a['id']}/grants", json={"member": cw.public_id(cw.stb)}), 201)
    assert ok(stb.get("/api/v1/receipts"))["items"][0]["id"] == a["id"]
    assert cw.client(cw.ohne).get("/api/v1/receipts").status_code == 403
    fremd = ok(cw.client(cw.admin_b).post("/api/v1/documents?filename=b.pdf", **PDF), 201)
    assert admin.put(f"/api/v1/receipts/{a['id']}/document", json={"document": fremd["id"]}).status_code == 404
    with tenant_transaction(engines.app, cw.b) as s:
        assert s.execute(text("SELECT count(*) FROM receipts")).scalar_one() == 0
    fremd_id = db(engines, "SELECT id FROM objects WHERE public_id = %s", (fremd["id"],))[0][0]
    with pytest.raises(DBAPIError), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE receipts SET document_id = :d"), {"d": fremd_id})
