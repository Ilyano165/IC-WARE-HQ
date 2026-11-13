"""Projekte, Projektteam und Projektzeiten (ADR-020). Name/Ersteller stehen in ``objects``."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, TenantScoped
from ichq.objects.fach import member_fk, table_fk, typed_object_fk

PROJECT_STATUS = ("planned", "active", "on_hold", "completed", "cancelled")
PROJECT_OPEN = ("planned", "active", "on_hold")
PRIORITY = ("low", "normal", "high", "urgent")
MAX_TEXT = 20_000
MAX_MINUTES_PER_ENTRY = 24 * 60


class Project(TenantScoped, Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="project")
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="planned")
    priority: Mapped[str] = mapped_column(String(8), nullable=False, server_default="normal")
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    budget_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        table_fk("customer_id", "customers"),
        member_fk("owner_membership_id"),
        CheckConstraint("object_type = 'project'", name="object_type_project"),
        CheckConstraint("status IN ('planned','active','on_hold','completed','cancelled')", name="status_valid"),
        CheckConstraint("priority IN ('low','normal','high','urgent')", name="priority_valid"),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="dates_ordered"),
        CheckConstraint("budget_minor IS NULL OR budget_minor >= 0", name="budget_not_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint(f"char_length(description) <= {MAX_TEXT}", name="description_length"),
        CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)", name="completed_consistent"),
        Index("ix_projects_tenant_status", "tenant_id", "status"),
        Index("ix_projects_tenant_customer", "tenant_id", "customer_id"),
    )


class ProjectMember(TenantScoped, Base):
    """Teammitglied. ``hourly_cost_minor`` = kalkulatorischer Kostensatz je Stunde (nur mit finance.read sichtbar)."""

    __tablename__ = "project_members"
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role: Mapped[str | None] = mapped_column(String(100))
    hourly_cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    added_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        table_fk("project_id", "projects", "CASCADE"),
        member_fk("membership_id", "CASCADE"),
        member_fk("added_by_membership_id"),
        CheckConstraint("hourly_cost_minor IS NULL OR hourly_cost_minor >= 0", name="cost_not_negative"),
        Index("ix_project_members_tenant_membership", "tenant_id", "membership_id"),
    )


class TimeEntry(TenantScoped, Base):
    """Projektzeit (Aufwand je Projekt) — ausdrücklich KEINE Arbeitszeiterfassung im arbeitsrechtlichen Sinn."""

    __tablename__ = "time_entries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    billable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    description: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        table_fk("project_id", "projects", "CASCADE"),
        member_fk("membership_id"),
        member_fk("created_by_membership_id"),
        CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="public_id_format"),
        CheckConstraint(f"minutes > 0 AND minutes <= {MAX_MINUTES_PER_ENTRY}", name="minutes_range"),
        Index("ix_time_entries_tenant_project_date", "tenant_id", "project_id", "work_date"),
    )
