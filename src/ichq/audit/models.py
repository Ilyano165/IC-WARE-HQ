from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped


class AuditEvent(IdMixin, TenantScoped, Base):
    """Audit einer Firma. UPDATE und DELETE verhindert ein Datenbank-Trigger."""

    __tablename__ = "audit_events"
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    target_type: Mapped[str | None] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(80))
    request_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "actor_membership_id"],
                             ["memberships.tenant_id", "memberships.id"], ondelete="RESTRICT"),
        CheckConstraint(r"action ~ '^[a-z][a-z0-9_.]{2,79}$'", name="action_format"),
        Index("ix_audit_events_tenant_time", "tenant_id", "occurred_at"),
    )


class PlatformAuditEvent(IdMixin, Base):
    """Audit der Control Plane. Ebenfalls nur anhängend."""

    __tablename__ = "platform_audit_events"
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    request_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  nullable=False, index=True)
    __table_args__ = (CheckConstraint(r"action ~ '^[a-z][a-z0-9_.]{2,79}$'", name="action_format"),)
