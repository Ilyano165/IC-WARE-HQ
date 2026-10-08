"""Tabellen der Anmeldung. Kein Geheimnis liegt hier im Klartext:
Sitzungs-, Reset- und Recovery-Tokens nur als Hash, 2FA-Geheimnisse verschlüsselt (an ``users``)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin


class AuthSessionRow(IdMixin, Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)      # mfa_pending | full
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    active_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    mfa_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                   nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (
        CheckConstraint("stage IN ('mfa_pending','full')", name="stage_valid"),
        CheckConstraint("(active_tenant_id IS NULL) = (active_membership_id IS NULL)", name="tenant_pair"),
        CheckConstraint("stage = 'full' OR active_tenant_id IS NULL", name="no_tenant_before_mfa"),
        Index("ix_auth_sessions_user_active", "user_id", postgresql_where=text("revoked_at IS NULL")),
    )


class PasswordResetToken(IdMixin, Base):
    __tablename__ = "password_reset_tokens"
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RecoveryCode(IdMixin, Base):
    __tablename__ = "recovery_codes"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
                                               nullable=False, index=True)
    code_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LoginAttempt(IdMixin, Base):
    """Fehlversuche je IP und je Login-Name. Der Login-Name steht nur als HMAC, nie im Klartext."""

    __tablename__ = "login_attempts"
    kind: Mapped[str] = mapped_column(String(16), nullable=False)       # login | reset | mfa
    subject_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)
    ip: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  nullable=False)
    __table_args__ = (
        CheckConstraint("kind IN ('login','reset','mfa')", name="kind_valid"),
        Index("ix_login_attempts_subject", "kind", "subject_hash", "occurred_at"),
        Index("ix_login_attempts_ip", "kind", "ip", "occurred_at"),
    )


class AuthEvent(IdMixin, Base):
    """Sicherheitsprotokoll der Anmeldung. Nur anhängend (Datenbank-Trigger)."""

    __tablename__ = "auth_events"
    event: Mapped[str] = mapped_column(String(60), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    request_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  nullable=False, index=True)
    __table_args__ = (CheckConstraint(r"event ~ '^[a-z][a-z0-9_.]{2,59}$'", name="event_format"),)
