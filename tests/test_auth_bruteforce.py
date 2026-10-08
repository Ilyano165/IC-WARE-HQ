"""Brute Force: Kontosperre, Drosselung je Login-Name und je IP — gespeichert, nicht zurückgerollt."""
from __future__ import annotations

from ichq.core.config import Settings
from ichq.db.engine import Engines
from tests.auth_helpers import PASSWORT, client, db, events, login, make_user, token
from tests.conftest import make_settings

FALSCH = "Ganz-Falsches-Passwort"


def test_kontosperre_nach_fuenf_fehlversuchen(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "ziel@firma.test")
    c, _ = client(settings, engines)
    for _ in range(5):
        assert login(c, "ziel@firma.test", FALSCH).status_code == 401
    status, fehler = db(engines, "SELECT status, failed_logins FROM users WHERE id = %s", (uid,))[0]
    assert (status, fehler) == ("locked", 5)
    r = login(c, "ziel@firma.test", PASSWORT)                 # sogar mit RICHTIGEM Passwort
    assert r.status_code == 401 and token(c) is None
    assert "account_locked" in events(engines, uid)


def test_fehlversuche_ueberleben_den_fehlerfall(engines: Engines, settings: Settings) -> None:
    """Regression gegen die Falle 'Ausnahme rollt den Zähler zurück'."""
    uid = make_user(engines, settings, "zaehler@firma.test")
    c, _ = client(settings, engines)
    login(c, "zaehler@firma.test", FALSCH)
    assert db(engines, "SELECT failed_logins FROM users WHERE id = %s", (uid,))[0][0] == 1
    assert db(engines, "SELECT count(*) FROM login_attempts WHERE NOT success")[0][0] == 1


def test_sperre_laeuft_ab(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "geduld@firma.test")
    c, _ = client(settings, engines)
    for _ in range(5):
        login(c, "geduld@firma.test", FALSCH)
    db(engines, "UPDATE users SET locked_until = now() - interval '1 second' WHERE id = %s", (uid,))
    db(engines, "DELETE FROM login_attempts")       # Namens-Drossel getrennt testen
    assert login(c, "geduld@firma.test").status_code == 200
    status, fehler = db(engines, "SELECT status, failed_logins FROM users WHERE id = %s", (uid,))[0]
    assert (status, fehler) == ("active", 0)
    assert "account_unlocked" in events(engines, uid)


def test_betreiber_sperre_laeuft_nicht_ab(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "gesperrt@firma.test")
    db(engines, "UPDATE users SET status = 'locked', locked_until = NULL WHERE id = %s", (uid,))
    c, _ = client(settings, engines)
    assert login(c, "gesperrt@firma.test").status_code == 401


def test_erfolg_setzt_zaehler_zurueck(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "vergesslich@firma.test")
    c, _ = client(settings, engines)
    for _ in range(4):
        login(c, "vergesslich@firma.test", FALSCH)
    assert login(c, "vergesslich@firma.test").status_code == 200
    assert db(engines, "SELECT failed_logins FROM users WHERE id = %s", (uid,))[0][0] == 0
    assert login(c, "vergesslich@firma.test", FALSCH).status_code == 401
    assert db(engines, "SELECT status FROM users WHERE id = %s", (uid,))[0][0] == "active"


def test_drossel_je_login_name_auch_ohne_konto(engines: Engines, settings: Settings) -> None:
    c, _ = client(settings, engines)
    for _ in range(settings.identifier_max_failures):
        assert login(c, "gibtsnicht@firma.test", FALSCH).status_code == 401
    r = login(c, "gibtsnicht@firma.test", FALSCH)
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"
    assert int(r.headers["retry-after"]) == settings.throttle_window_minutes * 60
    assert "login_throttled" in events(engines)


def test_drossel_je_ip_ueber_viele_namen(engines: Engines, db_name: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    eng = make_settings(db_name, tmp_path, ICHQ_IP_MAX_FAILURES="6")
    make_user(engines, eng, "echt@firma.test")
    c, _ = client(eng, engines)
    for i in range(6):
        assert login(c, f"spray{i}@firma.test", FALSCH).status_code == 401
    r = login(c, "echt@firma.test", PASSWORT)          # selbst richtige Daten — die IP ist gedrosselt
    assert r.status_code == 429 and token(c) is None


def test_drossel_endet_nach_dem_fenster(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "spaeter@firma.test")
    c, _ = client(settings, engines)
    for _ in range(settings.identifier_max_failures):
        login(c, "spaeter@firma.test", FALSCH)
    db(engines, "UPDATE users SET status = 'active', locked_until = NULL, failed_logins = 0")
    assert login(c, "spaeter@firma.test").status_code == 429
    db(engines, "UPDATE login_attempts SET occurred_at = now() - interval '16 minutes'")
    assert login(c, "spaeter@firma.test").status_code == 200


def test_keine_passwoerter_im_audit_oder_log(engines: Engines, settings: Settings, capsys) -> None:  # type: ignore[no-untyped-def]
    make_user(engines, settings, "log@firma.test")
    c, _ = client(settings, engines)
    login(c, "log@firma.test", "Mein-Geheimes-Falsches-Pw")
    login(c, "log@firma.test")
    out = capsys.readouterr().out
    alles = str(db(engines, "SELECT * FROM auth_events")) + str(db(engines, "SELECT * FROM login_attempts"))
    for geheim in ("Mein-Geheimes-Falsches-Pw", PASSWORT, "log@firma.test"):
        assert geheim not in alles, geheim
    assert "Mein-Geheimes-Falsches-Pw" not in out and PASSWORT not in out
