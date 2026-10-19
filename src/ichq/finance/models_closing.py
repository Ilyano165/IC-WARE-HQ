"""Monatsabschluss und Export-Historie (ADR-020 Nr. 7 und 11). Sperre und Unveränderbarkeit erzwingt die Datenbank
(Migration 0015); diese Modelle bilden nur die Tabellen ab."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, TenantScoped
from ichq.objects.fach import member_fk, table_fk

EXPORT_FORMATS = ("ichq-buchungen-v1",)


class MonthClose(TenantScoped, Base):
    __tablename__ = "month_closes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    period: Mapped[date] = mapped_column(Date, nullable=False)
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closed_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    close_note: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reopened_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reopen_reason: Mapped[str | None] = mapped_column(String(500))
    __table_args__ = (
        member_fk("closed_by_membership_id"),
        member_fk("reopened_by_membership_id"),
        CheckConstraint("extract(day FROM period) = 1", name="period_first_day"),
        CheckConstraint("(reopened_at IS NULL) = (reopen_reason IS NULL)", name="reopen_consistent"),
        Index("uq_month_closes_active", "tenant_id", "period", unique=True,
              postgresql_where=text("reopened_at IS NULL")),
    )


class Export(TenantScoped, Base):
    __tablename__ = "exports"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    format: Mapped[str] = mapped_column(String(24), nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    repeats_export_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        table_fk("repeats_export_id", "exports"),
        member_fk("created_by_membership_id"),
        CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="public_id_format"),
        CheckConstraint("format IN ('ichq-buchungen-v1')", name="format_valid"),
        CheckConstraint("period_to >= period_from", name="range_ordered"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_format"),
    )
