from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped, TimestampMixin

USER_STATUS = ("pending", "active", "locked", "suspended", "deactivated")


class User(IdMixin, TimestampMixin, Base):
    """Ein Konto. Firmen sehen per RLS nur Konten, die bei ihnen Mitglied sind — und nur die
    Stammdaten-Spalten. Passwort-Hash und 2FA-Geheimnis liest ausschließlich die Rolle ichq_auth."""

    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    username: Mapped[str | None] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    password_hash: Mapped[str | None] = mapped_column(String(255))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_pending_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    totp_last_step: Mapped[int | None] = mapped_column(BigInteger)
    __table_args__ = (
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        Index("uq_users_username_lower", text("lower(username)"), unique=True),
        CheckConstraint("status IN ('pending','active','locked','suspended','deactivated')", name="status_valid"),
        CheckConstraint("position('@' in email) > 1", name="email_shape"),
        CheckConstraint(r"username IS NULL OR username ~ '^[a-z0-9][a-z0-9._-]{2,31}$'", name="username_format"),
        CheckConstraint("password_hash IS NULL OR password_hash LIKE '$argon2id$%'", name="password_argon2id"),
        CheckConstraint("status <> 'active' OR password_hash IS NOT NULL", name="active_needs_password"),
        CheckConstraint("failed_logins >= 0", name="failed_logins_positive"),
    )


class Membership(IdMixin, TenantScoped, TimestampMixin, Base):
    __tablename__ = "memberships"
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"),
                                               nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="active")
    title: Mapped[str | None] = mapped_column(String(120))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),          # Ziel zusammengesetzter Fremdschlüssel
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint("status IN ('invited','active','suspended','left')", name="status_valid"),
    )
