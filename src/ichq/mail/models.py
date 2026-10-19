"""Tabelle ``mail_outbox``: jede ausgehende Mail, geschrieben in derselben Transaktion wie ihr Anlass.

Systemtabelle (wie ``auth_events``): ``tenant_id`` ist bei Einladungen gesetzt, bei Konto-Mails (Reset,
Sicherheitshinweise) und Betreiberwarnungen leer. RLS mit FORCE: App-Rolle darf nur für die eigene Firma
einfügen, Auth-Rolle nur ohne Firma; lesen und ändern dürfen nur Worker und Plattform (Migration 0008).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin

STATUS = ("pending", "sending", "sent", "failed", "expired", "cancelled")


class MailOutbox(IdMixin, Base):
    __tablename__ = "mail_outbox"
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id",
                                                                                        ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    recipient: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text)          # nur Mails ohne Geheimnis
    body_html: Mapped[str | None] = mapped_column(Text)
    body_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # Mails mit Token: AES-GCM, nach Versand gelöscht
    dedup_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="6")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                   nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('pending','sending','sent','failed','expired','cancelled')", name="status_valid"),
        CheckConstraint(r"kind ~ '^[a-z][a-z0-9_.]{2,39}$'", name="kind_format"),
        CheckConstraint("attempts >= 0 AND max_attempts BETWEEN 1 AND 20", name="attempts_range"),
        CheckConstraint("status NOT IN ('pending','sending') OR body_enc IS NOT NULL OR body_text IS NOT NULL",
                        name="body_present"),
        CheckConstraint("body_enc IS NULL OR (body_text IS NULL AND body_html IS NULL)", name="body_one_form"),
        Index("ix_mail_outbox_due", "available_at", postgresql_where=text("status = 'pending'")),
        Index("ix_mail_outbox_recipient_sent", "recipient", "sent_at"),
    )
