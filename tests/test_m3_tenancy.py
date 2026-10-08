"""M3 Mandanten: Firmenprofil, zentraler Schreibschutz bei Pause, Mitglieder, Einladungen, Last-Admin.
Alles mit ECHTEN Sitzungen (Login → Firmenwahl), kein dependency_override."""
from __future__ import annotations

import re
import secrets
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ichq.authz.registry import PERMISSIONS
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.tenancy.service import set_status
from tests.auth_helpers import PASSWORT, client, db, join, login, make_user
from tests.conftest import World

ADMIN = sorted(PERMISSIONS)


def _sitzung(settings: Settings, engines: Engines, email: str, tid: uuid.UUID) -> tuple[TestClient, Any]:
    c, mailer = client(settings, engines)
    assert login(c, email).status_code == 200
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": str(tid)}).status_code == 200
    return c, mailer


def _mitglied(world: World, engines: Engines, settings: Settings, tid: uuid.UUID, email: str,
              perms: list[str]) -> uuid.UUID:
    uid = make_user(engines, settings, email)
    mid = join(engines, tid, uid)
    if perms:
        world.assign(tid, mid, world.role(tid, f"R-{email}", perms))
    return mid


def _pid(engines: Engines, mid: uuid.UUID) -> str:
    return str(db(engines, "SELECT public_id FROM memberships WHERE id = %s", (mid,))[0][0])


@pytest.fixture
def chef(world: World, engines: Engines, settings: Settings) -> tuple[TestClient, Any, uuid.UUID]:
    mid = _mitglied(world, engines, settings, world.a.id, "chef@alpha.test", ADMIN)
    c, mailer = _sitzung(settings, engines, "chef@alpha.test", world.a.id)
    return c, mailer, mid


def _token(mailer: Any) -> str:
    treffer = re.search(r"/invite#token=([A-Za-z0-9_-]+)", mailer.sent[-1][2])
    assert treffer, mailer.sent[-1][2]
    return treffer.group(1)


# ---------- Firmenprofil ----------
def test_firmenprofil_lesen_und_aendern_mit_audit(chef: Any, engines: Engines) -> None:
    c, _, _ = chef
    r = c.patch("/api/v1/company", json={"name": "Alpha Bau GmbH", "legal_name": "Alpha Bau GmbH & Co. KG",
                                         "timezone": "Europe/Vienna", "currency": "CHF"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Alpha Bau GmbH" and r.json()["slug"] == "alpha" and r.json()["currency"] == "CHF"
    daten = db(engines, "SELECT data FROM audit_events WHERE action = 'company.updated'")[0][0]
    assert daten["changes"]["name"] == {"from": "Alpha GmbH", "to": "Alpha Bau GmbH"}
    assert db(engines, "SELECT name FROM tenants WHERE slug = 'beta'")[0][0] == "Beta AG"   # B unberührt


@pytest.mark.parametrize("body", [{"timezone": "Mars/Olympus"}, {"language": "xx"}, {"currency": "eur"},
                                  {"name": ""}, {"slug": "neu"}, {"status": "active"}, {}, {"name": None}])
def test_firmenprofil_validierung(chef: Any, body: dict[str, Any]) -> None:
    r = chef[0].patch("/api/v1/company", json=body)
    assert r.status_code == 422, (body, r.text)


def test_firmenprofil_braucht_recht(world: World, engines: Engines, settings: Settings) -> None:
    _mitglied(world, engines, settings, world.a.id, "leser@alpha.test", ["company.read"])
    c, _ = _sitzung(settings, engines, "leser@alpha.test", world.a.id)
    assert c.get("/api/v1/company").status_code == 200
    r = c.patch("/api/v1/company", json={"name": "Gekapert"})
    assert r.status_code == 403 and "company.update" in r.json()["detail"]


def test_app_rolle_kann_nur_eigene_firma_und_nur_profilspalten_aendern(world: World, engines: Engines) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import ProgrammingError
    with tenant_transaction(engines.app, world.a.id) as s:
        assert s.execute(text("UPDATE tenants SET name = 'X' WHERE slug = 'beta'")).rowcount == 0  # type: ignore[attr-defined]
    for sql in ("UPDATE tenants SET status = 'active'", "UPDATE tenants SET slug = 'gekapert'",
                "UPDATE tenants SET plan_code = 'enterprise'"):
        with pytest.raises(ProgrammingError, match="permission denied"), tenant_transaction(engines.app, world.a.id) as s:
            s.execute(text(sql))


# ---------- Zentraler Schreibschutz ----------
def test_pausierte_firma_zentral_nur_lesen(chef: Any, world: World, engines: Engines) -> None:
    c, _, _ = chef
    with platform_transaction(engines.platform) as s:
        set_status(s, world.a.id, "paused", actor="test", reason="Zahlungsverzug")
    assert c.get("/api/v1/company").status_code == 200
    assert c.get("/api/v1/members").status_code == 200
    for m, pfad, body in (("PATCH", "/api/v1/company", {"name": "x"}), ("POST", "/api/v1/tasks", {"title": "x"}),
                          ("POST", "/api/v1/invitations", {"email": "a@b.test"}),
                          ("POST", "/api/v1/membership/leave", None),
                          ("POST", "/api/v1/notifications/read-all", None)):
        r = c.request(m, pfad, json=body)
        assert r.status_code == 403 and r.json()["code"] == "tenant_paused", (m, pfad, r.status_code, r.text)
    # Anmelde-Routen sind nicht betroffen
    assert c.post("/api/v1/auth/logout").status_code == 204


# ---------- Einladungen ----------
def test_einladung_neues_konto_ende_zu_ende(chef: Any, world: World, engines: Engines, settings: Settings) -> None:
    c, mailer, _ = chef
    r = c.post("/api/v1/invitations", json={"email": "  Neu@Extern.TEST ", "title": "Buchhaltung"})
    assert r.status_code == 201 and r.json()["email"] == "neu@extern.test"
    token = _token(mailer)
    mail = mailer.sent[-1][2]
    assert str(world.a.id) not in mail and "alpha" not in mail.lower() and "neu@extern.test" not in mail
    assert db(engines, "SELECT count(*) FROM invitations WHERE token_hash = sha256(%s::bytea)",
              (token.encode(),))[0][0] == 1
    assert token not in str(db(engines, "SELECT * FROM invitations")) + str(db(engines, "SELECT * FROM audit_events"))
    anon, _ = client(settings, engines)
    r = anon.post("/api/v1/invitations/accept", json={"token": token, "display_name": "Nina Neu",
                                                      "password": PASSWORT})
    assert r.status_code == 201, r.text
    # Wiederverwenden geht nicht
    r2 = anon.post("/api/v1/invitations/accept", json={"token": token, "display_name": "Zweit", "password": PASSWORT})
    assert r2.status_code == 400 and r2.json()["code"] == "invalid_token"
    neu, _ = _sitzung(settings, engines, "neu@extern.test", world.a.id)
    assert neu.get("/api/v1/me").json()["permissions"] == []           # Einladung gibt KEINE Rechte
    liste = c.get("/api/v1/members?status=active").json()["items"]
    assert {(m["display_name"], m["title"]) for m in liste} >= {("Nina Neu", "Buchhaltung")}
    assert c.get("/api/v1/invitations").json()["items"] == []        # nicht mehr offen


@pytest.mark.parametrize("fall", ["erraten", "abgelaufen", "widerrufen", "zu_kurz"])
def test_einladungstoken_missbrauch(fall: str, chef: Any, engines: Engines, settings: Settings) -> None:
    c, mailer, _ = chef
    inv = c.post("/api/v1/invitations", json={"email": "ziel@extern.test"}).json()
    token = _token(mailer)
    if fall == "erraten":
        token = secrets.token_urlsafe(32)
    elif fall == "abgelaufen":
        db(engines, "UPDATE invitations SET created_at = now() - interval '9 days', "
                    "expires_at = now() - interval '1 second'")
    elif fall == "widerrufen":
        assert c.delete(f"/api/v1/invitations/{inv['id']}").status_code == 204
    elif fall == "zu_kurz":
        token = "kurz"
    anon, _ = client(settings, engines)
    r = anon.post("/api/v1/invitations/accept", json={"token": token, "display_name": "X", "password": PASSWORT})
    assert r.status_code in (400, 422)
    if r.status_code == 400:
        assert r.json()["code"] == "invalid_token" and "ziel@" not in r.text
    assert db(engines, "SELECT count(*) FROM users WHERE email = 'ziel@extern.test'")[0][0] == 0


def test_bestehendes_konto_wird_nicht_ohne_zustimmung_verknuepft(chef: Any, world: World, engines: Engines,
                                                                 settings: Settings) -> None:
    c, mailer, _ = chef
    make_user(engines, settings, "bestand@beta.test")
    c.post("/api/v1/invitations", json={"email": "bestand@beta.test"})
    token = _token(mailer)
    anon, _ = client(settings, engines)
    r = anon.post("/api/v1/invitations/accept", json={"token": token, "display_name": "Fremd", "password": PASSWORT})
    assert r.status_code == 409 and r.json()["code"] == "account_exists"
    assert db(engines, "SELECT count(*) FROM memberships m JOIN users u ON u.id = m.user_id "
                       "WHERE u.email = 'bestand@beta.test'")[0][0] == 0
    # Ein ANDERES angemeldetes Konto kann die Einladung nicht für sich nutzen
    _mitglied(world, engines, settings, world.b.id, "dritter@beta.test", [])
    dritter, _ = client(settings, engines)
    login(dritter, "dritter@beta.test")
    r = dritter.post("/api/v1/invitations/accept-existing", json={"token": token})
    assert r.status_code == 403
    # Das richtige Konto stimmt zu, indem es angemeldet annimmt
    richtig, _ = client(settings, engines)
    login(richtig, "bestand@beta.test")
    assert richtig.post("/api/v1/invitations/accept-existing", json={"token": token}).status_code == 201
    assert richtig.post("/api/v1/auth/tenant", json={"tenant_id": str(world.a.id)}).status_code == 200


def test_einladung_regeln(chef: Any, engines: Engines) -> None:
    c, _, _mid = chef
    assert c.post("/api/v1/invitations", json={"email": "doppelt@x.test"}).status_code == 201
    assert c.post("/api/v1/invitations", json={"email": "DOPPELT@x.test"}).status_code == 409
    assert c.post("/api/v1/invitations", json={"email": "chef@alpha.test"}).status_code == 409   # schon Mitglied
    assert c.post("/api/v1/invitations", json={"email": "kein-at"}).status_code == 422
    daten = str(db(engines, "SELECT data FROM audit_events WHERE action = 'invitation.created'"))
    assert "doppelt@" not in daten                                          # nur Domain im Audit


def test_einladung_ohne_mailer_503(world: World, engines: Engines, settings: Settings) -> None:
    from tests.api_helpers import make_client
    _mitglied(world, engines, settings, world.a.id, "ohnemail@alpha.test", ADMIN)
    c, _ = make_client(settings, engines, mailer=None)
    login(c, "ohnemail@alpha.test")
    c.post("/api/v1/auth/tenant", json={"tenant_id": str(world.a.id)})
    r = c.post("/api/v1/invitations", json={"email": "x@y.test"})
    assert r.status_code == 503 and db(engines, "SELECT count(*) FROM invitations")[0][0] == 0


# ---------- Deaktivieren, Verlassen, Last-Admin ----------
def test_niemand_deaktiviert_sich_selbst(chef: Any, engines: Engines) -> None:
    c, _, mid = chef
    r = c.post(f"/api/v1/members/{_pid(engines, mid)}/deactivate")
    assert r.status_code == 403
    assert db(engines, "SELECT status FROM memberships WHERE id = %s", (mid,))[0][0] == "active"


def test_deaktivieren_wirkt_sofort(chef: Any, world: World, engines: Engines, settings: Settings) -> None:
    c, _, _ = chef
    ma = _mitglied(world, engines, settings, world.a.id, "ma@alpha.test", ["tasks.read", "company.read"])
    ma_c, _ = _sitzung(settings, engines, "ma@alpha.test", world.a.id)
    assert ma_c.get("/api/v1/company").status_code == 200
    r = c.post(f"/api/v1/members/{_pid(engines, ma)}/deactivate")
    assert r.status_code == 200 and r.json()["status"] == "suspended"
    assert ma_c.get("/api/v1/company").status_code == 403                    # tenant_required
    assert ma_c.post("/api/v1/auth/tenant", json={"tenant_id": str(world.a.id)}).status_code == 403
    assert c.post(f"/api/v1/members/{_pid(engines, ma)}/deactivate").status_code == 409
    assert db(engines, "SELECT count(*) FROM audit_events WHERE action = 'membership.deactivated'")[0][0] == 1


def test_letzter_admin_kann_nicht_entfernt_werden(chef: Any, world: World, engines: Engines,
                                                  settings: Settings) -> None:
    _c, _, chef_mid = chef
    # zweiter Admin entfernt den ersten: geht, solange er selbst bleibt
    zweit = _mitglied(world, engines, settings, world.a.id, "zweit@alpha.test", ADMIN)
    z, _ = _sitzung(settings, engines, "zweit@alpha.test", world.a.id)
    assert z.post(f"/api/v1/members/{_pid(engines, chef_mid)}/deactivate").status_code == 200
    # jetzt ist „zweit" der letzte Admin: Verlassen verboten
    r = z.post("/api/v1/membership/leave")
    assert r.status_code == 409 and r.json()["code"] == "last_admin"
    assert db(engines, "SELECT status FROM memberships WHERE id = %s", (zweit,))[0][0] == "active"
    # Admin-Recht kommt aus Rollen: archivierte Rolle zählt nicht
    rolle = db(engines, "SELECT r.id FROM roles r JOIN membership_roles mr ON mr.role_id = r.id "
                        "WHERE mr.membership_id = %s", (chef_mid,))[0][0]
    db(engines, "UPDATE memberships SET status = 'active' WHERE id = %s", (chef_mid,))
    db(engines, "UPDATE roles SET archived_at = now() WHERE id = %s", (rolle,))
    assert z.post("/api/v1/membership/leave").status_code == 409


def test_verlassen_mit_weiterem_admin(chef: Any, world: World, engines: Engines, settings: Settings) -> None:
    c, _, chef_mid = chef
    _mitglied(world, engines, settings, world.a.id, "zweit@alpha.test", ADMIN)
    assert c.post("/api/v1/membership/leave").status_code == 204
    assert db(engines, "SELECT status FROM memberships WHERE id = %s", (chef_mid,))[0][0] == "left"
    assert c.get("/api/v1/company").status_code == 403


def test_mitgliederliste_nur_eigene_firma_und_mit_recht(chef: Any, world: World, engines: Engines,
                                                       settings: Settings) -> None:
    c, _, _ = chef
    _mitglied(world, engines, settings, world.b.id, "fremd@beta.test", ADMIN)
    namen = {m["display_name"] for m in c.get("/api/v1/members?limit=100").json()["items"]}
    assert "fremd" not in namen and "chef" in namen
    _mitglied(world, engines, settings, world.a.id, "ohne@alpha.test", [])
    ohne, _ = _sitzung(settings, engines, "ohne@alpha.test", world.a.id)
    assert ohne.get("/api/v1/members").status_code == 403
    assert ohne.get("/api/v1/invitations").status_code == 403


def test_company_admin_per_control_plane(world: World, engines: Engines, settings: Settings) -> None:
    """M4 ersetzt den M3-Übergang: gesperrte Rolle mit berechneten Rechten (keine gespeicherte Liste)."""
    from ichq.authz.service import permissions_for_membership
    from ichq.authz.templates import make_company_admin
    mid = _mitglied(world, engines, settings, world.a.id, "boot@alpha.test", [])
    with tenant_transaction(engines.app, world.a.id) as s:
        assert make_company_admin(s, mid) is True
        assert make_company_admin(s, mid) is False                    # idempotent
        assert permissions_for_membership(s, mid) == PERMISSIONS
    assert db(engines, "SELECT count(*) FROM roles WHERE name = 'Company Admin' AND grants_all")[0][0] == 1
    assert db(engines, "SELECT count(*) FROM role_permissions rp JOIN roles r ON r.id = rp.role_id "
                       "WHERE r.grants_all")[0][0] == 0
    with tenant_transaction(engines.app, world.b.id) as s:
        assert permissions_for_membership(s, mid) == frozenset()   # nur in Firma A


def test_einladung_wird_atomar_verbraucht(chef: Any, engines: Engines, settings: Settings) -> None:
    """Zweite Stufe einzeln geprüft: Auch wenn die Vorprüfung durchkäme, verbraucht die Mandanten-Transaktion die
    Einladung nur einmal (bedingtes UPDATE)."""
    from ichq.members.accept import InvalidInvitation, _einloesen, _finden
    c, mailer, _ = chef
    c.post("/api/v1/invitations", json={"email": "race@extern.test"})
    gefunden = _finden(engines, _token(mailer))
    eins, zwei = make_user(engines, settings, "race@extern.test"), make_user(engines, settings, "zwei@extern.test")
    _einloesen(engines, gefunden, eins)
    with pytest.raises(InvalidInvitation):
        _einloesen(engines, gefunden, zwei)
    assert db(engines, "SELECT count(*) FROM memberships WHERE user_id = %s", (zwei,))[0][0] == 0


def test_vorpruefung_lehnt_abgelaufene_einladung_ab(chef: Any, engines: Engines) -> None:
    from ichq.members.accept import InvalidInvitation, _finden
    c, mailer, _ = chef
    c.post("/api/v1/invitations", json={"email": "alt@extern.test"})
    token = _token(mailer)
    db(engines, "UPDATE invitations SET created_at = now() - interval '9 days', expires_at = now() - interval '1 s'")
    with pytest.raises(InvalidInvitation):
        _finden(engines, token)
