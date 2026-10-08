"""Passwort-Reset und seine Missbrauchsversuche."""
from __future__ import annotations

import re

import pytest

from ichq.auth.tokens import hash_token
from ichq.core.config import Settings
from ichq.db.engine import Engines
from tests.auth_helpers import PASSWORT, alle_textwerte, client, db, events, login, make_user, token

NEU = "Frisches-Langes-Passwort-42"


def _anfordern(c, wer: str):  # type: ignore[no-untyped-def]
    return c.post("/api/v1/auth/password-reset/request", json={"login": wer})


def _token_aus(mailer) -> str:  # type: ignore[no-untyped-def]
    m = re.search(r"#token=([A-Za-z0-9_-]+)", mailer.sent[-1][2])
    assert m
    return m.group(1)


def _setzen(c, tok: str, pw: str = NEU):  # type: ignore[no-untyped-def]
    return c.post("/api/v1/auth/password-reset/confirm", json={"token": tok, "new_password": pw})


def test_gleiche_antwort_fuer_bekannt_und_unbekannt(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "da@firma.test")
    c, mailer = client(settings, engines)
    a, b = _anfordern(c, "da@firma.test"), _anfordern(c, "niemand@firma.test")
    assert a.status_code == b.status_code == 202 and a.content == b.content == b""
    assert len(mailer.sent) == 1 and mailer.sent[0][0] == "da@firma.test"


def test_kompletter_ablauf(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "reset@firma.test")
    c, mailer = client(settings, engines)
    _anfordern(c, "reset@firma.test")
    tok = _token_aus(mailer)
    assert "/reset#token=" in mailer.sent[0][2]          # Fragment: der Token erreicht nie ein Server-Log
    assert _setzen(c, tok).status_code == 204
    assert login(c, "reset@firma.test", PASSWORT).status_code == 401
    assert login(c, "reset@firma.test", NEU).status_code == 200
    ev = events(engines, uid)
    assert "password_reset_requested" in ev and "password_reset_completed" in ev


def test_token_nur_einmal(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "einmal@firma.test")
    c, mailer = client(settings, engines)
    _anfordern(c, "einmal@firma.test")
    tok = _token_aus(mailer)
    assert _setzen(c, tok).status_code == 204
    r = _setzen(c, tok, "Noch-Ein-Anderes-Passwort-7")
    assert r.status_code == 400 and r.json()["code"] == "invalid_token"


def test_token_laeuft_ab(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "ablauf@firma.test")
    c, mailer = client(settings, engines)
    _anfordern(c, "ablauf@firma.test")
    db(engines, "UPDATE password_reset_tokens SET expires_at = now() - interval '1 second'")
    assert _setzen(c, _token_aus(mailer)).status_code == 400


def test_neuer_antrag_entwertet_alten(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "doppelt@firma.test")
    c, mailer = client(settings, engines)
    _anfordern(c, "doppelt@firma.test")
    alt = _token_aus(mailer)
    _anfordern(c, "doppelt@firma.test")
    neu = _token_aus(mailer)
    assert _setzen(c, alt).status_code == 400 and _setzen(c, neu).status_code == 204


def test_erfundene_und_kaputte_tokens(engines: Engines, settings: Settings) -> None:
    c, _ = client(settings, engines)
    for tok in ("A" * 43, "x" * 16, "' OR 1=1 --xxxxxxxx"):
        assert _setzen(c, tok).status_code == 400
    assert _setzen(c, "kurz").status_code == 422


@pytest.mark.parametrize("status", ["suspended", "deactivated"])
def test_kein_reset_fuer_gesperrte_konten(engines: Engines, settings: Settings, status: str) -> None:
    uid = make_user(engines, settings, f"r-{status}@firma.test")
    c, mailer = client(settings, engines)
    _anfordern(c, f"r-{status}@firma.test")            # Token entsteht, solange das Konto aktiv ist
    tok = _token_aus(mailer)
    db(engines, "UPDATE users SET status = %s WHERE id = %s", (status, uid))
    assert _setzen(c, tok).status_code == 400
    db(engines, "UPDATE users SET status = %s WHERE id = %s", (status, uid))
    _anfordern(c, f"r-{status}@firma.test")
    assert len(mailer.sent) == 1                       # keine zweite Mail für ein gesperrtes Konto


def test_reset_beendet_alle_sitzungen_und_entsperrt(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "entsperren@firma.test")
    angemeldet, _ = client(settings, engines)
    login(angemeldet, "entsperren@firma.test")
    c, mailer = client(settings, engines)
    for _ in range(5):
        login(c, "entsperren@firma.test", "Falsch-Falsch-Falsch")
    assert db(engines, "SELECT status FROM users WHERE id = %s", (uid,))[0][0] == "locked"
    _anfordern(c, "entsperren@firma.test")
    assert _setzen(c, _token_aus(mailer)).status_code == 204
    assert angemeldet.get("/api/v1/auth/session").status_code == 401
    assert db(engines, "SELECT status, failed_logins FROM users WHERE id = %s", (uid,))[0] == ("active", 0)


def test_regelverstoss_laesst_token_gueltig(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "regel@firma.test")
    c, mailer = client(settings, engines)
    _anfordern(c, "regel@firma.test")
    tok = _token_aus(mailer)
    r = _setzen(c, tok, "kurz-zu")
    assert r.status_code == 422 and r.json()["policy"] == "too_short"
    assert _setzen(c, tok).status_code == 204


def test_einladung_aktiviert_konto(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "neu@firma.test", password=None)
    c, mailer = client(settings, engines)
    _anfordern(c, "neu@firma.test")
    assert _setzen(c, _token_aus(mailer)).status_code == 204
    assert db(engines, "SELECT status FROM users WHERE id = %s", (uid,))[0][0] == "active"


def test_kein_klartext_kein_log(engines: Engines, settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    make_user(engines, settings, "geheim@firma.test")
    c, mailer = client(settings, engines)
    _anfordern(c, "geheim@firma.test")
    tok = _token_aus(mailer)
    _setzen(c, tok)
    assert tok not in alle_textwerte(engines) and NEU not in alle_textwerte(engines)
    assert db(engines, "SELECT count(*) FROM password_reset_tokens WHERE token_hash = %s", (hash_token(tok),))[0][0] == 1
    out = capsys.readouterr().out
    assert tok not in out and NEU not in out


def test_drosselung_von_reset_anfragen(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "flut@firma.test")
    c, mailer = client(settings, engines)
    for _ in range(settings.identifier_max_failures + 3):
        assert _anfordern(c, "flut@firma.test").status_code == 202      # Antwort bleibt gleich
    assert len(mailer.sent) == settings.identifier_max_failures         # aber keine Mail-Flut
    assert "password_reset_throttled" in events(engines)


def test_ohne_mailserver_503(engines: Engines, settings: Settings) -> None:
    from tests.api_helpers import make_client
    c, app = make_client(settings, engines)
    app.state.ichq = app.state.ichq.__class__(**{**app.state.ichq.__dict__, "mailer": None})
    r = c.post("/api/v1/auth/password-reset/request", json={"login": "x@y.test"})
    assert r.status_code == 503 and r.json()["code"] == "password_reset_unavailable"


def test_reset_meldet_niemanden_an(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "nicht-auto@firma.test")
    c, mailer = client(settings, engines)
    _anfordern(c, "nicht-auto@firma.test")
    r = _setzen(c, _token_aus(mailer))
    assert r.status_code == 204 and "set-cookie" not in r.headers and token(c) is None
