"""Kunden, Kontaktpersonen und Anfragen (ADR-020). Name/Titel und Ersteller stehen in ``objects``."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, TenantScoped
from ichq.objects.fach import member_fk, table_fk, typed_object_fk

CUSTOMER_KIND = ("company", "person")
CUSTOMER_STATUS = ("lead", "active", "inactive")
INQUIRY_STATUS = ("new", "in_progress", "waiting", "won", "lost", "closed")
INQUIRY_OPEN = ("new", "in_progress", "waiting")
INQUIRY_SOURCE = ("email", "phone", "website", "referral", "event", "other")
PRIORITY = ("low", "normal", "high", "urgent")
MAX_NOTES = 20_000


def _in(spalte: str, werte: tuple[str, ...]) -> str:
    return f"{spalte} IN ({', '.join(repr(w) for w in werte)})"


class Customer(TenantScoped, Base):
    """Fachtabelle zum Objekttyp ``customer`` (Firma oder Person). ``dedup_key`` = normalisierter Name."""

    __tablename__ = "customers"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="customer")
    kind: Mapped[str] = mapped_column(String(12), nullable=False, server_default="company")
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="active")
    legal_name: Mapped[str | None] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(300))
    street: Mapped[str | None] = mapped_column(String(200))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(2))
    vat_id: Mapped[str | None] = mapped_column(String(30))
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    dedup_key: Mapped[str] = mapped_column(String(300), nullable=False)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        member_fk("owner_membership_id"),
        table_fk("merged_into_id", "customers"),
        CheckConstraint("object_type = 'customer'", name="object_type_customer"),
        CheckConstraint(_in("kind", CUSTOMER_KIND), name="kind_valid"),
        CheckConstraint(_in("status", CUSTOMER_STATUS), name="status_valid"),
        CheckConstraint("country IS NULL OR country ~ '^[A-Z]{2}$'", name="country_format"),
        CheckConstraint(f"char_length(notes) <= {MAX_NOTES}", name="notes_length"),
        CheckConstraint("merged_into_id IS NULL OR merged_into_id <> id", name="merge_not_self"),
        Index("ix_customers_tenant_dedup", "tenant_id", "dedup_key"),
        Index("ix_customers_tenant_email", "tenant_id", "email"),
    )


class CustomerContact(TenantScoped, Base):
    """Kontaktperson eines Kunden — Stammdaten ohne eigene Sichtbarkeit (sichtbar mit dem Kunden)."""

    __tablename__ = "customer_contacts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str | None] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        table_fk("customer_id", "customers", "CASCADE"),
        CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="public_id_format"),
        CheckConstraint("char_length(btrim(name)) > 0", name="name_not_blank"),
        Index("ix_customer_contacts_tenant_customer", "tenant_id", "customer_id"),
    )


class Inquiry(TenantScoped, Base):
    """Fachtabelle zum Objekttyp ``inquiry`` (Anfrage). Titel in ``objects``."""

    __tablename__ = "inquiries"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="inquiry")
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    source: Mapped[str] = mapped_column(String(12), nullable=False, server_default="other")
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False, server_default="normal")
    status: Mapped[str] = mapped_column(String(12), nullable=False, server_default="new")
    owner_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    next_action: Mapped[str | None] = mapped_column(String(300))
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        table_fk("customer_id", "customers"),
        member_fk("owner_membership_id"),
        CheckConstraint("object_type = 'inquiry'", name="object_type_inquiry"),
        CheckConstraint(_in("status", INQUIRY_STATUS), name="status_valid"),
        CheckConstraint(_in("source", INQUIRY_SOURCE), name="source_valid"),
        CheckConstraint(_in("priority", PRIORITY), name="priority_valid"),
        CheckConstraint(f"char_length(description) <= {MAX_NOTES}", name="description_length"),
        CheckConstraint("(status IN ('won','lost','closed')) = (closed_at IS NOT NULL)", name="closed_consistent"),
        Index("ix_inquiries_tenant_status_follow", "tenant_id", "status", "follow_up_on"),
        Index("ix_inquiries_tenant_customer", "tenant_id", "customer_id"),
    )
