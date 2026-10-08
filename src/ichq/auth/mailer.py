"""E-Mail-Versand für Passwort-Resets. Der Inhalt enthält ein Geheimnis — er wird nie geloggt."""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from ichq.core.config import Settings

log = logging.getLogger("ichq.mail")


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        assert settings.smtp_host and settings.smtp_from
        self.s = settings

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.smtp_from, to, subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.s.smtp_host or "", self.s.smtp_port, timeout=15) as smtp:
                if self.s.smtp_starttls:
                    smtp.starttls(context=ssl.create_default_context())
                if self.s.smtp_user and self.s.smtp_password:
                    smtp.login(self.s.smtp_user, self.s.smtp_password.get_secret_value())
                smtp.send_message(msg)
        except Exception as e:   # nur die Art des Fehlers loggen — nie Empfänger-Inhalt oder Token
            log.error("mail_versand_fehlgeschlagen", extra={"exc_type": e.__class__.__name__})


class MemoryMailer:
    """Für Tests: hält Mails im Speicher statt sie zu senden."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


def build_mailer(settings: Settings) -> Mailer | None:
    return SmtpMailer(settings) if settings.smtp_host and settings.smtp_from else None
