"""Sitzungen: Fixation, Rotation, Ablauf, Abmelden, Invalidierung."""
from __future__ import annotations

import uuid

import pytest

from ichq.auth import account
from ichq.auth.tokens import hash_token
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import auth_transaction
from tests.auth_helpers import PASSWORT, alle_textwerte, client, db, events, join, login, make_user, set_token, token
from tests.conftest import World


def _gueltig(c, roh: str | None = None) -> bool:  # type: ignore[no-untyped-def]
    if roh is not None:
        set_token(c, roh)
    return c.get("/api/v1/auth/session").status_code == 200


# ---------- Session Fixation ----------
def test_selbst_gewaehltes_token_wird_nie_akzeptiert(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "fix@firma.test")
    c, _ = client(settings, engines)
    vorgegeben = "angreifer-hat-dieses-token-vorgegeben-1234567890"
    set_token(c, vorgegeben)
    assert c.get("/api/v1/auth/session").status_code == 401
    assert login(c, "fix@firma.test").status_code == 200
    assert token(c) != vorgegeben and len(token(c) or "") >= 40
    assert db(engines, "SELECT count(*) FROM auth_sessions WHERE token_hash = %s", (hash_token(vorgegeben),))[0][0] == 0


def test_fremdes_gueltiges_token_wird_nicht_aufgewertet(engines: Engines, settings: Settings) -> None:
    """Angreifer schiebt dem Opfer SEIN gültiges Token unter. Nach dem Login des Opfers gehört das
    Token des Angreifers weiterhin dem Angreifer — das Opfer bekommt ein neues."""
    angreifer = make_user(engines, settings, "angreifer@firma.test")
    opfer = make_user(engines, settings, "opfer@firma.test")
    a, _ = client(settings, engines)
    login(a, "angreifer@firma.test")
    a_token = token(a)
    o, _ = client(settings, engines)
    set_token(o, a_token)
    login(o, "opfer@firma.test")
    assert token(o) != a_token
    assert db(engines, "SELECT user_id FROM auth_sessions WHERE token_hash = %s", (hash_token(a_token),))[0][0] == angreifer
    assert o.get("/api/v1/auth/session").json()["user"]["id"] == str(opfer)


def test_jeder_stufenwechsel_rotiert_das_token(world: World, engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "stufen@firma.test")
    join(engines, world.a.id, uid)
    c, _ = client(settings, engines)
    login(c, "stufen@firma.test")
    t1 = token(c)
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": str(world.a.id)}).status_code == 200
    t2 = token(c)
    assert t2 != t1 and not _gueltig(c, t1) and _gueltig(c, t2)


def test_token_nur_als_hash_gespeichert(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "hash@firma.test")
    c, _ = client(settings, engines)
    login(c, "hash@firma.test")
    assert token(c) not in alle_textwerte(engines)
    assert db(engines, "SELECT count(*) FROM auth_sessions WHERE token_hash = %s", (hash_token(token(c)),))[0][0] == 1


# ---------- Ablauf ----------
def test_absolute_grenze(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "absolut@firma.test")
    c, _ = client(settings, engines)
    login(c, "absolut@firma.test")
    db(engines, "UPDATE auth_sessions SET expires_at = now() - interval '1 second'")
    assert c.get("/api/v1/auth/session").status_code == 401
    assert db(engines, "SELECT revoke_reason FROM auth_sessions")[0][0] == "absolute_timeout"
    assert "session_ended" in events(engines, uid)


def test_leerlauf(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "leerlauf@firma.test")
    c, _ = client(settings, engines)
    login(c, "leerlauf@firma.test")
    db(engines, "UPDATE auth_sessions SET last_seen_at = now() - make_interval(mins => %s + 1)",
       (settings.session_idle_minutes,))
    assert c.get("/api/v1/auth/session").status_code == 401
    assert db(engines, "SELECT revoke_reason FROM auth_sessions")[0][0] == "idle_timeout"


def test_aktivitaet_verlaengert_leerlauf_aber_nicht_absolut(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "aktiv@firma.test")
    c, _ = client(settings, engines)
    login(c, "aktiv@firma.test")
    ende_vorher = db(engines, "SELECT expires_at FROM auth_sessions")[0][0]
    db(engines, "UPDATE auth_sessions SET last_seen_at = now() - interval '10 minutes'")
    assert c.get("/api/v1/auth/session").status_code == 200
    gesehen, ende = db(engines, "SELECT last_seen_at > now() - interval '5 seconds', expires_at FROM auth_sessions")[0]
    assert gesehen and ende == ende_vorher


def test_abgelaufene_sitzung_bleibt_tot(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "tot@firma.test")
    c, _ = client(settings, engines)
    login(c, "tot@firma.test")
    db(engines, "UPDATE auth_sessions SET expires_at = now() - interval '1 second'")
    c.get("/api/v1/auth/session")
    db(engines, "UPDATE auth_sessions SET expires_at = now() + interval '1 hour'")   # Uhr zurückdrehen hilft nicht
    assert c.get("/api/v1/auth/session").status_code == 401


# ---------- Abmelden und Invalidierung ----------
def test_logout(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "tschuess@firma.test")
    c, _ = client(settings, engines)
    login(c, "tschuess@firma.test")
    alt = token(c)
    r = c.post("/api/v1/auth/logout")
    assert r.status_code == 204 and 'ichq_session=""' in r.headers["set-cookie"]
    assert not _gueltig(c, alt)
    assert events(engines, uid)[-1] == "logout"


def test_logout_ueberall(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "geraete@firma.test")
    andere = make_user(engines, settings, "fremd@firma.test")
    laptop, _ = client(settings, engines)
    handy, _ = client(settings, engines)
    fremd, _ = client(settings, engines)
    for c, email in ((laptop, "geraete@firma.test"), (handy, "geraete@firma.test"), (fremd, "fremd@firma.test")):
        login(c, email)
    assert laptop.post("/api/v1/auth/logout-all").status_code == 204
    assert not _gueltig(handy) and not _gueltig(laptop)
    assert _gueltig(fremd)                                   # andere Konten unberührt
    assert "logout_all" in events(engines, uid) and "logout_all" not in events(engines, andere)


def test_passwortwechsel_beendet_andere_sitzungen(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "wechsel@firma.test")
    hier, _ = client(settings, engines)
    dort, _ = client(settings, engines)
    login(hier, "wechsel@firma.test")
    login(dort, "wechsel@firma.test")
    alt = token(hier)
    neu_pw = "Neues-Langes-Passwort-99"
    r = hier.post("/api/v1/auth/password", json={"current_password": PASSWORT, "new_password": neu_pw})
    assert r.status_code == 200
    assert _gueltig(hier) and token(hier) != alt and not _gueltig(dort)
    assert not _gueltig(hier, alt)
    assert login(dort, "wechsel@firma.test", PASSWORT).status_code == 401
    assert login(dort, "wechsel@firma.test", neu_pw).status_code == 200
    assert "password_changed" in events(engines, uid)


def test_passwortwechsel_braucht_altes_passwort_und_regel(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "regel@firma.test")
    c, _ = client(settings, engines)
    login(c, "regel@firma.test")
    r = c.post("/api/v1/auth/password", json={"current_password": "falsch-falsch-falsch", "new_password": "Ok-Lang-Genug-123"})
    assert r.status_code == 401
    r = c.post("/api/v1/auth/password", json={"current_password": PASSWORT, "new_password": "password1234"})
    assert r.status_code == 422 and r.json()["policy"] == "common"
    assert "password_changed" not in events(engines, uid)


@pytest.mark.parametrize("status", ["deactivated", "suspended", "locked"])
def test_kontostatus_beendet_sitzungen_sofort(engines: Engines, settings: Settings, status: str) -> None:
    uid = make_user(engines, settings, f"s-{status}@firma.test")
    c, _ = client(settings, engines)
    login(c, f"s-{status}@firma.test")
    assert _gueltig(c)
    with auth_transaction(engines.auth) as s:
        assert account.set_status(s, uid, status, actor="test", reason="Test").ok
    assert not _gueltig(c)
    assert login(c, f"s-{status}@firma.test").status_code == 401
    assert "account_status_changed" in events(engines, uid)


def test_status_direkt_in_der_datenbank_wirkt_auch(engines: Engines, settings: Settings) -> None:
    """Zweite Linie: Selbst wenn jemand den Status ohne Sitzungs-Widerruf ändert, prüft jede Anfrage ihn."""
    uid = make_user(engines, settings, "direkt@firma.test")
    c, _ = client(settings, engines)
    login(c, "direkt@firma.test")
    db(engines, "UPDATE users SET status = 'deactivated' WHERE id = %s", (uid,))
    assert not _gueltig(c)
    assert db(engines, "SELECT revoke_reason FROM auth_sessions")[0][0] == "account_deactivated"


def test_ungueltige_cookies(engines: Engines, settings: Settings) -> None:
    c, _ = client(settings, engines)
    for wert in ("", "x", "a" * 500, "'; DROP TABLE auth_sessions; --", str(uuid.uuid4())):
        set_token(c, wert)
        assert c.get("/api/v1/auth/session").status_code == 401, wert
    assert db(engines, "SELECT count(*) FROM auth_sessions")[0][0] == 0
