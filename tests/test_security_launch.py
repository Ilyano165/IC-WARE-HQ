"""Regressionstests der Launch-Sicherheitsprüfung (Befunde der Audits vom 09.10.2026, docs/security-review.md).

Jeder Test hat seine Mutation in scripts/mutation-check.sh — er muss rot werden, wenn die Abwehr fehlt."""
from __future__ import annotations

from typing import Any

from ichq.auth import login as auth_login
from ichq.auth import sessions, totp
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import auth_transaction
from tests.auth_helpers import PASSWORT, client, db, enable_totp, events, login, make_user, token
from tests.conftest import World


def _mit_2fa(engines: Engines, settings: Settings, email: str) -> str:
    make_user(engines, settings, email)
    c, _ = client(settings, engines)
    login(c, email)
    return enable_totp(c)[0]


# ---- F1: 2FA nicht über viele Logins durchprobierbar -----------------------------------------------------------
def test_mfa_fehlversuche_zaehlen_ueber_logins_hinweg(engines: Engines, settings: Settings) -> None:
    geheimnis = _mit_2fa(engines, settings, "brute@firma.test")
    c, _ = client(settings, engines)
    fehler = 0
    while fehler < settings.identifier_max_failures:
        assert login(c, "brute@firma.test").status_code == 200            # Passwort stimmt jedes Mal
        for _ in range(2):
            c.post("/api/v1/auth/mfa", json={"code": "000000"})
            fehler += 1
    assert login(c, "brute@firma.test").status_code == 200
    r = c.post("/api/v1/auth/mfa", json={"code": totp.code_at(geheimnis, totp.current_step() + 1)})
    assert r.status_code == 429 and r.json()["code"] == "too_many_attempts"   # auch der richtige Code nicht
    assert "mfa_throttled" in events(engines)
    db(engines, "UPDATE login_attempts SET occurred_at = occurred_at - interval '1 day' WHERE kind = 'mfa'")
    assert login(c, "brute@firma.test").status_code == 200                  # nach dem Fenster wieder möglich
    assert c.post("/api/v1/auth/mfa", json={"code": totp.code_at(geheimnis, totp.current_step() + 1)}
                  ).status_code == 200


# ---- F2: Zähler atomar, widerrufene Challenge zählt nicht mehr ------------------------------------------------
def test_mfa_zaehler_mit_veralteter_sitzung(engines: Engines, settings: Settings) -> None:
    geheimnis = _mit_2fa(engines, settings, "race@firma.test")
    c, _ = client(settings, engines)
    login(c, "race@firma.test")
    roh = token(c)
    assert roh
    with auth_transaction(engines.auth) as s:
        challenge = sessions.load(s, settings, roh)          # einmal geladen — wie parallele Anfragen
    assert challenge is not None
    for _ in range(auth_login.MFA_MAX_ATTEMPTS):
        with auth_transaction(engines.auth) as s:
            auth_login.verify_mfa(s, settings, challenge, "000000", ip="1.2.3.4", user_agent=None)
    assert db(engines, "SELECT mfa_attempts, revoked_at IS NOT NULL FROM auth_sessions WHERE id = %s",
              (challenge.id,)) == [(auth_login.MFA_MAX_ATTEMPTS, True)]
    with auth_transaction(engines.auth) as s:
        o = auth_login.verify_mfa(s, settings, challenge, totp.code_at(geheimnis, totp.current_step() + 1),
                                  ip="1.2.3.4", user_agent=None)
    assert not o.ok and o.error == "mfa_invalid"             # verbrannte Challenge: auch richtiger Code nutzlos


# ---- F3: Reset hebt keine Betreiber-Sperre auf -----------------------------------------------------------------
def test_reset_hebt_betreibersperre_nicht_auf(engines: Engines, settings: Settings) -> None:
    from ichq.auth.account import set_status
    uid = make_user(engines, settings, "gesperrt@firma.test")
    c, mailer = client(settings, engines)
    c.post("/api/v1/auth/password-reset/request", json={"login": "gesperrt@firma.test"})
    tok = mailer.sent[-1][2].split("#token=")[1].split()[0]
    with auth_transaction(engines.auth) as s:
        set_status(s, uid, "locked", actor="betreiber", reason="Test")
    r = c.post("/api/v1/auth/password-reset/confirm", json={"token": tok, "new_password": "Ganz-Neu-Wolke-99"})
    assert r.status_code == 400
    assert db(engines, "SELECT status FROM users WHERE id = %s", (uid,)) == [("locked",)]
    c.post("/api/v1/auth/password-reset/request", json={"login": "gesperrt@firma.test"})
    assert len(mailer.sent) == 1                                                  # keine neue Reset-Mail
    assert login(c, "gesperrt@firma.test").status_code != 200


def test_reset_hebt_automatische_sperre_auf(engines: Engines, settings: Settings) -> None:
    uid = make_user(engines, settings, "auto@firma.test")
    c, mailer = client(settings, engines)
    for _ in range(settings.login_max_failures):
        login(c, "auto@firma.test", "falsch-falsch-falsch")
    assert db(engines, "SELECT status, locked_until IS NOT NULL FROM users WHERE id = %s", (uid,)) == [("locked", True)]
    c.post("/api/v1/auth/password-reset/request", json={"login": "auto@firma.test"})
    tok = mailer.sent[-1][2].split("#token=")[1].split()[0]
    neu = "Ganz-Neu-Wolke-99"
    assert c.post("/api/v1/auth/password-reset/confirm", json={"token": tok, "new_password": neu}).status_code == 204
    assert login(c, "auto@firma.test", neu).status_code == 200


# ---- F4: Passwort hinter einer Sitzung ist kein unbegrenztes Orakel --------------------------------------------
def test_passwort_abfrage_hinter_sitzung_gedrosselt(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "orakel@firma.test")
    c, _ = client(settings, engines)
    login(c, "orakel@firma.test")
    for _ in range(settings.identifier_max_failures):
        assert c.post("/api/v1/auth/2fa/setup", json={"password": "geraten-geraten-1"}).status_code == 401
    r = c.post("/api/v1/auth/2fa/setup", json={"password": PASSWORT})
    assert r.status_code == 429                                                  # richtiges Passwort hilft nicht
    assert c.get("/api/v1/auth/session").status_code == 401                     # Sitzung beendet
    assert "reauth_throttled" in events(engines)


def test_zwei_faktor_aus_beendet_andere_sitzungen(engines: Engines, settings: Settings) -> None:
    geheimnis = _mit_2fa(engines, settings, "aus@firma.test")
    def frischer_code() -> str:   # Zeit simulieren: Wiederverwendungsschutz zurücksetzen statt ihn abzuschwächen
        db(engines, "UPDATE users SET totp_last_step = NULL WHERE email = 'aus@firma.test'")
        return totp.code_at(geheimnis, totp.current_step())

    andere, _ = client(settings, engines)
    login(andere, "aus@firma.test")
    andere.post("/api/v1/auth/mfa", json={"code": frischer_code()})
    assert andere.get("/api/v1/auth/session").status_code == 200
    c, _ = client(settings, engines)
    login(c, "aus@firma.test")
    c.post("/api/v1/auth/mfa", json={"code": frischer_code()})
    r = c.post("/api/v1/auth/2fa/disable", json={"password": PASSWORT, "code": frischer_code()})
    assert r.status_code == 204, r.text
    assert andere.get("/api/v1/auth/session").status_code == 401 and c.get("/api/v1/auth/session").status_code == 200


# ---- B1: Wieder eingeladen ⇒ ohne alte Rechte -----------------------------------------------------------------
def test_wiedereintritt_ohne_alte_rollen(world: World, engines: Engines, settings: Settings) -> None:
    from tests.test_m3_tenancy import ADMIN, _mitglied, _sitzung, _token
    _mitglied(world, engines, settings, world.a.id, "chef@alpha.test", ADMIN)          # bleibt Admin
    _mitglied(world, engines, settings, world.a.id, "ex@alpha.test", ADMIN)
    _mitglied(world, engines, settings, world.a.id, "einlader@alpha.test", ["users.create", "users.read"])
    ex, _ = _sitzung(settings, engines, "ex@alpha.test", world.a.id)
    assert ex.post("/api/v1/membership/leave").status_code == 204
    einlader, mailer = _sitzung(settings, engines, "einlader@alpha.test", world.a.id)
    assert einlader.post("/api/v1/invitations", json={"email": "ex@alpha.test"}).status_code == 201
    zurueck, _ = client(settings, engines)
    login(zurueck, "ex@alpha.test")
    assert zurueck.post("/api/v1/invitations/accept-existing", json={"token": _token(mailer)}).status_code == 201
    assert zurueck.post("/api/v1/auth/tenant", json={"tenant_id": str(world.a.id)}).status_code == 200
    rechte: Any = zurueck.get("/api/v1/me").json()
    assert "roles.assign" not in str(rechte) and "users.create" not in str(rechte), rechte
    assert db(engines, "SELECT count(*) FROM membership_roles mr JOIN memberships m ON m.id = mr.membership_id "
                       "JOIN users u ON u.id = m.user_id WHERE u.email = 'ex@alpha.test'") == [(0,)]


# ---- B5: Selbstprüfung sichtbar -------------------------------------------------------------------------------
def test_selbstpruefung_eines_belegs_ist_sichtbar(engines: Engines, settings: Settings, world: World) -> None:
    from tests.core_helpers import CoreWorld
    cw = CoreWorld(world, engines, settings)
    c = cw.client(cw.mitarbeiter)
    r = c.post("/api/v1/documents?filename=b.pdf", content=b"%PDF-1.4 x", headers={"content-type": "application/pdf"})
    ref = r.json()["id"]
    db(engines, "UPDATE documents SET scan_status = 'clean'")
    assert c.post(f"/api/v1/documents/{ref}/review", json={"decision": "approved"}).status_code == 200
    assert db(engines, "SELECT data->>'self_review' FROM audit_events WHERE action = 'document.reviewed'") == [("true",)]


# ---- B4: Cursor verrät keine interne UUID und ist nicht fälschbar ----------------------------------------------
def test_cursor_verschluesselt_und_manipulationssicher() -> None:
    import base64
    import uuid
    from datetime import UTC, datetime

    import pytest
    from sqlalchemy import column

    from ichq.core.errors import ValidationFailed
    from ichq.db.paging import SortKey, configure_cursor_key, decode_cursor, encode_cursor
    configure_cursor_key("x" * 48)
    sort, rid, jetzt = SortKey("created_at", column("c"), "ts"), uuid.uuid4(), datetime.now(UTC)
    c = encode_cursor(sort, True, jetzt, rid)
    roh = base64.urlsafe_b64decode(c + "=" * (-len(c) % 4))
    assert rid.hex.encode() not in roh and b"created_at" not in roh
    assert decode_cursor(c, sort, True) == (jetzt, rid)
    kaputt = c[:-2] + ("A" if c[-2] != "A" else "B") + c[-1]
    with pytest.raises(ValidationFailed):
        decode_cursor(kaputt, sort, True)
    klar = base64.urlsafe_b64encode(f'{{"s":"created_at","d":true,"v":"{jetzt.isoformat()}","i":"{rid.hex}"}}'
                                    .encode()).decode()
    with pytest.raises(ValidationFailed):
        decode_cursor(klar, sort, True)                      # unverschlüsselter (selbst gebauter) Cursor


# ---- B2: Upload-Grenzen je Mitglied und Firma ------------------------------------------------------------------
def test_upload_rate_und_kontingent(engines: Engines, settings: Settings, world: World,
                                    monkeypatch: Any) -> None:
    from ichq.documents import service as dokumente
    from tests.core_helpers import CoreWorld
    cw = CoreWorld(world, engines, settings)
    c = cw.client(cw.mitarbeiter)

    def hoch() -> Any:
        return c.post("/api/v1/documents?filename=b.txt", content=b"x", headers={"content-type": "text/plain"})

    monkeypatch.setattr(dokumente, "UPLOADS_PER_MEMBER_HOUR", 2)
    assert hoch().status_code == 201 and hoch().status_code == 201
    assert hoch().status_code == 429
    db(engines, "UPDATE objects SET created_at = created_at - interval '2 hours'")
    monkeypatch.setattr(dokumente, "TENANT_QUOTA_BYTES", 2)
    r = hoch()
    assert r.status_code == 413 and r.json()["code"] == "storage_quota_exceeded"


# ---- F6/F7: Einladung — Passwort wörtlich, kein verwaistes Konto -----------------------------------------------
def test_einladung_passwort_mit_rand_und_kein_verwaistes_konto(world: World, engines: Engines, settings: Settings,
                                                             monkeypatch: Any) -> None:
    from ichq.members import accept
    from tests.test_m3_tenancy import ADMIN, _mitglied, _sitzung, _token
    _mitglied(world, engines, settings, world.a.id, "chef@alpha.test", ADMIN)
    chef, mailer = _sitzung(settings, engines, "chef@alpha.test", world.a.id)
    chef.post("/api/v1/invitations", json={"email": "neu@extern.test"})
    erster = _token(mailer)
    original = accept._finden

    def finden_dann_widerrufen(*a: Any) -> Any:                             # Wettlauf: Widerruf mitten im Annehmen
        gefunden = original(*a)
        db(engines, "UPDATE invitations SET revoked_at = now()")
        return gefunden

    monkeypatch.setattr(accept, "_finden", finden_dann_widerrufen)
    monkeypatch.setattr(accept, "_vorab_pruefen", lambda *a: None)
    anon, _ = client(settings, engines)
    pw = "  Rand-Leerzeichen-Wolke-7  "
    r = anon.post("/api/v1/invitations/accept", json={"token": erster, "display_name": "Nina", "password": pw})
    assert r.status_code in (400, 404, 410), r.text
    assert db(engines, "SELECT status, password_hash IS NULL FROM users WHERE email = 'neu@extern.test'") == \
        [("pending", True)]                                                   # nicht aktiv, kein Passwort
    monkeypatch.undo()
    chef.post("/api/v1/invitations", json={"email": "neu@extern.test"})
    r = anon.post("/api/v1/invitations/accept", json={"token": _token(mailer), "display_name": "Nina", "password": pw})
    assert r.status_code == 201, r.text                                       # Rest wird weiterverwendet
    assert login(anon, "neu@extern.test", pw).status_code == 200              # Passwort exakt wie eingegeben


def test_passwort_setzen_hebt_betreibersperre_nicht_auf(engines: Engines, settings: Settings) -> None:
    """Zweite Linie hinter dem Reset: auch ein vom Betreiber gesetztes Passwort (CLI) entsperrt nicht."""
    from ichq.auth.account import set_initial_password, set_status
    uid = make_user(engines, settings, "betrieb-gesperrt@firma.test")
    with auth_transaction(engines.auth) as s:
        set_status(s, uid, "locked", actor="betreiber", reason="Test")
    with auth_transaction(engines.auth) as s:
        assert set_initial_password(s, settings, uid, "Neu-Gesetzt-Wolke-55", actor="betreiber").ok
    assert db(engines, "SELECT status FROM users WHERE id = %s", (uid,)) == [("locked",)]
