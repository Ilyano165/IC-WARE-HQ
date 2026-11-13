"""Rechnungen, Positionen, Nummernkreis, Zahlungen, Mahn-/Kontakthistorie, Versandhistorie (ADR-020).

Nach dem Ausstellen schützt die DATENBANK die Rechnung (Trigger, Migration 0011): Beträge, Positionen, Kunde, Datum
und Nummer sind unveränderlich; Korrektur nur per Stornorechnung. Historien-Tabellen sind nur anhängend.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, TenantScoped
from ichq.objects.fach import member_fk, table_fk, typed_object_fk

INVOICE_STATUS = ("draft", "issued", "sent", "partially_paid", "paid", "cancelled")
INVOICE_OPEN = ("issued", "sent", "partially_paid")           # Forderung offen (wenn Restbetrag > 0)
INVOICE_KIND = ("invoice", "cancellation")
FOLLOWUP_KIND = ("contact_attempt", "reminder_noted", "dunning_level", "note")
CHANNELS = ("phone", "email", "letter", "in_person", "other")
PAYMENT_METHOD = ("bank_transfer", "cash", "card", "direct_debit", "other")
MAX_TEXT = 5_000


class Invoice(TenantScoped, Base):
    __tablename__ = "invoices"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="invoice")
    kind: Mapped[str] = mapped_column(String(14), nullable=False, server_default="invoice")
    cancels_invoice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    number: Mapped[str | None] = mapped_column(String(40))
    issue_date: Mapped[date | None] = mapped_column(Date)
    service_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    gross_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    customer_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    responsible_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    dunning_level: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    next_follow_up: Mapped[date | None] = mapped_column(Date)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "number"),
        UniqueConstraint("tenant_id", "cancels_invoice_id"),        # höchstens ein Storno je Rechnung
        table_fk("cancels_invoice_id", "invoices"),
        table_fk("customer_id", "customers"),
        table_fk("project_id", "projects"),
        member_fk("responsible_membership_id"),
        member_fk("issued_by_membership_id"),
        CheckConstraint("object_type = 'invoice'", name="object_type_invoice"),
        CheckConstraint("status IN ('draft','issued','sent','partially_paid','paid','cancelled')", name="status_valid"),
        CheckConstraint("kind IN ('invoice','cancellation')", name="kind_valid"),
        CheckConstraint("(kind = 'cancellation') = (cancels_invoice_id IS NOT NULL)", name="cancellation_ref"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("gross_minor = net_minor + tax_minor", name="gross_is_sum"),
        CheckConstraint("(status = 'draft') = (number IS NULL)", name="number_iff_issued"),
        CheckConstraint("status = 'draft' OR (issue_date IS NOT NULL AND issued_at IS NOT NULL "
                        "AND customer_id IS NOT NULL AND due_date IS NOT NULL)", name="issued_complete"),
        CheckConstraint("due_date IS NULL OR issue_date IS NULL OR due_date >= issue_date", name="due_after_issue"),
        CheckConstraint("dunning_level BETWEEN 0 AND 9", name="dunning_level_range"),
        CheckConstraint(f"char_length(notes) <= {MAX_TEXT}", name="notes_length"),
        Index("ix_invoices_tenant_status_due", "tenant_id", "status", "due_date"),
        Index("ix_invoices_tenant_customer", "tenant_id", "customer_id"),
        Index("ix_invoices_tenant_project", "tenant_id", "project_id"),
    )


class InvoiceLine(TenantScoped, Base):
    """Menge in Tausendsteln, Einzelpreis in Cent, Steuersatz in Basispunkten (vom Nutzer erfasst, kein Standard)."""

    __tablename__ = "invoice_lines"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    quantity_milli: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(20))
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_rate_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    __table_args__ = (
        table_fk("invoice_id", "invoices", "CASCADE"),
        UniqueConstraint("invoice_id", "position"),
        CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="public_id_format"),
        CheckConstraint("char_length(btrim(description)) > 0", name="description_not_blank"),
        CheckConstraint("quantity_milli <> 0", name="quantity_not_zero"),
        CheckConstraint("tax_rate_bp BETWEEN 0 AND 10000", name="tax_rate_range"),
        Index("ix_invoice_lines_tenant_invoice", "tenant_id", "invoice_id"),
    )


class InvoiceNumberCounter(TenantScoped, Base):
    """Nummernkreis je Firma und Jahr — die Zeilensperre serialisiert parallele Ausstellungen (lückenlos)."""

    __tablename__ = "invoice_number_counters"
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False)
    prefix: Mapped[str] = mapped_column(String(12), nullable=False, server_default="RE-")
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "year"),
        CheckConstraint("next_value >= 1", name="next_value_positive"),
        CheckConstraint(r"prefix ~ '^[A-Za-z0-9\-_/]{0,12}$'", name="prefix_format"),
    )


class Payment(TenantScoped, Base):
    """Zahlungseingang zu einer Rechnung (Objekttyp ``payment``). Kein Bankabgleich — manuell erfasst. Eine falsch
    erfasste Zahlung wird nie gelöscht, sondern per Gegenbuchung (``reverses_payment_id``, negativer Betrag)
    aufgehoben."""

    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="payment")
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False, server_default="bank_transfer")
    reference: Mapped[str | None] = mapped_column(String(200))
    reverses_payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "reverses_payment_id"),      # jede Zahlung höchstens einmal zurückgenommen
        table_fk("invoice_id", "invoices"),
        table_fk("reverses_payment_id", "payments"),
        CheckConstraint("object_type = 'payment'", name="object_type_payment"),
        CheckConstraint("(reverses_payment_id IS NULL AND amount_minor > 0) OR "
                        "(reverses_payment_id IS NOT NULL AND amount_minor < 0)", name="amount_sign"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("method IN ('bank_transfer','cash','card','direct_debit','other')", name="method_valid"),
        Index("ix_payments_tenant_invoice", "tenant_id", "invoice_id"),
        Index("ix_payments_tenant_paid_on", "tenant_id", "paid_on"),
    )


class InvoiceFollowup(TenantScoped, Base):
    """Kontaktversuch, notierte Erinnerung, Mahnstufe oder Notiz — nur anhängend (Bearbeitungshistorie)."""

    __tablename__ = "invoice_followups"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(String(MAX_TEXT), nullable=False, server_default="")
    dunning_level: Mapped[int | None] = mapped_column(Integer)
    next_follow_up: Mapped[date | None] = mapped_column(Date)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        table_fk("invoice_id", "invoices", "CASCADE"),
        member_fk("created_by_membership_id"),
        CheckConstraint("kind IN ('contact_attempt','reminder_noted','dunning_level','note')", name="kind_valid"),
        CheckConstraint("channel IS NULL OR channel IN ('phone','email','letter','in_person','other')",
                        name="channel_valid"),
        CheckConstraint("dunning_level IS NULL OR dunning_level BETWEEN 0 AND 9", name="dunning_level_range"),
        Index("ix_invoice_followups_tenant_invoice", "tenant_id", "invoice_id"),
    )


class InvoiceDispatch(TenantScoped, Base):
    """Versand-/Exporthistorie: wer hat wann wie verschickt, gedruckt oder exportiert — nur anhängend."""

    __tablename__ = "invoice_dispatches"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(10))
    note: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        table_fk("invoice_id", "invoices", "CASCADE"),
        member_fk("created_by_membership_id"),
        CheckConstraint("action IN ('sent','printed','exported')", name="action_valid"),
        CheckConstraint("channel IS NULL OR channel IN ('phone','email','letter','in_person','other')",
                        name="channel_valid"),
        Index("ix_invoice_dispatches_tenant_invoice", "tenant_id", "invoice_id"),
    )
