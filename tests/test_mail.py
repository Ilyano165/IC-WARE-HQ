"""E-Mail (ichq.mail): Outbox in der Transaktion des Anlasses, Token nur verschlüsselt, Wiederholung, Ablauf, Dedup,
Ratenlimit, Rechte der DB-Rollen, Sicherheitshinweise, echter SMTP-Dialog gegen einen Test-Server, Betreiberwarnung."""
from __future__ import annotations

import re
import socket
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import exc, text

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import auth_transaction, platform_transaction, tenant_transaction
from ichq.mail import templates
from ichq.mail.delivery import SmtpProvider, dispatch_once, retry_failed, status_counts
from ichq.mail.outbox import enqueue
from tests.auth_helpers import PASSWORT, OutboxMailer, client, db, login, make_user


class Kaputt:
    """Zustellweg, der immer scheitert (SMTP-Server weg)."""

    def __init__(self) -> None:
        self.versuche = 0

    def send(self, to: str, subject: str, body_text: str, body_html: str | None = None) -> None:
        self.versuche += 1
        raise ConnectionRefusedError("smtp weg")


def _zeilen(engines: Engines) -> list[Any]:
    return db(engines, "SELECT kind, status, body_text, body_html, body_enc, attempts, recipient FROM mail_outbox "
                       "ORDER BY created_at")


def _mail(n: int = 0) -> templates.Rendered:
    return templates.Rendered(f"Betreff {n}", f"Text {n}", f"<p>HTML {n}</p>")


def _einreihen(engines: Engines, **kw: Any) -> None:
    with platform_transaction(engines.platform) as s:
        enqueue(s, **{"kind": "test", "to": "ziel@firma.test", "mail": _mail(), **kw})


def test_reset_token_nur_verschluesselt_und_nach_versand_geloescht(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "da@firma.test")
    c, mailer = client(settings, engines)
    assert c.post("/api/v1/auth/password-reset/request", json={"login": "da@firma.test"}).status_code == 202
    (kind, status, bt, bh, enc, _, an), = _zeilen(engines)
    assert (kind, status, bt, bh, an) == ("password_reset", "pending", None, None, "da@firma.test")
    assert enc and b"token" not in bytes(enc) and b"reset" not in bytes(enc)           # kein Klartext in der DB
    (_, _, inhalt), = mailer.sent
    token = re.search(r"#token=([A-Za-z0-9_-]+)", inhalt).group(1)  # type: ignore[union-attr]
    assert token.encode() not in bytes(enc)
    assert "/reset#token=" in mailer.speicher.html[-1]  # type: ignore[operator]  # HTML-Teil hat denselben Link
    (_, status, bt, bh, enc, _, _), = _zeilen(engines)
    assert (status, bt, bh, enc) == ("sent", None, None, None)                          # Inhalt nach Versand weg


def test_verschluesselung_an_mail_gebunden(engines: Engines, settings: Settings) -> None:
    """Vertauschte Chiffrate (andere Mail-ID) lassen sich nicht entschlüsseln → Mail scheitert, statt Falsches zu senden."""
    for i in range(2):
        with platform_transaction(engines.platform) as s:
            enqueue(s, kind="test", to=f"z{i}@firma.test", mail=_mail(i),
                    secret_key=settings.secret_key.get_secret_value())
    db(engines, "UPDATE mail_outbox SET body_enc = (SELECT body_enc FROM mail_outbox WHERE recipient = 'z0@firma.test') "
                "WHERE recipient = 'z1@firma.test'")
    mailer = OutboxMailer(settings, engines, nur=None)
    assert [m[0] for m in mailer.alle] == ["z0@firma.test"]
    assert db(engines, "SELECT attempts FROM mail_outbox WHERE recipient = 'z1@firma.test'") == [(1,)]


def test_wiederholung_mit_wartezeit_dann_failed_und_erneut(engines: Engines, settings: Settings) -> None:
    _einreihen(engines)
    kaputt = Kaputt()
    r = dispatch_once(engines, settings, kaputt)
    assert (r.sent, r.retrying, r.failed) == (0, 1, 0)
    warte = db(engines, "SELECT status, attempts, available_at > now() + interval '50 seconds', last_error "
                        "FROM mail_outbox")
    assert warte == [("pending", 1, True, "ConnectionRefusedError: smtp weg")]
    assert dispatch_once(engines, settings, kaputt).claimed == 0                        # noch nicht fällig
    for _ in range(5):                                                                  # Zeit vorspulen
        db(engines, "UPDATE mail_outbox SET available_at = now() - interval '1 second'")
        dispatch_once(engines, settings, kaputt)
    assert kaputt.versuche == 6 and db(engines, "SELECT status FROM mail_outbox") == [("failed",)]
    assert status_counts(engines)["failed"] == 1
    assert retry_failed(engines) == 1
    mailer = OutboxMailer(settings, engines, nur=None)
    assert [m[1] for m in mailer.alle] == ["Betreff 0"] and db(engines, "SELECT status FROM mail_outbox") == [("sent",)]


def test_abgelaufene_mail_wird_nicht_gesendet(engines: Engines, settings: Settings) -> None:
    _einreihen(engines, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    mailer = OutboxMailer(settings, engines, nur=None)
    assert mailer.alle == []
    assert db(engines, "SELECT status, body_text FROM mail_outbox") == [("expired", None)]


def test_dedup(engines: Engines, settings: Settings) -> None:
    _einreihen(engines, dedup_key="x:1")
    _einreihen(engines, dedup_key="x:1")
    _einreihen(engines, dedup_key="x:2")
    assert len(OutboxMailer(settings, engines, nur=None).alle) == 2


def test_ratenlimit_je_empfaenger_stellt_zurueck(engines: Engines, settings: Settings) -> None:
    for i in range(settings.mail_per_recipient_hour + 2):
        _einreihen(engines, mail=_mail(i))
    _einreihen(engines, to="andere@firma.test")
    mailer = OutboxMailer(settings, engines, nur=None)
    assert len(mailer.alle) == settings.mail_per_recipient_hour + 1                     # +1: anderer Empfänger
    assert db(engines, "SELECT count(*) FROM mail_outbox WHERE status = 'pending' "
                       "AND available_at > now() + interval '10 minutes'") == [(2,)]   # zurückgestellt, nicht weg


def test_rollen_duerfen_nur_einfuegen_was_ihnen_zusteht(engines: Engines, world: Any) -> None:
    with pytest.raises(exc.ProgrammingError, match="permission denied"), tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("SELECT count(*) FROM mail_outbox"))                            # App liest keine Mails
    with pytest.raises(exc.ProgrammingError, match="row-level security"), \
            tenant_transaction(engines.app, world.a.id) as s:
        enqueue(s, kind="test", to="x@y.test", mail=_mail(), tenant_id=world.b.id)    # nie für fremde Firma
    with pytest.raises(exc.ProgrammingError, match="row-level security"), auth_transaction(engines.auth) as s:
        enqueue(s, kind="test", to="x@y.test", mail=_mail(), tenant_id=world.a.id)    # Auth nur ohne Firma
    with pytest.raises(exc.ProgrammingError, match="permission denied"), auth_transaction(engines.auth) as s:
        s.execute(text("SELECT recipient FROM mail_outbox"))
    with tenant_transaction(engines.app, world.a.id) as s:
        enqueue(s, kind="test", to="x@y.test", mail=_mail(), tenant_id=world.a.id)
    assert db(engines, "SELECT count(*) FROM mail_outbox") == [(1,)]


def test_einladung_und_mail_atomar(engines: Engines, settings: Settings, world: Any) -> None:
    from tests.api_helpers import make_client
    from tests.m4_helpers import RbacWorld
    rw = RbacWorld(world, engines, settings)
    a, _ = make_client(settings, engines, principal=lambda: rw.principal(rw.admin),
                       mailer=OutboxMailer(settings, engines))
    assert a.post("/api/v1/invitations", json={"email": "neu@extern.test"}).status_code == 201
    assert a.post("/api/v1/invitations", json={"email": "neu@extern.test"}).status_code == 409   # offen: abgelehnt
    assert db(engines, "SELECT kind, tenant_id FROM mail_outbox") == [("invitation", world.a.id)]


def test_sicherheitshinweis_bei_passwortwechsel(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "sicher@firma.test")
    c, mailer = client(settings, engines)
    assert login(c, "sicher@firma.test").status_code == 200
    neu = "Neues-Passwort-Wolke-42"
    assert c.post("/api/v1/auth/password", json={"current_password": PASSWORT, "new_password": neu}).status_code == 200
    hinweise = [m for m in mailer.alle if m[1] == "IC WARE HQ: Passwort geändert"]
    assert len(hinweise) == 1 and hinweise[0][0] == "sicher@firma.test"
    assert PASSWORT not in hinweise[0][2] and neu not in hinweise[0][2]


def test_sperrhinweis_hoechstens_stuendlich(engines: Engines, settings: Settings) -> None:
    make_user(engines, settings, "gesperrt@firma.test")
    c, mailer = client(settings, engines)
    for _ in range(settings.login_max_failures * 3):
        login(c, "gesperrt@firma.test", "falsch-falsch-falsch")
        db(engines, "UPDATE users SET locked_until = now() - interval '1 second' WHERE email = 'gesperrt@firma.test' "
                    "AND locked_until IS NOT NULL")
    assert len([m for m in mailer.alle if m[1] == "IC WARE HQ: Konto vorübergehend gesperrt"]) == 1


def test_html_ist_maskiert() -> None:
    m = templates.alert("<b>x</b>", '<script>alert(1)</script>"', "host")
    assert "<script>" not in m.html and "&lt;script&gt;" in m.html and "<b>x</b>" not in m.html
    r = templates.password_reset('https://h"onmouseover="x', "tok", 30)
    assert 'href="https://h&quot;onmouseover=&quot;x/reset#token=tok"' in r.html


# ---- echter SMTP-Dialog ------------------------------------------------------------------------------------------

class SmtpServer:
    """Minimaler SMTP-Server (RFC 5321) für Tests: nimmt eine Mail an und merkt sich die DATA."""

    def __init__(self) -> None:
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        self.daten: list[bytes] = []
        self.befehle: list[str] = []
        threading.Thread(target=self._dienen, daemon=True).start()

    def _dienen(self) -> None:
        while True:
            try:
                c, _ = self.sock.accept()
            except OSError:
                return
            with c, c.makefile("rb") as f:
                c.sendall(b"220 test ESMTP\r\n")
                while zeile := f.readline():
                    befehl = zeile.decode().strip()
                    self.befehle.append(befehl.split(" ")[0].upper())
                    if befehl.upper().startswith("EHLO"):
                        c.sendall(b"250-test\r\n250 8BITMIME\r\n")
                    elif befehl.upper() == "DATA":
                        c.sendall(b"354 go\r\n")
                        teile = []
                        while (z := f.readline()) != b".\r\n":
                            teile.append(z)
                        self.daten.append(b"".join(teile))
                        c.sendall(b"250 ok\r\n")
                    elif befehl.upper() == "QUIT":
                        c.sendall(b"221 bye\r\n")
                        break
                    else:
                        c.sendall(b"250 ok\r\n")

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def smtp() -> Iterator[SmtpServer]:
    s = SmtpServer()
    yield s
    s.close()


def test_smtp_dialog_mit_text_und_html(engines: Engines, settings: Settings, smtp: SmtpServer) -> None:
    cfg = settings.model_copy(update={"smtp_host": "127.0.0.1", "smtp_port": smtp.port, "smtp_starttls": False,
                                      "smtp_from": "hq@firma.test"})
    _einreihen(engines, mail=templates.security_notice("totp_enabled"))
    assert dispatch_once(engines, cfg, SmtpProvider(cfg)).sent == 1
    roh = smtp.daten[0].decode()
    assert "MAIL" in smtp.befehle and "RCPT" in smtp.befehle
    assert "To: ziel@firma.test" in roh and "From: hq@firma.test" in roh and "Auto-Submitted: auto-generated" in roh
    assert "multipart/alternative" in roh and "text/plain" in roh and "text/html" in roh


def test_smtp_ausfall_ist_wiederholbarer_fehler(engines: Engines, settings: Settings) -> None:
    frei = socket.socket()
    frei.bind(("127.0.0.1", 0))
    port = frei.getsockname()[1]
    frei.close()                                                                      # niemand hört auf diesem Port
    cfg = settings.model_copy(update={"smtp_host": "127.0.0.1", "smtp_port": port, "smtp_starttls": False,
                                      "smtp_from": "hq@firma.test"})
    _einreihen(engines)
    assert dispatch_once(engines, cfg, SmtpProvider(cfg)).retrying == 1


def test_smtp_anmeldung_nur_verschluesselt(db_name: str, tmp_path: Any) -> None:
    from tests.conftest import make_settings
    s = make_settings(db_name, tmp_path)
    with pytest.raises(ValueError, match="nur verschlüsselt"):
        s.model_validate({**s.model_dump(), "smtp_host": "mail.test", "smtp_user": "u", "smtp_starttls": False})


# ---- Betreiberwarnung -----------------------------------------------------------------------------------------

def test_alert_ueber_outbox_und_direkt_wenn_db_weg(engines: Engines, settings: Settings) -> None:
    from ichq import betrieb
    from ichq.auth.mailer import MemoryMailer
    from ichq.db.engine import build_engines
    cfg = settings.model_copy(update={"alert_email": "betrieb@firma.test"})
    assert betrieb.alert(cfg, engines, "Backup überfällig", "seit 30 h", "backup-alt") == 0
    assert betrieb.alert(cfg, engines, "Backup überfällig", "seit 30 h", "backup-alt") == 0   # dedup
    assert db(engines, "SELECT kind, recipient FROM mail_outbox") == [("alert", "betrieb@firma.test")]
    tot = cfg.model_copy(update={"platform_database_url": cfg.platform_database_url.__class__(
        "postgresql+psycopg://ichq_platform:x@127.0.0.1:1/nirgends")})
    kaputte = build_engines(tot)
    direkt = MemoryMailer()
    try:
        assert betrieb.alert(tot, kaputte, "DB weg", "keine Verbindung", None, provider=direkt) == 0
    finally:
        kaputte.dispose()
    assert direkt.sent[0][0] == "betrieb@firma.test" and "DB weg" in direkt.sent[0][1]
    assert betrieb.alert(settings, engines, "x", "y", None) == 2                      # ohne Adresse: klarer Fehler
