"""Test-Zustellweg: hält Mails im Speicher statt sie zu senden (Produktion: ``ichq.mail.delivery.SmtpProvider``)."""
from __future__ import annotations


class MemoryMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []
        self.html: list[str | None] = []

    def send(self, to: str, subject: str, body_text: str, body_html: str | None = None) -> None:
        self.sent.append((to, subject, body_text))
        self.html.append(body_html)
