"""Ausgaben mit Beleg (Objekttyp ``receipt``) (ADR-020).

Belegprinzip (CLAUDE.md, Steuerregel 4): Eine Ausgabe ohne Belegdokument ist sichtbar „Beleg fehlt" — nie still.
Ein Beleg zählt erst als vorhanden, wenn das Dokument die Virenprüfung bestanden hat (``scan_status = clean``).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
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

PAYMENT_STATUS = ("unpaid", "paid")
MAX_TEXT = 5_000


class Receipt(TenantScoped, Base):
    __tablename__ = "receipts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="receipt")
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_name: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)          # Bruttobetrag, wie auf dem Beleg
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    tax_rate_bp: Mapped[int | None] = mapped_column(Integer)                      # vom Nutzer erfasst, optional
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    responsible_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payment_status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="unpaid")
    paid_on: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    document_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="document")
    missing_reason: Mapped[str | None] = mapped_column(String(500))                # warum (noch) kein Beleg
    follow_up_on: Mapped[date | None] = mapped_column(Date)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))      # storniert (Fehlerfassung)
    void_reason: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        table_fk("project_id", "projects"),
        member_fk("responsible_membership_id"),
        # Beleg = Dokument (Typ durch den Schlüssel garantiert, nicht durch Konvention)
        ForeignKeyConstraint(
            ["tenant_id", "document_id", "document_type"], ["objects.tenant_id", "objects.id", "objects.type"],
            ondelete="RESTRICT"),
        CheckConstraint("object_type = 'receipt'", name="object_type_receipt"),
        CheckConstraint("document_type = 'document'", name="document_type_document"),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("tax_rate_bp IS NULL OR tax_rate_bp BETWEEN 0 AND 10000", name="tax_rate_range"),
        CheckConstraint("payment_status IN ('unpaid','paid')", name="payment_status_valid"),
        CheckConstraint("(payment_status = 'paid') = (paid_on IS NOT NULL)", name="paid_consistent"),
        CheckConstraint(f"char_length(description) <= {MAX_TEXT}", name="description_length"),
        CheckConstraint("(voided_at IS NULL) = (void_reason IS NULL)", name="void_reason_required"),
        Index("ix_receipts_tenant_date", "tenant_id", "expense_date"),
        Index("ix_receipts_tenant_project", "tenant_id", "project_id"),
        Index("ix_receipts_tenant_document", "tenant_id", "document_id"),
    )
