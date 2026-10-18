"""Fristen (Objekttyp ``deadline``, ADR-020 Nr. 10).

HQ gibt keine Fristen vor. Auch Steuerfristen legt die Firma selbst an; die Quelle (Fundstelle) ist Freitext und wird
von HQ nicht geprüft. Ohne Quelle zeigt die Oberfläche „nicht amtlich bestätigt“ (CLAUDE.md, Steuerregel 1).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, TenantScoped
from ichq.objects.fach import member_fk, table_fk, typed_object_fk

CATEGORY = ("tax", "contract", "payroll", "insurance", "authority", "other")
RECURRENCE = ("none", "monthly", "quarterly", "yearly")
DEADLINE_STATUS = ("open", "done", "cancelled")
MAX_TEXT = 5_000


def _in(spalte: str, werte: tuple[str, ...]) -> str:
    return f"{spalte} IN ({', '.join(repr(w) for w in werte)})"


class Deadline(TenantScoped, Base):
    __tablename__ = "deadlines"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="deadline")
    due_on: Mapped[date] = mapped_column(Date, nullable=False)
    category: Mapped[str] = mapped_column(String(12), nullable=False, server_default="other")
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    source_reference: Mapped[str | None] = mapped_column(String(500))
    responsible_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    remind_days_before: Mapped[int] = mapped_column(Integer, nullable=False, server_default="7")
    recurrence: Mapped[str] = mapped_column(String(10), nullable=False, server_default="none")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    done_note: Mapped[str | None] = mapped_column(String(500))
    follows_deadline_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "follows_deadline_id"),
        member_fk("responsible_membership_id"),
        member_fk("done_by_membership_id"),
        table_fk("follows_deadline_id", "deadlines"),
        CheckConstraint("object_type = 'deadline'", name="object_type_deadline"),
        CheckConstraint(_in("category", CATEGORY), name="category_valid"),
        CheckConstraint(_in("recurrence", RECURRENCE), name="recurrence_valid"),
        CheckConstraint(_in("status", DEADLINE_STATUS), name="status_valid"),
        CheckConstraint("remind_days_before BETWEEN 0 AND 365", name="remind_range"),
        CheckConstraint(f"char_length(description) <= {MAX_TEXT}", name="description_length"),
        CheckConstraint("(status = 'open') = (done_at IS NULL)", name="done_consistent"),
        Index("ix_deadlines_tenant_status_due", "tenant_id", "status", "due_on"),
    )
