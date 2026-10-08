from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKeyConstraint, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, TenantScoped

TASK_STATUS = ("open", "in_progress", "blocked", "done", "cancelled")
TASK_PRIORITY = ("low", "normal", "high", "urgent")
MAX_DESCRIPTION = 20_000


class Task(TenantScoped, Base):
    """Fachtabelle zum Objekttyp ``task``. Titel und Ersteller stehen in ``objects``."""

    __tablename__ = "tasks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="task")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    priority: Mapped[str] = mapped_column(String(8), nullable=False, server_default="normal")
    assignee_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    due_date: Mapped[date | None] = mapped_column(Date)
    subject_object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_comment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "id", "object_type"], ["objects.tenant_id", "objects.id", "objects.type"],
                             ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "assignee_membership_id"], ["memberships.tenant_id", "memberships.id"],
                             ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "subject_object_id"], ["objects.tenant_id", "objects.id"],
                             ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "source_comment_id"], ["comments.tenant_id", "comments.id"],
                             ondelete="RESTRICT"),
        CheckConstraint("object_type = 'task'", name="object_type_task"),
        CheckConstraint("status IN ('open','in_progress','blocked','done','cancelled')", name="status_valid"),
        CheckConstraint("priority IN ('low','normal','high','urgent')", name="priority_valid"),
        CheckConstraint(f"char_length(description) <= {MAX_DESCRIPTION}", name="description_length"),
        CheckConstraint("subject_object_id IS NULL OR subject_object_id <> id", name="subject_not_self"),
        Index("ix_tasks_tenant_assignee", "tenant_id", "assignee_membership_id"),
        Index("ix_tasks_tenant_status_due", "tenant_id", "status", "due_date"),
    )
