"""E3 Rechnungen (ADR-020): Rundung, Ausstellen mit lückenlosem Nummernkreis (auch parallel), Unveränderbarkeit in
der Datenbank, Storno, Zahlungen mit Rücknahme, Überfälligkeit, Mahnhistorie ohne Versand, Rechte, Isolation."""
from __future__ import annotations

import threading
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.finance import invoices as svc
from ichq.finance.rechnen import runde_div, summe, zeile
from ichq.tenancy.service import company_today
from tests.auth_helpers import db
from tests.conftest import World
from tests.core_helpers import CoreWorld, ok

POS = {"description": "Dachdeckerarbeiten", "quantity_milli": 3000, "unit": "Std", "unit_price_minor": 3333,
       "tax_rate_bp": 1900}


@pytest.fixture
def cw(world: World, engines: Engines, settings: Settings) -> CoreWorld:
    return CoreWorld(world, engines, settings)


def test_rundung_kaufmaennisch_je_position() -> None:
    assert [runde_div(x, 100) for x in (149, 150, 151, -149, -150, -151)] == [1, 2, 2, -1, -2, -2]
    z = zeile(3000, 3333, 1900)                     # 3 × 33,33 = 99,99; 19 % = 18,9981 → 19,00
    assert (z.net_minor, z.tax_minor) == (9999, 1900)
    assert (zeile(1500, 999, 700).net_minor, zeile(1500, 999, 700).tax_minor) == (1499, 105)   # 14,985 → 14,99
    assert zeile(-3000, 3333, 1900).tax_minor == -1900                                         # Storno spiegelbildlich
    s = summe([(1900, zeile(1000, 10000, 1900)), (700, zeile(2000, 500, 700)), (1900, zeile(1000, 1, 1900))])
    assert (s.net_minor, s.tax_minor, s.gross_minor) == (11001, 1970, 12971)
    assert s.tax_by_rate == {700: (1000, 70), 1900: (10001, 1900)}
    with pytest.raises(ValueError):
        zeile(1000, 100, 10001)


def _entwurf(c: Any, kunde: str | None = None, **extra: Any) -> dict[str, Any]:
    if kunde is None:
        kunde = ok(c.post("/api/v1/customers", json={"name": "Bauherr GmbH", "street": "Hauptstr. 1",
                                                     "postal_code": "50667", "city": "Köln", "allow_duplicate": True}),
                   201)["id"]
    r = ok(c.post("/api/v1/invoices", json={"customer": kunde, **extra}), 201)
    ok(c.post(f"/api/v1/invoices/{r['id']}/lines", json=POS), 201)
    return ok(c.get(f"/api/v1/invoices/{r['id']}"))


def _ausstellen(c: Any, ref: str, due: str = "2099-12-31") -> dict[str, Any]:
    return ok(c.post(f"/api/v1/invoices/{ref}/issue", json={"due_date": due}))


def test_entwurf_positionen_ausstellen_nummern(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    e = _entwurf(c)
    assert (e["status"], e["number"], e["gross_minor"]) == ("draft", None, 11899)
    zweite = ok(c.post(f"/api/v1/invoices/{e['id']}/lines", json={**POS, "description": "Material",
                                                                    "quantity_milli": 1000, "unit_price_minor": 5000,
                                                                    "tax_rate_bp": 700}), 201)
    ok(c.patch(f"/api/v1/invoices/{e['id']}/lines/{zweite['id']}", json={"unit_price_minor": 6000}))
    e = ok(c.get(f"/api/v1/invoices/{e['id']}"))
    assert (e["net_minor"], e["tax_minor"], e["gross_minor"]) == (15999, 2320, 18319)
    assert [x["tax_rate_bp"] for x in e["tax_by_rate"]] == [700, 1900]
    a = _ausstellen(c, e["id"])
    jahr = a["issue_date"][:4]
    assert (a["status"], a["number"], a["title"]) == ("issued", f"RE-{jahr}-00001", f"Rechnung RE-{jahr}-00001")
    assert a["customer_snapshot"]["city"] == "Köln" and a["open_minor"] == 18319
    b = _ausstellen(c, _entwurf(c)["id"])
    assert b["number"] == f"RE-{jahr}-00002"
    # Kundenstand bleibt eingefroren, auch wenn der Kunde umzieht
    ok(c.patch(f"/api/v1/customers/{a['customer']['id']}", json={"city": "Bonn"}))
    assert ok(c.get(f"/api/v1/invoices/{a['id']}"))["customer_snapshot"]["city"] == "Köln"


def test_ausstellen_nur_vollstaendig(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    ohne_kunde = ok(c.post("/api/v1/invoices", json={}), 201)
    ok(c.post(f"/api/v1/invoices/{ohne_kunde['id']}/lines", json=POS), 201)
    assert c.post(f"/api/v1/invoices/{ohne_kunde['id']}/issue", json={"due_date": "2099-01-01"}).status_code == 422
    kunde = ok(c.post("/api/v1/customers", json={"name": "K"}), 201)["id"]
    ohne_pos = ok(c.post("/api/v1/invoices", json={"customer": kunde}), 201)
    assert c.post(f"/api/v1/invoices/{ohne_pos['id']}/issue", json={"due_date": "2099-01-01"}).status_code == 422
    e = _entwurf(c, kunde)
    assert c.post(f"/api/v1/invoices/{e['id']}/issue", json={}).status_code == 422          # Fälligkeit fehlt
    assert c.post(f"/api/v1/invoices/{e['id']}/issue", json={"due_date": "2001-01-01"}).status_code == 422
    assert c.post(f"/api/v1/invoices/{e['id']}/lines", json={**POS, "tax_rate_bp": 10001}).status_code == 422
    assert c.post(f"/api/v1/invoices/{e['id']}/lines", json={**POS, "quantity_milli": 0}).status_code == 422


def test_ausgestellt_ist_unveraenderlich_auch_in_der_datenbank(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    a = _ausstellen(c, _entwurf(c)["id"])
    zeile_id = a["lines"][0]["id"]
    assert c.patch(f"/api/v1/invoices/{a['id']}", json={"notes": "nachträglich"}).status_code == 409
    assert c.post(f"/api/v1/invoices/{a['id']}/lines", json=POS).status_code == 409
    assert c.patch(f"/api/v1/invoices/{a['id']}/lines/{zeile_id}", json={"unit_price_minor": 1}).status_code == 409
    assert c.delete(f"/api/v1/invoices/{a['id']}/lines/{zeile_id}").status_code == 409
    assert c.post(f"/api/v1/invoices/{a['id']}/issue", json={"due_date": "2099-01-01"}).status_code == 409
    assert c.post(f"/api/v1/objects/{a['id']}/archive").status_code == 409
    # Zuständigkeit (Mahnwesen) bleibt änderbar
    assert ok(c.patch(f"/api/v1/invoices/{a['id']}", json={"responsible": cw.public_id(cw.admin_a)}))["responsible"]
    iid = db(engines, "SELECT id FROM objects WHERE public_id = %s", (a["id"],))[0][0]
    with pytest.raises(DBAPIError, match="kein Entwurf mehr"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("UPDATE invoices SET status = 'draft' WHERE id = :i"), {"i": iid})
    # Auch der Datenbank-Superuser (direkter Zugriff, nicht die App) kann eine ausgestellte Rechnung nicht löschen
    with pytest.raises(Exception, match="nicht gelöscht werden"):
        db(engines, "DELETE FROM invoices WHERE id = %s", (iid,))
    for sql in ("UPDATE invoices SET gross_minor = 1, net_minor = 1, tax_minor = 0 WHERE id = :i",
                "UPDATE invoices SET status = 'draft', number = NULL WHERE id = :i",
                "UPDATE invoices SET customer_snapshot = '{}'::jsonb WHERE id = :i",
                "UPDATE invoice_lines SET unit_price_minor = 1 WHERE invoice_id = :i",
                "DELETE FROM invoice_lines WHERE invoice_id = :i",
                "INSERT INTO invoice_lines(id, tenant_id, public_id, invoice_id, position, description, quantity_milli,"
                " unit_price_minor, tax_rate_bp, net_minor, tax_minor) VALUES (gen_random_uuid(), "
                "ichq_current_tenant(), replace(gen_random_uuid()::text, '-', ''), :i, 9, 'x', 1, 1, 0, 0, 0)",
                "DELETE FROM invoices WHERE id = :i"):
        with pytest.raises(DBAPIError, match=r"ichq:|permission denied"), tenant_transaction(engines.app, cw.a) as s:
            s.execute(text(sql), {"i": iid})
    assert ok(c.get(f"/api/v1/invoices/{a['id']}"))["gross_minor"] == 11899


def test_nummernkreis_parallel_lueckenlos(cw: CoreWorld, engines: Engines) -> None:
    """8 Entwürfe werden GLEICHZEITIG ausgestellt: jede Nummer genau einmal, ohne Lücke."""
    c = cw.client(cw.admin_a)
    kunde = ok(c.post("/api/v1/customers", json={"name": "Parallel AG"}), 201)["id"]
    refs = [_entwurf(c, kunde)["id"] for _ in range(8)]
    p = cw.principal(cw.admin_a)
    start, fehler, nummern = threading.Barrier(len(refs)), [], []

    def ausstellen(ref: str) -> None:
        try:
            with tenant_transaction(engines.app, cw.a) as s:
                heute = company_today(s)
                start.wait(timeout=20)
                inv, _ = svc.issue(s, p, ref, today=heute, due_date=heute.replace(year=2099))
                nummern.append(inv.number)
        except Exception as e:                                 # pragma: no cover — sonst stiller Fehlschlag
            fehler.append(repr(e))

    threads = [threading.Thread(target=ausstellen, args=(r,)) for r in refs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not fehler, fehler
    assert sorted(int(n.rsplit("-", 1)[1]) for n in nummern) == list(range(1, 9))


def test_zahlungen_teil_voll_ueberzahlung_ruecknahme(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    e = _entwurf(c)
    assert c.post(f"/api/v1/invoices/{e['id']}/payments", json={"amount_minor": 100,
                                                                "paid_on": "2026-10-01"}).status_code == 409
    a = _ausstellen(c, e["id"])
    heute = a["issue_date"]
    zahl = {"paid_on": heute, "method": "bank_transfer", "reference": "Überweisung 4711"}
    teil = ok(c.post(f"/api/v1/invoices/{a['id']}/payments", json={**zahl, "amount_minor": 5000}), 201)
    assert (teil["status"], teil["paid_minor"], teil["open_minor"]) == ("partially_paid", 5000, 6899)
    assert c.post(f"/api/v1/invoices/{a['id']}/payments", json={**zahl, "amount_minor": 6900}).status_code == 422
    assert c.post(f"/api/v1/invoices/{a['id']}/payments",
                  json={**zahl, "amount_minor": 1, "paid_on": "2099-01-01"}).status_code == 422
    voll = ok(c.post(f"/api/v1/invoices/{a['id']}/payments", json={**zahl, "amount_minor": 6899}), 201)
    assert (voll["status"], voll["open_minor"]) == ("paid", 0)
    zuletzt = voll["payments"][-1]["id"]
    zurueck = ok(c.post(f"/api/v1/invoices/{a['id']}/payments/{zuletzt}/reverse"), 201)
    assert (zurueck["status"], zurueck["open_minor"]) == ("partially_paid", 6899)
    assert [x["amount_minor"] for x in zurueck["payments"]] == [5000, 6899, -6899]   # nichts gelöscht
    assert c.post(f"/api/v1/invoices/{a['id']}/payments/{zuletzt}/reverse").status_code == 409
    rueck_id = zurueck["payments"][-1]["id"]
    assert c.post(f"/api/v1/invoices/{a['id']}/payments/{rueck_id}/reverse").status_code == 409
    # direkt in der DB: Zahlung auf Entwurf / falsche Rücknahme wird abgewiesen
    entwurf_id = db(engines, "SELECT id FROM objects WHERE public_id = %s", (_entwurf(c)["id"],))[0][0]
    with pytest.raises(DBAPIError, match="ichq:"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("INSERT INTO objects(id, tenant_id, type, public_id, title) VALUES (gen_random_uuid(), "
                       "ichq_current_tenant(), 'payment', replace(gen_random_uuid()::text,'-',''), 'x') RETURNING id"))
        pid = s.execute(text("SELECT id FROM objects WHERE type='payment' AND title='x'")).scalar_one()
        s.execute(text("INSERT INTO payments(id, tenant_id, invoice_id, paid_on, amount_minor, currency) "
                       "VALUES (:p, ichq_current_tenant(), :i, current_date, 100, 'EUR')"), {"p": pid, "i": entwurf_id})
    with pytest.raises(DBAPIError, match="permission denied"), tenant_transaction(engines.app, cw.a) as s:
        s.execute(text("DELETE FROM payments"))


def test_storno_erzeugt_gegenrechnung(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    a = _ausstellen(c, _entwurf(c)["id"])
    b = _ausstellen(c, _entwurf(c)["id"])
    ok(c.post(f"/api/v1/invoices/{b['id']}/payments", json={"amount_minor": 100, "paid_on": b["issue_date"]}), 201)
    assert c.post(f"/api/v1/invoices/{b['id']}/cancel").status_code == 409      # erst Zahlungen klären
    storno = ok(c.post(f"/api/v1/invoices/{a['id']}/cancel"))
    jahr = a["issue_date"][:4]
    assert (storno["kind"], storno["number"], storno["gross_minor"]) == ("cancellation", f"RE-{jahr}-00003", -11899)
    assert storno["cancels"]["id"] == a["id"] and storno["lines"][0]["quantity_milli"] == -3000
    original = ok(c.get(f"/api/v1/invoices/{a['id']}"))
    assert (original["status"], original["cancelled_by"]["id"], original["open_minor"]) == ("cancelled", storno["id"], 0)
    assert c.post(f"/api/v1/invoices/{a['id']}/cancel").status_code == 409
    assert c.post(f"/api/v1/invoices/{storno['id']}/cancel").status_code == 409
    offene = [x["id"] for x in ok(c.get("/api/v1/invoices?open=true"))["items"]]
    assert offene == [b["id"]]


def test_ueberfaellig_mahnhistorie_ohne_versand(cw: CoreWorld, engines: Engines) -> None:
    c = cw.client(cw.admin_a)
    a = _ausstellen(c, _entwurf(c)["id"])
    nicht = _ausstellen(c, _entwurf(c)["id"])
    assert ok(c.get("/api/v1/invoices?overdue=true"))["items"] == []
    # Zeitreise: Fälligkeit liegt 10 Tage zurück (nur im Test, Schutz-Trigger dafür abgeschaltet)
    db(engines, "SET session_replication_role = replica; "
                "UPDATE invoices SET issue_date = current_date - 30, due_date = current_date - 10 "
                f"WHERE id = (SELECT id FROM objects WHERE public_id = '{a['id']}')")
    ueber = ok(c.get("/api/v1/invoices?overdue=true&sort=due_date&order=asc"))["items"]
    assert [x["id"] for x in ueber] == [a["id"]] and ueber[0]["days_overdue"] >= 10 and ueber[0]["overdue"]
    assert nicht["overdue"] is False
    ok(c.post(f"/api/v1/invoices/{a['id']}/followups", json={"kind": "contact_attempt", "channel": "phone",
                                                             "note": "Buchhaltung nicht erreicht"}), 201)
    m = ok(c.post(f"/api/v1/invoices/{a['id']}/followups", json={"kind": "dunning_level", "dunning_level": 1,
                                                                 "next_follow_up": "2026-01-01"}), 201)
    assert (m["dunning_level"], len(m["followups"])) == (1, 2)
    assert [x["id"] for x in ok(c.get("/api/v1/invoices?follow_up_due=true"))["items"]] == [a["id"]]
    assert c.post(f"/api/v1/invoices/{a['id']}/followups", json={"kind": "dunning_level"}).status_code == 422
    assert db(engines, "SELECT count(*) FROM mail_outbox")[0][0] == 0             # nichts verschickt
    v = ok(c.post(f"/api/v1/invoices/{a['id']}/dispatches", json={"action": "sent", "channel": "email"}), 201)
    assert v["sent_at"] and v["status"] == "sent" and v["dispatches"][0]["channel"] == "email"
    # bezahlt ⇒ nicht mehr überfällig
    ok(c.post(f"/api/v1/invoices/{a['id']}/payments", json={"amount_minor": 11899, "paid_on": a["issue_date"]}), 201)
    assert ok(c.get("/api/v1/invoices?overdue=true"))["items"] == []


def test_rechte_sichtbereich_isolation(cw: CoreWorld, engines: Engines) -> None:
    admin = cw.client(cw.admin_a)
    a = _ausstellen(admin, _entwurf(admin)["id"])
    ma = cw.client(cw.mitarbeiter)                          # invoices.read + read_all, keine Schreibrechte
    assert ok(ma.get(f"/api/v1/invoices/{a['id']}"))["number"]
    assert ma.post("/api/v1/invoices", json={}).status_code == 403
    assert ma.post(f"/api/v1/invoices/{a['id']}/payments", json={"amount_minor": 1,
                                                                 "paid_on": a["issue_date"]}).status_code == 403
    stb = cw.client(cw.stb)                                 # invoices.read ohne read_all: nur Freigegebenes
    assert stb.get(f"/api/v1/invoices/{a['id']}").status_code == 404
    ok(admin.post(f"/api/v1/objects/{a['id']}/grants", json={"member": cw.public_id(cw.stb)}), 201)
    sicht = ok(stb.get(f"/api/v1/invoices/{a['id']}"))
    assert sicht["customer"] is None and sicht["customer_snapshot"]["name"] == "Bauherr GmbH"
    entwurf = _entwurf(admin)
    pl = cw._mitglied(cw.a, "fakt@alpha.test", "Fritz Faktura", ["invoices.read", "invoices.create",
                                                                  "invoices.update", "customers.read",
                                                                  "objects.read_all"])
    assert cw.client(pl).post(f"/api/v1/invoices/{entwurf['id']}/issue",
                              json={"due_date": "2099-01-01"}).status_code == 403   # Ausstellen = invoices.approve
    assert "payments" not in ok(cw.client(pl).get(f"/api/v1/invoices/{a['id']}"))     # Zahlungen = finance.read
    assert "payments" in ok(admin.get(f"/api/v1/invoices/{a['id']}"))
    kb = ok(cw.client(cw.admin_b).post("/api/v1/customers", json={"name": "Beta"}), 201)
    assert admin.post("/api/v1/invoices", json={"customer": kb["id"]}).status_code == 404
    with tenant_transaction(engines.app, cw.b) as s:
        assert s.execute(text("SELECT count(*) FROM invoices")).scalar_one() == 0
        assert s.execute(text("SELECT count(*) FROM invoice_lines")).scalar_one() == 0
    with pytest.raises(IntegrityError), tenant_transaction(engines.app, cw.a) as s:
        kb_id = db(engines, "SELECT id FROM objects WHERE public_id = %s", (kb["id"],))[0][0]
        s.execute(text("UPDATE invoices SET customer_id = :k WHERE status = 'draft'"), {"k": kb_id})


def test_kunde_mit_ausgestellter_rechnung_nicht_zusammenfuehrbar(cw: CoreWorld) -> None:
    c = cw.client(cw.admin_a)
    a = _ausstellen(c, _entwurf(c)["id"])
    bleibt = ok(c.post("/api/v1/customers", json={"name": "Andere GmbH"}), 201)
    r = c.post(f"/api/v1/customers/{a['customer']['id']}/merge", json={"into": bleibt["id"]})
    assert r.status_code == 409 and "geschützt" in r.json()["detail"]
    assert ok(c.get(f"/api/v1/invoices/{a['id']}"))["customer"]["id"] == a["customer"]["id"]
