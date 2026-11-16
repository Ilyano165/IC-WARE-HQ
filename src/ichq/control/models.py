"""Betreiber der Installation und Einrichtungscodes (ADR-021). Beide Tabellen gehören der Control Plane:
kein Mandantenbezug, nur die Rolle ``ichq_platform`` darf sie lesen und schreiben."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base


class PlatformOperator(Base):
    """Ein Konto, das Firmen anlegen und verwalten darf. Kein Recht innerhalb einer Firma folgt daraus."""

    __tablename__ = "platform_operators"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
                                               primary_key=True)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class PlatformSetupCode(Base):
    """Einmaliger Einrichtungscode — nur als Hash gespeichert, läuft ab, wird beim Einlösen verbraucht."""

    __tablename__ = "platform_setup_codes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("code_hash ~ '^[0-9a-f]{64}$'", name="code_hash_format"),)
