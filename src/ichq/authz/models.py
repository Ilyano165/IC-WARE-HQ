"""Rollen, Einzelrechte und Feature-Flags (M1-Schema, M4-Verwaltung — ADR-011)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped, TimestampMixin


class Role(IdMixin, TenantScoped, TimestampMixin, Base):
    __tablename__ = "roles"
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")   # Rang, höher = mächtiger
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # Gesperrte Systemrolle „Company Admin": Rechte werden berechnet (alle der Registry), nie gespeichert
    grants_all: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True,
                                           server_default=text("replace(gen_random_uuid()::text, '-', '')"))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "name"),
        CheckConstraint("priority BETWEEN 1 AND 999", name="priority_range"),
        CheckConstraint("NOT grants_all OR is_system", name="grants_all_is_system"),
        CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="public_id_format"),
        Index("uq_roles_one_grants_all", "tenant_id", unique=True, postgresql_where=text("grants_all")),
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


def _mitglied_fk(spalte: str, ondelete: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", spalte], ["memberships.tenant_id", "memberships.id"], ondelete=ondelete)


class PermissionOverride(TenantScoped, Base):
    """Einzelrecht je Mitgliedschaft: ``allow`` gilt zusätzlich zu Rollen, ``deny`` schlägt jede Rolle.
    Wer es gesetzt hat, steht im Mandanten-Audit (``permission.override_set``)."""

    __tablename__ = "permission_overrides"
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    permission: Mapped[str] = mapped_column(String(64), primary_key=True)
    effect: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        _mitglied_fk("membership_id", "CASCADE"),
        CheckConstraint("effect IN ('allow','deny')", name="effect_valid"),
        CheckConstraint(r"permission ~ '^[a-z][a-z_]*(\.[a-z][a-z_]*)+$'", name="permission_format"),
    )


class FeatureFlag(TenantScoped, Base):
    """Modul je Firma an/aus. Schreibt nur die Control Plane (ichq_platform)."""

    __tablename__ = "tenant_feature_flags"
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_by: Mapped[str] = mapped_column(String(120), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "module"),
        CheckConstraint("module ~ '^[a-z][a-z_]*$'", name="module_format"),
    )
