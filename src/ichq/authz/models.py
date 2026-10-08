"""Rollen-Tabellen. In M1 nur Schema + Lesen; Verwaltung, Vorlagen und Delegationsregeln folgen in M4."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped, TimestampMixin


class Role(IdMixin, TenantScoped, TimestampMixin, Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint("priority BETWEEN 1 AND 999", name="priority_range"),
    )


class RolePermission(TenantScoped, Base):
    __tablename__ = "role_permissions"
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], ondelete="CASCADE"),
        CheckConstraint(r"permission ~ '^[a-z][a-z_]*(\.[a-z][a-z_]*)+$'", name="permission_format"),
    )


class MembershipRole(TenantScoped, Base):
    __tablename__ = "membership_roles"
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "membership_id"], ["memberships.tenant_id", "memberships.id"],
                             ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], ondelete="CASCADE"),
    )
