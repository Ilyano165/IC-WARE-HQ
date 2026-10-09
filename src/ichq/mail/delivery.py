"""Versand aus ``mail_outbox`` (Worker-Rolle). Mindestens-einmal-Zustellung:

* Abholen mit ``FOR UPDATE SKIP LOCKED`` (mehrere Worker kollidieren nicht); hängende ``sending`` nach 10 min zurück.
* Fehler: Wartezeit 1, 4, 16, 64 … min (max. 6 h), nach ``max_attempts`` ⇒ ``failed`` (Monitoring meldet das;
  ``ichq mail-retry`` stellt erneut zu).
* Abgelaufene Mails (Token-Gültigkeit vorbei) werden nicht mehr gesendet ⇒ ``expired``.
* Je Empfänger höchstens ``mail_per_recipient_hour`` je Stunde — darüber zurückgestellt, nicht verworfen.
* Nach Versand/Ablauf wird der Inhalt gelöscht. Logs enthalten nie Empfänger, Betreff-Token oder Inhalt.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Protocol

from sqlalchemy import text

from ichq.core.config import Settings
from ichq.core.logging import redact_text
from ichq.db.engine import Engines
from ichq.db.session import worker_transaction
from ichq.mail.outbox import unseal

log = logging.getLogger("ichq.mail")
STALE_MINUTES = 10


class Provider(Protocol):
    def send(self, to: str, subject: str, body_text: str, body_html: str | None) -> None:
        """Wirft bei jedem Fehler — der Aufrufer entscheidet über Wiederholung."""


class SmtpProvider:
    def __init__(self, settings: Settings) -> None:
        if not (settings.smtp_host and settings.smtp_from):
            raise ValueError("SMTP nicht eingerichtet (ICHQ_SMTP_HOST, ICHQ_SMTP_FROM)")
        self.s = settings

    def send(self, to: str, subject: str, body_text: str, body_html: str | None) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, to, subject
        msg["Message-ID"] = make_msgid(domain=(self.s.smtp_from or "ichq").rsplit("@", 1)[-1].strip("> "))
        msg["Auto-Submitted"] = "auto-generated"
        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype="html")
        kontext = ssl.create_default_context()
        klasse = smtplib.SMTP_SSL if self.s.smtp_ssl else smtplib.SMTP
        kw = {"context": kontext} if self.s.smtp_ssl else {}
        with klasse(self.s.smtp_host or "", self.s.smtp_port, timeout=20, **kw) as smtp:  # type: ignore[arg-type]
            if self.s.smtp_starttls and not self.s.smtp_ssl:
                smtp.starttls(context=kontext)
            if self.s.smtp_user and self.s.smtp_password:
                smtp.login(self.s.smtp_user, self.s.smtp_password.get_secret_value())
            smtp.send_message(msg)


def build_provider(settings: Settings) -> Provider | None:
    return SmtpProvider(settings) if settings.smtp_host and settings.smtp_from else None


@dataclass
class MailRun:
    sent: int = 0
    retrying: int = 0
    failed: int = 0
    expired: int = 0
    deferred: int = 0

    @property
    def claimed(self) -> int:
        return self.sent + self.retrying + self.failed + self.deferred


def _anzahl(res: object) -> int:
    return int(getattr(res, "rowcount", 0) or 0)


def _wartezeit(versuch: int) -> int:
    return int(min(60 * 4 ** max(versuch - 1, 0), 6 * 3600))


def dispatch_once(engines: Engines, settings: Settings, provider: Provider, limit: int = 20) -> MailRun:
    lauf = MailRun()
    with worker_transaction(engines.worker) as s:
        s.execute(text("UPDATE mail_outbox SET status='pending', locked_at=NULL WHERE status='sending' "
                       "AND locked_at < now() - make_interval(mins => :m)"), {"m": STALE_MINUTES})
        lauf.expired = _anzahl(s.execute(text(
            "UPDATE mail_outbox SET status='expired', body_enc=NULL, body_text=NULL, body_html=NULL "
            "WHERE status IN ('pending','failed') AND expires_at IS NOT NULL AND expires_at < now()")))
        zeilen = s.execute(text("""
            UPDATE mail_outbox SET status='sending', locked_at=now(), attempts=attempts+1
            WHERE id IN (SELECT id FROM mail_outbox WHERE status='pending' AND available_at <= now()
                         ORDER BY available_at, id FOR UPDATE SKIP LOCKED LIMIT :n)
            RETURNING id, recipient, subject, body_text, body_html, body_enc, attempts, max_attempts"""),
            {"n": limit}).all()
    for z in zeilen:
        _eine(engines, settings, provider, z, lauf)
    return lauf


def _eine(engines: Engines, settings: Settings, provider: Provider, z: object, lauf: MailRun) -> None:
    mid: uuid.UUID = z.id  # type: ignore[attr-defined]
    with worker_transaction(engines.worker) as s:
        schon = s.execute(text("SELECT count(*) FROM mail_outbox WHERE lower(recipient) = lower(:r) "
                               "AND status = 'sent' AND sent_at > now() - interval '1 hour'"),
                          {"r": z.recipient}).scalar_one()  # type: ignore[attr-defined]
        if schon >= settings.mail_per_recipient_hour:
            s.execute(text("UPDATE mail_outbox SET status='pending', locked_at=NULL, attempts=attempts-1, "
                           "available_at = now() + interval '15 minutes' WHERE id=:id"), {"id": mid})
            lauf.deferred += 1
            log.warning("mail_zurueckgestellt_ratenlimit", extra={"mail_id": str(mid)})
            return
    try:
        if z.body_enc is not None:  # type: ignore[attr-defined]
            body_text, body_html = unseal(settings.secret_key.get_secret_value(), mid,
                                          z.body_enc)  # type: ignore[attr-defined]
        else:
            body_text, body_html = z.body_text, z.body_html  # type: ignore[attr-defined]
        provider.send(z.recipient, z.subject, body_text, body_html)  # type: ignore[attr-defined]
    except Exception as e:   # Art des Fehlers speichern, nie Inhalt/Empfänger
        endgueltig = z.attempts >= z.max_attempts  # type: ignore[attr-defined]
        with worker_transaction(engines.worker) as s:
            s.execute(text("""UPDATE mail_outbox SET status=:st, locked_at=NULL, last_error=:err,
                              available_at = now() + make_interval(secs => :w) WHERE id=:id"""),
                      {"st": "failed" if endgueltig else "pending", "id": mid,
                       "err": redact_text(f"{e.__class__.__name__}: {e}")[:300],
                       "w": _wartezeit(z.attempts)})  # type: ignore[attr-defined]
        if endgueltig:
            lauf.failed += 1
        else:
            lauf.retrying += 1
        log.error("mail_versand_fehlgeschlagen", extra={"mail_id": str(mid), "exc_type": e.__class__.__name__,
                                                       "endgueltig": endgueltig})
        return
    with worker_transaction(engines.worker) as s:
        s.execute(text("UPDATE mail_outbox SET status='sent', sent_at=now(), locked_at=NULL, last_error=NULL, "
                       "body_enc=NULL, body_text=NULL, body_html=NULL WHERE id=:id"), {"id": mid})
    lauf.sent += 1
    log.info("mail_versendet", extra={"mail_id": str(mid)})


def retry_failed(engines: Engines, mail_id: uuid.UUID | None = None) -> int:
    """Fehlgeschlagene Mails erneut zustellen (nur solche mit Inhalt, d. h. nicht abgelaufen)."""
    with worker_transaction(engines.worker) as s:
        sql = ("UPDATE mail_outbox SET status='pending', attempts=0, available_at=now(), last_error=NULL "
               "WHERE status='failed' AND (body_enc IS NOT NULL OR body_text IS NOT NULL)")
        if mail_id is not None:
            return _anzahl(s.execute(text(sql + " AND id = :id"), {"id": mail_id}))
        return _anzahl(s.execute(text(sql)))


def status_counts(engines: Engines) -> dict[str, int]:
    with worker_transaction(engines.worker) as s:
        zeilen = s.execute(text("SELECT status, count(*) FROM mail_outbox GROUP BY status")).all()
        alt = s.execute(text("SELECT coalesce(extract(epoch FROM now() - min(created_at))::int, 0) "
                             "FROM mail_outbox WHERE status = 'pending'")).scalar_one()
    d = {str(k): int(v) for k, v in zeilen}
    d["oldest_pending_seconds"] = int(alt)
    return d
