"""ADR-021 Unternehmensverwaltung: Ersteinrichtung mit einmaligem Code, Firmen in der Oberfläche anlegen und
verwalten, Betreiber. Erwartungen ausgeschrieben; echte Anmeldung über die API (kein Principal-Ersatz)."""
from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ichq.api.security import iter_api_routes
from ichq.app import create_app
from ichq.auth import account
from ichq.control import service as control
from ichq.control.onboarding import slug_vorschlag
from ichq.core.config import Settings
from ichq.core.errors import Conflict
from ichq.db.engine import Engines
from ichq.db.session import auth_transaction, platform_transaction, tenant_transaction
from tests.auth_helpers import PASSWORT, db, login, make_user
from tests.auth_helpers import client as auth_client
from tests.conftest import World
from tests.core_helpers import ok

FIRMA = {"name": "IC Ware GbR", "slug": "ic-ware-gbr", "legal_name": "IC Ware GbR", "timezone": "Europe/Berlin",
         "language": "de", "currency": "EUR"}
STARK = "Regen-Lampe-Fenster-42"


def _code(engines: Engines) -> str:
    with platform_transaction(engines.platform) as s:
        return control.new_setup_code(s, actor="test")


def _einrichten(c: Any, engines: Engines, mail: str = "chef@ic-ware.test") -> None:
    ok(c.post("/api/v1/setup", json={"code": _code(engines), "email": mail, "name": "Chef", "password": STARK,
                                     "company": FIRMA}), 201)
    ok(login(c, mail, STARK))


def test_slug_vorschlag() -> None:
    assert slug_vorschlag("Müller & Söhne GmbH") == "mueller-soehne-gmbh"
    assert slug_vorschlag("  Straße 7 ") == "strasse-7"
    assert slug_vorschlag("AB") == "ab-firma"
    assert len(slug_vorschlag("x" * 200)) == 48


def test_ersteinrichtung_mit_einmaligem_code(settings: Settings, engines: Engines) -> None:
    c, _ = auth_client(settings, engines)
    assert ok(c.get("/api/v1/setup")) == {"needed": True}
    daten = {"email": "Chef@IC-Ware.test", "name": "Chef", "password": STARK, "company": FIRMA}
    assert c.post("/api/v1/setup", json={**daten, "code": "falscher-code-123"}).status_code == 403
    assert db(engines, "SELECT count(*) FROM tenants")[0][0] == 0
    code = _code(engines)
    assert code not in str(db(engines, "SELECT code_hash FROM platform_setup_codes"))        # nur als Hash
    schwach = c.post("/api/v1/setup", json={**daten, "code": code, "password": "passwort123"})
    assert schwach.status_code == 422 and db(engines, "SELECT count(*) FROM users")[0][0] == 0
    kaputt = c.post("/api/v1/setup", json={**daten, "code": code, "company": {**FIRMA, "slug": "admin"}})
    assert kaputt.status_code == 422                                # Kürzel reserviert → Code bleibt gültig
    r = ok(c.post("/api/v1/setup", json={**daten, "code": code}), 201)
    assert (r["company"]["slug"], r["company"]["status"], r["login"]) == ("ic-ware-gbr", "active", "chef@ic-ware.test")
    assert ok(c.get("/api/v1/setup")) == {"needed": False}
    assert c.post("/api/v1/setup", json={**daten, "code": code, "email": "zwei@x.test",
                                         "company": {**FIRMA, "slug": "zweite"}}).status_code == 403   # verbraucht
    with pytest.raises(Conflict), platform_transaction(engines.platform) as s:
        control.new_setup_code(s, actor="test")                    # eingerichtet → kein neuer Code
    ok(login(c, "chef@ic-ware.test", STARK))
    sitzung = ok(c.get("/api/v1/auth/session"))
    assert sitzung["operator"] is True and [m["slug"] for m in sitzung["memberships"]] == ["ic-ware-gbr"]
    ok(c.post("/api/v1/auth/tenant", json={"tenant_id": sitzung["memberships"][0]["tenant_id"]}))
    rechte = set(ok(c.get("/api/v1/me"))["permissions"])
    assert {"users.create", "roles.assign", "invoices.create", "finance.approve"} <= rechte     # Company Admin
    rollen = {r["name"] for r in ok(c.get("/api/v1/roles"))["items"]}
    assert {"Company Admin", "Geschäftsführung", "Mitarbeiter", "Steuerberater"} <= rollen     # Vorlagen angelegt
    aktionen = {a[0] for a in db(engines, "SELECT action FROM platform_audit_events")}
    assert {"setup.code_issued", "operator.added", "tenant.created", "tenant.status_changed"} <= aktionen


def test_abgelaufener_code_gilt_nicht(settings: Settings, engines: Engines) -> None:
    c, _ = auth_client(settings, engines)
    code = _code(engines)
    db(engines, "UPDATE platform_setup_codes SET expires_at = now() - interval '1 minute'")
    assert c.post("/api/v1/setup", json={"code": code, "email": "a@b.test", "name": "A", "password": STARK,
                                         "company": FIRMA}).status_code == 403
    alt = _code(engines)
    neu = _code(engines)                                           # neuer Code entwertet den alten
    assert c.post("/api/v1/setup", json={"code": alt, "email": "a@b.test", "name": "A", "password": STARK,
                                         "company": FIRMA}).status_code == 403
    ok(c.post("/api/v1/setup", json={"code": neu, "email": "a@b.test", "name": "A", "password": STARK,
                                     "company": FIRMA}), 201)


def test_firmen_anlegen_und_verwalten(settings: Settings, engines: Engines) -> None:
    c, _ = auth_client(settings, engines)
    _einrichten(c, engines)
    assert ok(c.get("/api/v1/platform/slug-suggestion?name=IC Ware GbR"))["slug"] == "ic-ware-gbr-2"   # belegt
    assert ok(c.get("/api/v1/platform/slug-suggestion?name=Dach Müller"))["slug"] == "dach-mueller"
    # 1) ich selbst als Admin, ein Modul abgewählt
    a = ok(c.post("/api/v1/platform/companies", json={
        "company": {"name": "Dach Müller", "slug": "dach-mueller", "modules_off": ["travel"]},
        "admin": {"mode": "self"}}), 201)
    assert (a["status"], a["members"], [x["email"] for x in a["admins"]]) == ("active", 1, ["chef@ic-ware.test"])
    assert c.post("/api/v1/platform/companies", json={"company": {"name": "x", "slug": "dach-mueller"},
                                                      "admin": {"mode": "self"}}).status_code == 409
    # 2) neues Konto: schwaches Passwort legt NICHTS an
    neu = {"company": {"name": "Maler Weiß", "slug": "maler-weiss"},
           "admin": {"mode": "new", "email": "inh@maler.test", "name": "Inhaberin", "password": "kurz"}}
    assert c.post("/api/v1/platform/companies", json=neu).status_code == 422
    assert db(engines, "SELECT count(*) FROM tenants WHERE slug = 'maler-weiss'")[0][0] == 0
    assert db(engines, "SELECT count(*) FROM users WHERE email = 'inh@maler.test'")[0][0] == 0
    neu["admin"]["password"] = PASSWORT
    ok(c.post("/api/v1/platform/companies", json=neu), 201)
    assert c.post("/api/v1/platform/companies", json={**neu, "company": {"name": "y", "slug": "noch-eine"}}
                  ).status_code == 409                              # Konto existiert → „bestehendes Konto“
    m, _ = auth_client(settings, engines)
    ok(login(m, "inh@maler.test"))
    ms = ok(m.get("/api/v1/auth/session"))
    assert ms["operator"] is False and [x["slug"] for x in ms["memberships"]] == ["maler-weiss"]
    # 3) bestehendes Konto
    assert c.post("/api/v1/platform/companies", json={"company": {"name": "z", "slug": "zett-gmbh"}, "admin": {
        "mode": "existing", "email": "gibts@nicht.test"}}).status_code == 404
    ok(c.post("/api/v1/platform/companies", json={"company": {"name": "Zett", "slug": "zett-gmbh"}, "admin": {
        "mode": "existing", "email": "inh@maler.test"}}), 201)
    liste = ok(c.get("/api/v1/platform/companies"))
    assert [x["slug"] for x in liste["items"]] == ["dach-mueller", "ic-ware-gbr", "maler-weiss", "zett-gmbh"]
    assert liste["counts"] == {"active": 4}
    assert [x["slug"] for x in ok(c.get("/api/v1/platform/companies?q=maler"))["items"]] == ["maler-weiss"]
    # Detail, Bearbeiten, Module
    d = ok(c.get("/api/v1/platform/companies/dach-mueller"))
    assert {x["module"]: x["enabled"] for x in d["modules"]}["travel"] is False
    assert {x["module"]: x["enabled"] for x in d["modules"]}["invoices"] is True
    g = ok(c.patch("/api/v1/platform/companies/dach-mueller", json={"legal_name": "Dach Müller GmbH",
                                                                    "currency": "CHF"}))
    assert (g["legal_name"], g["currency"], g["slug"]) == ("Dach Müller GmbH", "CHF", "dach-mueller")
    assert c.patch("/api/v1/platform/companies/dach-mueller", json={"timezone": "Mond/Krater"}).status_code == 422
    assert c.patch("/api/v1/platform/companies/dach-mueller", json={"slug": "anders"}).status_code == 422
    ok(c.put("/api/v1/platform/companies/dach-mueller/modules/travel", json={"enabled": True, "reason": "gebucht"}))
    assert c.put("/api/v1/platform/companies/dach-mueller/modules/roles",
                 json={"enabled": False, "reason": "Kernmodul"}).status_code == 422
    # Status: nur mit Begründung, nur erlaubte Übergänge, deaktiviert ist endgültig
    assert c.post("/api/v1/platform/companies/zett-gmbh/status", json={"status": "paused"}).status_code == 422
    p = ok(c.post("/api/v1/platform/companies/zett-gmbh/status", json={"status": "paused", "reason": "Zahlung offen"}))
    assert (p["status"], p["next_status"]) == ("paused", ["active", "deactivated", "suspended"])
    ok(c.post("/api/v1/platform/companies/zett-gmbh/status", json={"status": "deactivated", "reason": "gekündigt"}))
    assert c.post("/api/v1/platform/companies/zett-gmbh/status",
                  json={"status": "active", "reason": "doch wieder"}).status_code == 409
    assert c.post("/api/v1/platform/companies/zett-gmbh/admins", json={"email": "chef@ic-ware.test"}).status_code == 409
    # weiteren Admin zuweisen
    r = ok(c.post("/api/v1/platform/companies/maler-weiss/admins", json={"email": "chef@ic-ware.test"}), 201)
    assert r["assigned"] is True and [x["email"] for x in r["admins"]] == ["chef@ic-ware.test", "inh@maler.test"]
    verlauf = [h["action"] for h in ok(c.get("/api/v1/platform/companies/maler-weiss"))["history"]]
    assert "tenant.admin_assigned" in verlauf and "tenant.created" in verlauf
    assert c.get("/api/v1/platform/companies/gibt-es-nicht").status_code == 404


def test_nur_betreiber_und_keine_rechte_in_fremden_firmen(settings: Settings, engines: Engines, world: World) -> None:
    c, _ = auth_client(settings, engines)
    make_user(engines, settings, "betreiber@ic-ware.test")
    db(engines, "UPDATE users SET status = 'active' WHERE email = 'betreiber@ic-ware.test'")
    with platform_transaction(engines.platform) as s:
        control.add_operator(s, control.user_by_email(s, "betreiber@ic-ware.test").id, actor="test")
    app = create_app(settings, engines=engines)
    routen = [(m, p) for p, ms, _ in iter_api_routes(app) if p.startswith("/api/v1/platform") for m in ms - {"HEAD"}]
    assert len(routen) >= 12
    with auth_transaction(engines.auth) as s:                       # Anna (Firma Alpha) bekommt ein Passwort
        assert account.set_initial_password(s, settings, world.user_a, PASSWORT, actor="test").ok
        assert account.set_status(s, world.user_a, "active", actor="test", reason="test").ok
    anna, _ = auth_client(settings, engines)
    ok(login(anna, "anna@alpha.test"))
    for wer, erwartet in ((c, 401), (anna, 403)):                   # ohne Anmeldung / angemeldet, aber kein Betreiber
        for methode, pfad in routen:
            url = pfad.replace("{slug}", "alpha").replace("{module}", "travel")
            assert wer.request(methode, url, json={}).status_code == erwartet, (methode, pfad)
    assert db(engines, "SELECT status FROM tenants WHERE slug = 'alpha'")[0][0] == "active"
    # Betreiber: verwaltet Firmen, hat aber IN der fremden Firma keine Rechte (keine Mitgliedschaft)
    ok(login(c, "betreiber@ic-ware.test"))
    assert ok(c.get("/api/v1/platform/companies/alpha"))["members"] == 1
    assert ok(c.get("/api/v1/auth/session"))["memberships"] == []
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": str(world.a.id)}).status_code == 403
    assert c.get("/api/v1/customers").status_code == 403
    # Datenbank: Mandanten-Rolle sieht die Betreibertabellen nicht
    for tabelle in ("platform_operators", "platform_setup_codes"):
        with pytest.raises(DBAPIError, match="permission denied"), tenant_transaction(engines.app, world.a.id) as s:
            s.execute(text(f"SELECT count(*) FROM {tabelle}"))


def test_betreiber_verwalten(settings: Settings, engines: Engines) -> None:
    c, _ = auth_client(settings, engines)
    _einrichten(c, engines)
    assert c.post("/api/v1/platform/operators/remove", json={"email": "chef@ic-ware.test"}).status_code == 409
    assert c.post("/api/v1/platform/operators", json={"email": "fremd@x.test"}).status_code == 404
    make_user(engines, settings, "zwei@ic-ware.test")
    db(engines, "UPDATE users SET status = 'active' WHERE email = 'zwei@ic-ware.test'")
    assert ok(c.post("/api/v1/platform/operators", json={"email": "zwei@ic-ware.test"}), 201)["added"] is True
    assert ok(c.post("/api/v1/platform/operators", json={"email": "zwei@ic-ware.test"}), 201)["added"] is False
    z, _ = auth_client(settings, engines)
    ok(login(z, "zwei@ic-ware.test"))
    assert [(o["email"], o["me"]) for o in ok(z.get("/api/v1/platform/operators"))["items"]] == [
        ("chef@ic-ware.test", False), ("zwei@ic-ware.test", True)]
    ok(c.post("/api/v1/platform/operators/remove", json={"email": "zwei@ic-ware.test"}))
    assert z.get("/api/v1/platform/companies").status_code == 403           # wirkt sofort, ohne neue Anmeldung
