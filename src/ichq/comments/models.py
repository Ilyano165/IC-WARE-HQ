from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped
from ichq.objects.models import PUBLIC_ID_CHECK, new_public_id

COMMENT_KINDS = ("note", "question")
MAX_BODY = 10_000


class Comment(IdMixin, TenantScoped, Base):
    """Kommentar an einem Fachobjekt. Gelöschte Kommentare bleiben als leere Hülle stehen."""

    __tablename__ = "comments"
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, default=new_public_id)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="note")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        ForeignKeyConstraint(["tenant_id", "object_id"], ["objects.tenant_id", "objects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "author_membership_id"], ["memberships.tenant_id", "memberships.id"],
                             ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "deleted_by_membership_id"],
                             ["memberships.tenant_id", "memberships.id"], ondelete="RESTRICT"),
        CheckConstraint("kind IN ('note','question')", name="kind_valid"),
        CheckConstraint(f"char_length(body) <= {MAX_BODY}", name="body_length"),
        CheckConstraint("deleted_at IS NULL OR body = ''", name="deleted_is_empty"),
        CheckConstraint("deleted_at IS NOT NULL OR char_length(btrim(body)) > 0", name="body_not_blank"),
        CheckConstraint(PUBLIC_ID_CHECK, name="public_id_format"),
        Index("ix_comments_tenant_object_created", "tenant_id", "object_id", "created_at"),
    )


class CommentMention(TenantScoped, Base):
    __tablename__ = "comment_mentions"
    comment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "comment_id"], ["comments.tenant_id", "comments.id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "membership_id"], ["memberships.tenant_id", "memberships.id"],
                             ondelete="CASCADE"),
    )
