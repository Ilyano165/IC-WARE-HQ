"""Login: korrekte Fälle, gleiche Antwort für alle Fehlschläge, Kontozustände, Audit, Cookies."""
from __future__ import annotations

import pytest

from ichq.core.config import Settings
from ichq.db.engine import Engines
from tests.auth_helpers import client, db, events, login, make_user, token
from tests.conftest import make_settings


def test_login_mit_email_und_benutzername(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "Anna@Firma.test", username="anna")
    c, _ = client(settings, engines)
    for name in ("anna@firma.test", "  ANNA@FIRMA.TEST ", "anna", "ANNA"):
        r = login(c, name)
        assert r.status_code == 200 and r.json() == {"status": "ok"}, name
        assert token(c) and token(c) not in r.text            # Token nur im Cookie
    assert events(engines, uid).count("login_succeeded") == 4
    assert c.get("/api/v1/auth/session").json()["user"]["email"] == "anna@firma.test"


def test_falsches_passwort_und_unbekanntes_konto_gleich(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "bert@firma.test")
    c, _ = client(settings, engines)
    a = login(c, "bert@firma.test", "Falsches-Passwort-123")
    b = login(c, "niemand@firma.test", "Falsches-Passwort-123")
    assert a.status_code == b.status_code == 401
    ohne_id = lambda r: {k: v for k, v in r.json().items() if k != "request_id"}  # noqa: E731
    assert ohne_id(a) == ohne_id(b) and a.json()["code"] == "invalid_credentials"
    assert token(c) is None
    gruende = [r[0] for r in db(engines, "SELECT data->>'reason' FROM auth_events WHERE event='login_failed' "
                                         "ORDER BY occurred_at")]
    assert gruende == ["bad_password", "unknown_account"]
    assert events(engines, uid)[-1] == "login_failed"


@pytest.mark.parametrize("status", ["pending", "suspended", "deactivated"])
def test_nicht_aktive_konten_kommen_nicht_rein(engines: Engines, settings: Settings, status: str) -> None:
    uid = make_user(engines, settings, f"{status}@firma.test")
    if status != "pending":
        db(engines, "UPDATE users SET status = %s WHERE id = %s", (status, uid))
    else:
        db(engines, "UPDATE users SET status = 'pending' WHERE id = %s", (uid,))
    c, _ = client(settings, engines)
    r = login(c, f"{status}@firma.test")          # richtiges Passwort!
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials" and token(c) is None
    assert db(engines, "SELECT data->>'reason' FROM auth_events WHERE event='login_failed'")[0][0] == f"status_{status}"


def test_konto_ohne_passwort(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "ohne@firma.test", password=None)
    c, _ = client(settings, engines)
    assert login(c, "ohne@firma.test", "").status_code == 422          # leeres Passwort: Validierung
    assert login(c, "ohne@firma.test", "irgendwas-langes").status_code == 401


def test_cookie_flags_entwicklung(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "keks@firma.test")
    c, _ = client(settings, engines)
    kopf = login(c, "keks@firma.test").headers["set-cookie"]
    assert kopf.startswith("ichq_session=") and "HttpOnly" in kopf and "SameSite=lax" in kopf
    assert "Path=/" in kopf and "Domain" not in kopf and "Secure" not in kopf


def test_cookie_flags_produktion(engines: Engines, settings: Settings, db_name: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    prod = make_settings(db_name, tmp_path, ICHQ_ENV="production", ICHQ_PUBLIC_ORIGIN="https://testserver",
                         ICHQ_ARGON2_MEMORY_KIB="65536")
    make_user(engines, settings, "prod@firma.test")
    c, _ = client(prod, engines, base_url="https://testserver")
    r = login(c, "prod@firma.test")
    kopf = r.headers["set-cookie"]
    assert r.status_code == 200
    assert kopf.startswith("__Host-ichq_session=") and "Secure" in kopf and "HttpOnly" in kopf
    assert "SameSite=lax" in kopf and "Path=/" in kopf and "Domain" not in kopf
    assert "Max-Age=43200" in kopf      # 12 Stunden absolut


def test_hash_wird_bei_login_erneuert(engines: Engines, settings: Settings, db_name: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    uid = make_user(engines, settings, "rehash@firma.test")
    alt = db(engines, "SELECT password_hash FROM users WHERE id = %s", (uid,))[0][0]
    staerker = make_settings(db_name, tmp_path, ICHQ_ARGON2_TIME_COST="2")
    c, _ = client(staerker, engines)
    assert login(c, "rehash@firma.test").status_code == 200
    neu = db(engines, "SELECT password_hash FROM users WHERE id = %s", (uid,))[0][0]
    assert neu != alt and ",t=2," in neu


def test_unbekanntes_konto_kostet_gleich_viel_rechenzeit(engines: Engines, settings: Settings,
                                                         monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Sonst verrät die Antwortzeit, welche E-Mail ein Konto hat. Gezählt statt gemessen — Zeitmessung im
    Test wäre unzuverlässig; entscheidend ist, dass in beiden Fällen genau ein Argon2-Vergleich läuft."""
    from argon2 import PasswordHasher
    aufrufe: list[str] = []
    original = PasswordHasher.verify

    def zaehlen(self, h, pw):  # type: ignore[no-untyped-def]
        aufrufe.append(h)
        return original(self, h, pw)
    monkeypatch.setattr(PasswordHasher, "verify", zaehlen)
    make_user(engines, settings, "bekannt@firma.test")
    c, _ = client(settings, engines)
    login(c, "bekannt@firma.test", "Falsches-Passwort-1")
    login(c, "unbekannt@firma.test", "Falsches-Passwort-1")
    assert len(aufrufe) == 2 and all(h.startswith("$argon2id$") for h in aufrufe)
