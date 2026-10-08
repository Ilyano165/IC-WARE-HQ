"""2FA (TOTP): Algorithmus, Speicherung, Login-Ablauf und Missbrauch."""
from __future__ import annotations

import base64

import pytest
from cryptography.exceptions import InvalidTag

from ichq.auth import totp
from ichq.core.config import Settings
from ichq.db.engine import Engines
from tests.auth_helpers import PASSWORT, alle_textwerte, client, db, enable_totp, events, login, make_user, token

RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")


@pytest.mark.parametrize("zeit,erwartet", [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"),
                                           (1234567890, "005924"), (2000000000, "279037")])
def test_rfc6238_testvektoren(zeit: int, erwartet: str) -> None:
    """Testvektoren aus RFC 6238, Anhang B (SHA-1), auf 6 Stellen gekürzt."""
    assert totp.code_at(RFC_SECRET, totp.current_step(zeit)) == erwartet


def test_zeitfenster_und_wiederverwendung() -> None:
    jetzt = 1_700_000_000
    schritt = totp.current_step(jetzt)
    for versatz in (-1, 0, 1):
        assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, schritt + versatz), None, jetzt) == schritt + versatz
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, schritt + 2), None, jetzt) is None
    assert totp.verify(RFC_SECRET, totp.code_at(RFC_SECRET, schritt), schritt, jetzt) is None    # schon benutzt
    assert totp.verify(RFC_SECRET, "12345", None, jetzt) is None and totp.verify(RFC_SECRET, "abcdef", None, jetzt) is None


def test_geheimnis_verschluesselt_und_an_konto_gebunden() -> None:
    blob = totp.encrypt("k" * 40, RFC_SECRET, "konto-a")
    assert RFC_SECRET.encode() not in blob and totp.decrypt("k" * 40, blob, "konto-a") == RFC_SECRET
    with pytest.raises(InvalidTag):
        totp.decrypt("k" * 40, blob, "konto-b")       # Geheimnis lässt sich nicht auf ein anderes Konto kopieren
    with pytest.raises(InvalidTag):
        totp.decrypt("x" * 40, blob, "konto-a")       # anderer Schlüssel


def test_einrichten(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "zwei@firma.test")
    c, _ = client(settings, engines)
    login(c, "zwei@firma.test")
    assert c.post("/api/v1/auth/2fa/setup", json={"password": "falsch-falsch-falsch"}).status_code == 401
    r = c.post("/api/v1/auth/2fa/setup", json={"password": PASSWORT})
    geheimnis = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/")
    assert c.post("/api/v1/auth/2fa/enable", json={"code": "000000"}).status_code == 401
    r = c.post("/api/v1/auth/2fa/enable", json={"code": totp.code_at(geheimnis, totp.current_step())})
    codes = r.json()["recovery_codes"]
    assert r.status_code == 200 and len(codes) == 10 and len(set(codes)) == 10
    alles = alle_textwerte(engines)
    assert geheimnis not in alles and not any(cd in alles for cd in codes)
    assert {"totp_setup_started", "totp_enabled"} <= set(events(engines, uid))


def _zeit_vergeht(engines: Engines) -> None:
    """Simuliert ein späteres Zeitfenster: Ohne das gibt es nach Einrichtung (Schritt t) und Login (t+1)
    im selben 30-s-Fenster keinen weiteren gültigen Code — der Wiederverwendungsschutz wirkt."""
    db(engines, "UPDATE users SET totp_last_step = totp_last_step - 3 WHERE totp_last_step IS NOT NULL")


def _mit_2fa(engines: Engines, settings: Settings, email: str) -> tuple[str, list[str]]:
    make_user(engines, settings, email)
    c, _ = client(settings, engines)
    login(c, email)
    return enable_totp(c)


def test_login_verlangt_zweiten_faktor(engines: Engines, settings: Settings) -> None:
    geheimnis, _ = _mit_2fa(engines, settings, "faktor@firma.test")
    c, _ = client(settings, engines)
    r = login(c, "faktor@firma.test")
    assert r.json() == {"status": "mfa_required"} and "Max-Age=300" in r.headers["set-cookie"]
    zwischen = token(c)
    for pfad in ("/api/v1/auth/session",):
        assert c.get(pfad).status_code == 401            # Zwischenschritt öffnet nichts
    assert c.post("/api/v1/auth/tenant", json={"tenant_id": "00000000-0000-0000-0000-000000000000"}).status_code == 401
    r = c.post("/api/v1/auth/mfa", json={"code": totp.code_at(geheimnis, totp.current_step() + 1)})
    assert r.status_code == 200 and token(c) != zwischen
    assert c.get("/api/v1/auth/session").status_code == 200


def test_falscher_und_wiederverwendeter_code(engines: Engines, settings: Settings) -> None:
    geheimnis, _ = _mit_2fa(engines, settings, "replay@firma.test")
    a, _ = client(settings, engines)
    login(a, "replay@firma.test")
    assert a.post("/api/v1/auth/mfa", json={"code": "123456"}).status_code == 401
    code = totp.code_at(geheimnis, totp.current_step() + 1)
    assert a.post("/api/v1/auth/mfa", json={"code": code}).status_code == 200
    b, _ = client(settings, engines)
    login(b, "replay@firma.test")
    r = b.post("/api/v1/auth/mfa", json={"code": code})          # abgefangener Code, zweiter Versuch
    assert r.status_code == 401 and r.json()["code"] == "mfa_invalid"


def test_zu_viele_falsche_codes(engines: Engines, settings: Settings) -> None:
    geheimnis, _ = _mit_2fa(engines, settings, "rate@firma.test")
    c, _ = client(settings, engines)
    login(c, "rate@firma.test")
    for _ in range(5):
        c.post("/api/v1/auth/mfa", json={"code": "000000"})
    r = c.post("/api/v1/auth/mfa", json={"code": totp.code_at(geheimnis, totp.current_step() + 1)})
    assert r.status_code == 401                               # Zwischenschritt verbrannt, auch mit richtigem Code
    assert "mfa_locked_out" in events(engines)


def test_zwischenschritt_laeuft_ab(engines: Engines, settings: Settings) -> None:
    geheimnis, _ = _mit_2fa(engines, settings, "langsam@firma.test")
    c, _ = client(settings, engines)
    login(c, "langsam@firma.test")
    db(engines, "UPDATE auth_sessions SET expires_at = now() - interval '1 second' WHERE stage = 'mfa_pending'")
    assert c.post("/api/v1/auth/mfa", json={"code": totp.code_at(geheimnis, totp.current_step() + 1)}).status_code == 401


def test_volle_sitzung_kann_mfa_schritt_nicht_nutzen(engines: Engines, settings: Settings) -> None:
    geheimnis, _ = _mit_2fa(engines, settings, "voll@firma.test")
    c, _ = client(settings, engines)
    login(c, "voll@firma.test")
    c.post("/api/v1/auth/mfa", json={"code": totp.code_at(geheimnis, totp.current_step() + 1)})
    assert c.post("/api/v1/auth/mfa", json={"code": "000000"}).status_code == 401


def test_recovery_code_nur_einmal(engines: Engines, settings: Settings) -> None:
    _, codes = _mit_2fa(engines, settings, "notfall@firma.test")
    a, _ = client(settings, engines)
    login(a, "notfall@firma.test")
    assert a.post("/api/v1/auth/mfa", json={"code": codes[0].lower().replace("-", " ")}).status_code == 200
    b, _ = client(settings, engines)
    login(b, "notfall@firma.test")
    assert b.post("/api/v1/auth/mfa", json={"code": codes[0]}).status_code == 401
    assert b.post("/api/v1/auth/mfa", json={"code": codes[1]}).status_code == 200
    assert db(engines, "SELECT data->>'remaining' FROM auth_events WHERE event='recovery_code_used' "
                       "ORDER BY occurred_at DESC LIMIT 1")[0][0] == "8"


def test_abschalten_braucht_passwort_und_code(engines: Engines, settings: Settings) -> None:
    geheimnis, _ = _mit_2fa(engines, settings, "aus@firma.test")
    c, _ = client(settings, engines)
    login(c, "aus@firma.test")
    c.post("/api/v1/auth/mfa", json={"code": totp.code_at(geheimnis, totp.current_step() + 1)})
    assert c.post("/api/v1/auth/2fa/disable", json={"password": PASSWORT,
                  "code": totp.code_at(geheimnis, totp.current_step())}).status_code == 401   # Fenster verbraucht
    _zeit_vergeht(engines)
    jetzt = totp.code_at(geheimnis, totp.current_step())
    assert c.post("/api/v1/auth/2fa/disable", json={"password": "falsch-falsch-falsch", "code": jetzt}).status_code == 401
    assert c.post("/api/v1/auth/2fa/disable", json={"password": PASSWORT, "code": "000000"}).status_code == 401
    assert c.post("/api/v1/auth/2fa/disable", json={"password": PASSWORT, "code": jetzt}).status_code == 204
    assert login(client(settings, engines)[0], "aus@firma.test").json() == {"status": "ok"}
    assert "totp_disabled" in events(engines)


def test_neue_recovery_codes_entwerten_alte(engines: Engines, settings: Settings) -> None:
    geheimnis, alte = _mit_2fa(engines, settings, "neucodes@firma.test")
    c, _ = client(settings, engines)
    login(c, "neucodes@firma.test")
    c.post("/api/v1/auth/mfa", json={"code": totp.code_at(geheimnis, totp.current_step() + 1)})
    _zeit_vergeht(engines)
    r = c.post("/api/v1/auth/2fa/recovery-codes",
               json={"password": PASSWORT, "code": totp.code_at(geheimnis, totp.current_step())})
    assert r.status_code == 200 and set(r.json()["recovery_codes"]).isdisjoint(alte)
    d, _ = client(settings, engines)
    login(d, "neucodes@firma.test")
    assert d.post("/api/v1/auth/mfa", json={"code": alte[3]}).status_code == 401


def test_aktivieren_beendet_andere_sitzungen(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "andere@firma.test")
    hier, _ = client(settings, engines)
    dort, _ = client(settings, engines)
    login(hier, "andere@firma.test")
    login(dort, "andere@firma.test")
    enable_totp(hier)
    assert hier.get("/api/v1/auth/session").status_code == 200 and dort.get("/api/v1/auth/session").status_code == 401
