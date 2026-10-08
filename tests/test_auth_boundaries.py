"""Authentifizierung ersetzt keine Autorisierung — und weitere Grenzen."""
from __future__ import annotations

import io
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from ichq import cli
from ichq.core.config import Settings, get_settings
from ichq.db.engine import Engines
from ichq.db.session import auth_transaction, platform_transaction, tenant_transaction
from tests.auth_helpers import PASSWORT, client, db, enable_totp, events, join, login, make_user, token
from tests.conftest import World


def _mit_firma(c, tid: uuid.UUID) -> int:  # type: ignore[no-untyped-def]
    return int(c.post("/api/v1/auth/tenant", json={"tenant_id": str(tid)}).status_code)


# ---------- Authentifizierung ≠ Autorisierung ----------
def test_angemeldet_ohne_firma_darf_nichts(world: World, engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "ohnefirma@firma.test")
    join(engines, world.a.id, uid)
    c, _ = client(settings, engines)
    login(c, "ohnefirma@firma.test")
    for pfad in ("/api/v1/me", "/api/v1/company"):
        r = c.get(pfad)
        assert r.status_code == 403 and r.json()["code"] == "tenant_required", pfad


def test_mitglied_ohne_rolle_hat_keine_rechte(world: World, engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "ohnerolle@firma.test")
    join(engines, world.a.id, uid)
    c, _ = client(settings, engines)
    login(c, "ohnerolle@firma.test")
    assert _mit_firma(c, world.a.id) == 200
    assert c.get("/api/v1/me").json()["permissions"] == []
    r = c.get("/api/v1/company")
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"


def test_rechte_kommen_nur_aus_rollen(world: World, engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "mitrolle@firma.test")
    mid = join(engines, world.a.id, uid)
    world.assign(world.a.id, mid, world.role(world.a.id, "Lesen", ["company.read"]))
    c, _ = client(settings, engines)
    login(c, "mitrolle@firma.test")
    _mit_firma(c, world.a.id)
    assert c.get("/api/v1/me").json()["permissions"] == ["company.read"]
    assert c.get("/api/v1/company").json()["slug"] == "alpha"


def test_keine_firma_ohne_mitgliedschaft(world: World, engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "fremd@firma.test")
    join(engines, world.a.id, uid)
    c, _ = client(settings, engines)
    login(c, "fremd@firma.test")
    vorher = token(c)
    for tid in (world.b.id, uuid.uuid4()):          # fremde Firma und erfundene Firma — gleiche Antwort
        r = c.post("/api/v1/auth/tenant", json={"tenant_id": str(tid)})
        assert r.status_code == 403 and r.json()["code"] == "tenant_forbidden"
    assert token(c) == vorher and "tenant_selection_denied" in events(engines, uid)
    sichtbar = {m["slug"] for m in c.get("/api/v1/auth/session").json()["memberships"]}
    assert sichtbar == {"alpha"}                    # Firma B taucht nirgends auf


def test_entzug_der_mitgliedschaft_wirkt_sofort(world: World, engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "entzug@firma.test")
    mid = join(engines, world.a.id, uid)
    world.assign(world.a.id, mid, world.role(world.a.id, "Lesen", ["company.read"]))
    c, _ = client(settings, engines)
    login(c, "entzug@firma.test")
    _mit_firma(c, world.a.id)
    assert c.get("/api/v1/company").status_code == 200
    with tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("UPDATE memberships SET status = 'suspended' WHERE id = :m"), {"m": mid})
    assert c.get("/api/v1/company").status_code == 403       # Sitzung lebt, Zugriff nicht


def test_gesperrte_firma_nicht_waehlbar(world: World, engines: Engines, settings: Settings) -> None:
    from ichq.tenancy.service import set_status
    uid = make_user(engines, settings, "gesperrt@firma.test")
    join(engines, world.a.id, uid)
    with platform_transaction(engines.platform) as s:
        set_status(s, world.a.id, "suspended", actor="test", reason="Zahlung")
    c, _ = client(settings, engines)
    login(c, "gesperrt@firma.test")
    assert _mit_firma(c, world.a.id) == 403


def test_zwischenschritt_gibt_keinen_principal(world: World, engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "halb@firma.test")
    join(engines, world.a.id, uid)
    c, _ = client(settings, engines)
    login(c, "halb@firma.test")
    enable_totp(c)
    d, _ = client(settings, engines)
    login(d, "halb@firma.test")
    assert d.get("/api/v1/me").status_code == 401 and d.get("/api/v1/company").status_code == 401


# ---------- CSRF ----------
@pytest.mark.parametrize("kopf", [{"Origin": "https://boese.example"}, {"Sec-Fetch-Site": "cross-site"}])
def test_fremde_herkunft_abgelehnt(engines: Engines, settings: Settings, kopf: dict[str, str]) -> None:
    make_user(engines, settings, "csrf@firma.test")
    c, _ = client(settings, engines)
    r = c.post("/api/v1/auth/login", json={"login": "csrf@firma.test", "password": PASSWORT}, headers=kopf)
    assert r.status_code == 403 and r.json()["code"] == "cross_site_request" and token(c) is None
    login(c, "csrf@firma.test")
    assert c.post("/api/v1/auth/logout-all", headers=kopf).status_code == 403
    assert c.get("/api/v1/auth/session").status_code == 200          # nichts passiert


def test_eigene_herkunft_erlaubt(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "selbst@firma.test")
    c, _ = client(settings, engines)
    r = c.post("/api/v1/auth/login", json={"login": "selbst@firma.test", "password": PASSWORT},
               headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200


# ---------- Datenbankrechte ----------
def test_app_rolle_sieht_keine_passwort_hashes(world: World, engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "versteckt@firma.test")
    join(engines, world.a.id, uid)
    with tenant_transaction(engines.app, world.a.id) as s:
        assert s.execute(text("SELECT email FROM users WHERE id = :u"), {"u": uid}).scalar() == "versteckt@firma.test"
    for spalte in ("password_hash", "totp_secret_enc", "failed_logins"):
        with pytest.raises(ProgrammingError, match="permission denied"), \
                tenant_transaction(engines.app, world.a.id) as s:
            s.execute(text(f"SELECT {spalte} FROM users"))


def test_plattform_rolle_kann_weder_hash_noch_status(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "platt@firma.test")
    for sql in ("SELECT password_hash FROM users", "UPDATE users SET status = 'active'",
                "UPDATE users SET password_hash = NULL", "SELECT * FROM auth_sessions"):
        with pytest.raises(ProgrammingError, match="permission denied"), platform_transaction(engines.platform) as s:
            s.execute(text(sql))
    assert uid


def test_auth_rolle_sieht_nur_eigene_mitgliedschaften(world: World, engines: Engines) -> None:
    with auth_transaction(engines.auth, user_id=world.user_a) as s:
        firmen = {r[0] for r in s.execute(text("SELECT t.slug FROM memberships m JOIN tenants t ON t.id = m.tenant_id"))}
    with auth_transaction(engines.auth) as s:     # ohne Kontoangabe: nichts
        assert s.execute(text("SELECT count(*) FROM memberships")).scalar() == 0
    assert firmen == {"alpha"}


def test_auth_audit_nur_anhaengend(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "audit@firma.test")
    c, _ = client(settings, engines)
    login(c, "audit@firma.test")
    for sql in ("UPDATE auth_events SET event = 'gefaelscht'", "DELETE FROM auth_events", "TRUNCATE auth_events"):
        with pytest.raises(Exception, match="nur anhängend"):
            db(engines, sql)


# ---------- Audit-Vollständigkeit ----------
def test_alle_geforderten_ereignisse(world: World, engines: Engines, settings: Settings) -> None:
    from ichq.auth import account
    uid = make_user(engines, settings, "voll@firma.test")
    join(engines, world.a.id, uid)
    c, mailer = client(settings, engines)
    login(c, "voll@firma.test", "Falsches-Passwort-123")                       # failed login
    login(c, "voll@firma.test")                                                 # login
    c.post("/api/v1/auth/password", json={"current_password": PASSWORT, "new_password": "Zweites-Passwort-Lang-1"})
    enable_totp(c, "Zweites-Passwort-Lang-1")                                   # 2FA
    c.post("/api/v1/auth/logout")                                               # logout
    c.post("/api/v1/auth/password-reset/request", json={"login": "voll@firma.test"})
    import re
    tok = re.search(r"#token=([A-Za-z0-9_-]+)", mailer.sent[-1][2]).group(1)  # type: ignore[union-attr]
    c.post("/api/v1/auth/password-reset/confirm", json={"token": tok, "new_password": "Drittes-Passwort-Lang-2"})
    with auth_transaction(engines.auth) as s:
        account.set_status(s, uid, "suspended", actor="test", reason="Prüfung")  # status change
    erwartet = {"login_failed", "login_succeeded", "password_changed", "totp_setup_started", "totp_enabled",
                "logout", "password_reset_requested", "password_reset_completed", "account_status_changed"}
    assert erwartet <= set(events(engines, uid)), erwartet - set(events(engines, uid))
    ip, rid = db(engines, "SELECT ip, request_id FROM auth_events WHERE event = 'login_succeeded'")[0]
    assert ip and rid


# ---------- CLI ----------
@pytest.fixture
def cli_env(settings: Settings, monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    for name in ("database_url", "platform_database_url", "worker_database_url", "auth_database_url",
                 "secret_key", "session_secret"):
        monkeypatch.setenv(f"ICHQ_{name.upper()}", getattr(settings, name).get_secret_value())
    for k in ("ARGON2_MEMORY_KIB", "ARGON2_TIME_COST", "ARGON2_PARALLELISM"):
        monkeypatch.setenv(f"ICHQ_{k}", str(getattr(settings, k.lower())))
    monkeypatch.setenv("ICHQ_STORAGE_PATH", str(settings.storage_path))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_cli_konto_einrichten(world: World, cli_env: None, engines: Engines, settings: Settings,
                              monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["user-create", "--email", "cli@firma.test", "--name", "Cli", "--username", "cli.nutzer"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("password1234\n"))
    assert cli.main(["user-set-password", "--email", "cli@firma.test", "--password-stdin"]) == 1   # Regel gilt
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORT + "\n"))
    assert cli.main(["user-set-password", "--email", "cli@firma.test", "--password-stdin"]) == 0
    assert cli.main(["membership-add", "--email", "cli@firma.test", "--tenant", "alpha"]) == 0
    c, _ = client(settings, engines)
    assert login(c, "cli.nutzer").status_code == 200 and _mit_firma(c, world.a.id) == 200
    assert cli.main(["user-status", "--email", "cli@firma.test", "deactivated", "--reason", "Austritt"]) == 0
    assert c.get("/api/v1/auth/session").status_code == 401
    out = capsys.readouterr()
    assert PASSWORT not in out.out + out.err
