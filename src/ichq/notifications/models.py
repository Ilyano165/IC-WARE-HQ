from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped
from ichq.objects.models import PUBLIC_ID_CHECK, new_public_id

CHANNELS = ("in_app", "email", "push")


class Notification(IdMixin, TenantScoped, Base):
    """Eine zugestellte Benachrichtigung. Nur Titel + Objektbezug, keine Beträge (M0)."""

    __tablename__ = "notifications"
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, default=new_public_id)
    recipient_membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, server_default="in_app")
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    dedup_key: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "recipient_membership_id"], ["memberships.tenant_id", "memberships.id"],
                             ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "object_id"], ["objects.tenant_id", "objects.id"], ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "recipient_membership_id", "dedup_key"),
        CheckConstraint(r"kind ~ '^[a-z][a-z_]*\.[a-z][a-z_]*$'", name="kind_format"),
        CheckConstraint("channel IN ('in_app','email','push')", name="channel_valid"),
        CheckConstraint(PUBLIC_ID_CHECK, name="public_id_format"),
        Index("ix_notifications_tenant_recipient_created", "tenant_id", "recipient_membership_id", "created_at"),
    )
