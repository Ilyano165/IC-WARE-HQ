from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, LargeBinary, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped
from ichq.objects.models import PUBLIC_ID_CHECK, new_public_id


def _mfk(spalte: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", spalte], ["memberships.tenant_id", "memberships.id"],
                                ondelete="RESTRICT")


class Invitation(IdMixin, TenantScoped, Base):
    """Einladung per E-Mail. Der Token steht nur als SHA-256 hier; der Link enthält weder Firma noch E-Mail."""

    __tablename__ = "invitations"
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, default=new_public_id)
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    title: Mapped[str | None] = mapped_column(String(120))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    invited_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        _mfk("invited_by_membership_id"), _mfk("accepted_membership_id"), _mfk("revoked_by_membership_id"),
        CheckConstraint(PUBLIC_ID_CHECK, name="public_id_format"),
        CheckConstraint("position('@' in email) > 1 AND email = lower(email)", name="email_shape"),
        CheckConstraint("octet_length(token_hash) = 32", name="token_hash_length"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        CheckConstraint("NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)", name="one_end"),
        Index("ix_invitations_tenant_created", "tenant_id", "created_at"),
        Index("uq_invitations_open_email", "tenant_id", "email", unique=True,
              postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL")),
    )
