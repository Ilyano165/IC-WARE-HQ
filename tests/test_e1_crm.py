"""E1 CRM (ADR-020): Kunden, Kontaktpersonen, Dubletten, Zusammenführen, Anfragen, Archivieren, Rechte, Isolation."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.objects.service import create_object
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def _kunde(c, name: str = "Müller GmbH", **extra):  # type: ignore[no-untyped-def]
    return ok(c.post("/api/v1/customers", json={"name": name, **extra}), 201)


def test_kunde_anlegen_lesen_aendern_suchen_archivieren(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    k = _kunde(c, email="info@mueller.test", city="Köln", country="DE", status="lead",
               owner=cw.public_id(cw.mitarbeiter), notes="Kennt uns von der Messe")
    assert (k["status"], k["city"], k["owner"]["display_name"], k["notes"]) == (
        "lead", "Köln", "Max Mitarbeiter", "Kennt uns von der Messe")
    g = ok(c.get(f"/api/v1/customers/{k['id']}"))
    assert g["email"] == "info@mueller.test" and g["contacts"] == []
    p = ok(c.patch(f"/api/v1/customers/{k['id']}", json={"status": "active", "phone": "  0221 1234 ", "owner": None}))
    assert (p["status"], p["phone"], p["owner"]) == ("active", "0221 1234", None)
    assert [x["id"] for x in ok(c.get("/api/v1/customers?q=köln"))["items"]] == [k["id"]]
    assert ok(c.get("/api/v1/customers?status=lead"))["items"] == []
    # Archivieren: aus der Standardliste, im Archiv sichtbar, wiederherstellbar — nichts gelöscht
    ok(c.post(f"/api/v1/objects/{k['id']}/archive"))
    assert ok(c.get("/api/v1/customers"))["items"] == []
    assert [x["id"] for x in ok(c.get("/api/v1/customers?archived=true"))["items"]] == [k["id"]]
    assert ok(c.post(f"/api/v1/objects/{k['id']}/restore"))["archived"] is False
    assert len(ok(c.get("/api/v1/customers"))["items"]) == 1
    verben = [a["verb"] for a in ok(c.get(f"/api/v1/objects/{k['id']}/activities"))["items"]]
    assert {"customer.created", "customer.updated", "object.archived", "object.restored"} <= set(verben)


def test_ungueltige_eingaben(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    for body in ({"name": ""}, {"name": "X", "email": "keine-mail"}, {"name": "X", "country": "deu"},
                 {"name": "X", "status": "vip"}, {"name": "X", "unbekannt": 1}):
        assert c.post("/api/v1/customers", json=body).status_code == 422, body
    k = _kunde(c)
    assert c.patch(f"/api/v1/customers/{k['id']}", json={"name": None}).status_code == 422
    assert c.patch(f"/api/v1/customers/{k['id']}", json={}).status_code == 422


def test_dublette_wird_erkannt_und_nur_bewusst_angelegt(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    erster = _kunde(c, "Müller GmbH & Co. KG", email="kontakt@mueller.test")
    for name, mail in (("mueller", None), ("Anders AG", "KONTAKT@mueller.test")):
        r = c.post("/api/v1/customers", json={"name": name, "email": mail} if mail else {"name": name})
        assert r.status_code == 409 and "Müller GmbH" in r.json()["detail"], r.text
        treffer = ok(c.get("/api/v1/customers/duplicates", params={"name": name, "email": mail or ""}))["items"]
        assert [t["id"] for t in treffer] == [erster["id"]]
    zweiter = _kunde(c, "Mueller", allow_duplicate=True)
    assert zweiter["id"] != erster["id"]
    assert ok(c.get("/api/v1/customers/duplicates?name=Schmidt"))["items"] == []
    events = db(cw.engines, "SELECT data->>'duplicate_confirmed' FROM audit_events WHERE action = 'customer.created' "
                            "ORDER BY occurred_at")
    assert [e[0] for e in events] == ["false", "true"]


def test_kontaktpersonen_mit_einem_hauptkontakt(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    k = _kunde(c)
    a = ok(c.post(f"/api/v1/customers/{k['id']}/contacts", json={"name": "Anna", "is_primary": True}), 201)
    b = ok(c.post(f"/api/v1/customers/{k['id']}/contacts", json={"name": "Bernd", "role": "Einkauf",
                                                                 "email": "b@mueller.test"}), 201)
    ok(c.patch(f"/api/v1/customers/{k['id']}/contacts/{b['id']}", json={"is_primary": True}))
    kontakte = ok(c.get(f"/api/v1/customers/{k['id']}"))["contacts"]
    assert [(x["name"], x["is_primary"]) for x in kontakte] == [("Bernd", True), ("Anna", False)]
    # Kontakt eines ANDEREN Kunden über diesen Kunden: nicht erreichbar
    anderer = _kunde(c, "Andere GmbH")
    assert c.patch(f"/api/v1/customers/{anderer['id']}/contacts/{a['id']}", json={"name": "X"}).status_code == 404
    assert c.delete(f"/api/v1/customers/{k['id']}/contacts/{a['id']}").status_code == 204
    assert [x["name"] for x in ok(c.get(f"/api/v1/customers/{k['id']}"))["contacts"]] == ["Bernd"]


def test_zusammenfuehren_verschiebt_verweise_und_archiviert_dublette(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    bleibt = _kunde(c, "Müller GmbH")
    weg = _kunde(c, "Mueller", allow_duplicate=True)
    ok(c.post(f"/api/v1/customers/{weg['id']}/contacts", json={"name": "Clara"}), 201)
    anfrage = ok(c.post("/api/v1/inquiries", json={"title": "Angebot Dach", "customer": weg["id"]}), 201)
    assert c.post(f"/api/v1/customers/{weg['id']}/merge", json={"into": weg["id"]}).status_code == 422
    assert cw.client(cw.mitarbeiter).post(f"/api/v1/customers/{weg['id']}/merge",
                                          json={"into": bleibt["id"]}).status_code == 403
    ziel = ok(c.post(f"/api/v1/customers/{weg['id']}/merge", json={"into": bleibt["id"]}))
    assert [x["name"] for x in ziel["contacts"]] == ["Clara"]
    assert ok(c.get(f"/api/v1/inquiries/{anfrage['id']}"))["customer"]["id"] == bleibt["id"]
    alt = ok(c.get(f"/api/v1/customers/{weg['id']}"))
    assert alt["archived"] is True and alt["merged_into"]["id"] == bleibt["id"]
    assert [x["id"] for x in ok(c.get("/api/v1/customers"))["items"]] == [bleibt["id"]]
    daten = db(cw.engines, "SELECT data FROM audit_events WHERE action = 'customer.merged'")[0][0]
    assert daten["moved"] == {"customer_contacts": 1, "inquiries": 1}
    # Archivierte Dublette nicht erneut zusammenführen
    assert c.post(f"/api/v1/customers/{weg['id']}/merge", json={"into": bleibt["id"]}).status_code == 409


def test_anfragen_status_wiedervorlage_und_sichtbarer_kunde(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    kunde = _kunde(c)
    a = ok(c.post("/api/v1/inquiries", json={"title": "Wartungsvertrag", "source": "phone", "priority": "high",
                                             "customer": kunde["id"], "owner": cw.public_id(cw.admin_a),
                                             "next_action": "Rückruf", "follow_up_on": "2026-10-01"}), 201)
    b = ok(c.post("/api/v1/inquiries", json={"title": "Später", "follow_up_on": "2099-01-01"}), 201)
    assert a["status"] == "new" and a["received_on"]                 # Eingang = heute (Firmenzeitzone)
    faellig = ok(c.get("/api/v1/inquiries?follow_up_before=2026-10-12&owner=me"))["items"]
    assert [x["id"] for x in faellig] == [a["id"]]
    gewonnen = ok(c.patch(f"/api/v1/inquiries/{a['id']}", json={"status": "won"}))
    assert gewonnen["closed_at"] is not None
    assert ok(c.get("/api/v1/inquiries?follow_up_before=2026-10-12"))["items"] == []   # erledigt ⇒ keine Wiedervorlage
    wieder = ok(c.patch(f"/api/v1/inquiries/{a['id']}", json={"status": "in_progress"}))
    assert wieder["closed_at"] is None
    assert [x["id"] for x in ok(c.get(f"/api/v1/inquiries?customer={kunde['id']}"))["items"]] == [a["id"]]
    assert b["customer"] is None
    verben = [x["verb"] for x in ok(c.get(f"/api/v1/objects/{a['id']}/activities"))["items"]]
    assert verben.count("inquiry.status_changed") == 2
    # Fremder Kunde als Bezug: 404 (nicht anlegbar)
    fremd = _kunde(cw.client(cw.admin_b), "Beta Kunde")
    assert c.post("/api/v1/inquiries", json={"title": "x", "customer": fremd["id"]}).status_code == 404


def test_rechte_und_sichtbereich(cw: CoreWorld) -> None:
    admin, ma = cw.client(cw.admin_a), cw.client(cw.mitarbeiter)
    k = _kunde(admin)
    # Mitarbeiter: customers.read (+ read_all) ⇒ sieht, darf aber nicht anlegen/ändern
    assert ok(ma.get(f"/api/v1/customers/{k['id']}"))["name"] == "Müller GmbH"
    assert ma.post("/api/v1/customers", json={"name": "X"}).status_code == 403
    assert ma.patch(f"/api/v1/customers/{k['id']}", json={"name": "X"}).status_code == 403
    assert ma.post(f"/api/v1/objects/{k['id']}/archive").status_code == 403
    # Steuerberater ohne customers.read: Liste 403, Objekt unsichtbar (404)
    stb = cw.client(cw.stb)
    assert stb.get("/api/v1/customers").status_code == 403
    assert stb.get(f"/api/v1/objects/{k['id']}").status_code == 404
    assert cw.client(cw.ohne).get("/api/v1/inquiries").status_code == 403


def test_isolation_in_der_datenbank(cw: CoreWorld, engines: Engines) -> None:
    """RLS + zusammengesetzte Fremdschlüssel: auch ohne Service keine Verweise über Firmengrenzen."""
    kb = _kunde(cw.client(cw.admin_b), "Beta GmbH")
    kb_id = db(engines, "SELECT id FROM objects WHERE public_id = %s", (kb["id"],))[0][0]
    with tenant_transaction(engines.app, cw.a) as s:
        assert s.execute(text("SELECT count(*) FROM customers")).scalar_one() == 0
        assert s.execute(text("UPDATE customers SET notes = 'x' WHERE id = :i"), {"i": kb_id}).rowcount == 0
    with pytest.raises(IntegrityError), tenant_transaction(engines.app, cw.a) as s:
        o = create_object(s, type_="inquiry", title="Fremdbezug", actor_membership_id=None)
        s.execute(text("INSERT INTO inquiries(id, tenant_id, received_on, customer_id) "
                       "VALUES (:i, :t, current_date, :k)"), {"i": o.id, "t": cw.a, "k": kb_id})
    with pytest.raises(IntegrityError), tenant_transaction(engines.app, cw.a) as s:   # Fachzeile ohne Objekt
        s.execute(text("INSERT INTO customers(id, tenant_id, dedup_key) VALUES (:i, :t, 'x')"),
                  {"i": uuid.uuid4(), "t": cw.a})


def test_audit_ohne_freitexte(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    k = _kunde(c, notes="GEHEIMNOTIZ")
    ok(c.patch(f"/api/v1/customers/{k['id']}", json={"notes": "NOCH GEHEIMER"}))
    ok(c.post("/api/v1/inquiries", json={"title": "A", "description": "VERTRAULICH"}), 201)
    alles = str(db(cw.engines, "SELECT data FROM audit_events")) + str(db(cw.engines, "SELECT data FROM activities"))
    assert "GEHEIM" not in alles and "VERTRAULICH" not in alles


def test_sichtbereich_ohne_read_all_nur_eigenes_und_freigegebenes(cw: CoreWorld) -> None:
    """Vertrieb ohne objects.read_all: sieht eigene Kunden/Anfragen und Freigegebenes — einen Kunden hinter einer
    freigegebenen Anfrage aber NICHT automatisch (keine Daten über den Umweg einer Verknüpfung)."""
    vertrieb = cw._mitglied(cw.a, "vertrieb@alpha.test", "Vera Vertrieb", ["customers.read", "customers.create"])
    admin, v = cw.client(cw.admin_a), cw.client(vertrieb)
    fremd = _kunde(admin, "Chef-Kunde AG")
    anfrage = ok(admin.post("/api/v1/inquiries", json={"title": "Chef-Anfrage", "customer": fremd["id"]}), 201)
    eigen = _kunde(v, "Eigene Kundin")
    assert [x["id"] for x in ok(v.get("/api/v1/customers"))["items"]] == [eigen["id"]]
    assert v.get(f"/api/v1/customers/{fremd['id']}").status_code == 404
    assert v.get(f"/api/v1/inquiries/{anfrage['id']}").status_code == 404
    ok(admin.post(f"/api/v1/objects/{anfrage['id']}/grants", json={"member": cw.public_id(vertrieb)}), 201)
    sichtbar = ok(v.get(f"/api/v1/inquiries/{anfrage['id']}"))
    assert sichtbar["title"] == "Chef-Anfrage" and sichtbar["customer"] is None
    assert "Chef-Kunde" not in str(ok(v.get("/api/v1/inquiries")))
