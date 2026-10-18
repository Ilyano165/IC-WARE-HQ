"""Verträge (Objekttyp ``contract``, ADR-020).

Ein Vertrag in HQ ist eine Verwaltungsakte: Partei, Laufzeit, Kündigungsfrist, Kosten, Dokumente (als Anhang).
Termine wie „kündbar bis“ rechnet HQ nur aus den eingegebenen Werten — das ist keine rechtliche Prüfung, und ein
hochgeladenes Dokument wird nicht ausgewertet.
"""
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

CONTRACT_STATUS = ("draft", "active", "terminated")
UNITS = ("days", "weeks", "months")
BILLING = ("none", "once", "monthly", "quarterly", "yearly")
MAX_NOTES = 20_000


def _in(spalte: str, werte: tuple[str, ...]) -> str:
    return f"{spalte} IN ({', '.join(repr(w) for w in werte)})"


class Contract(TenantScoped, Base):
    __tablename__ = "contracts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="contract")
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    counterparty_name: Mapped[str | None] = mapped_column(String(200))
    contract_type: Mapped[str | None] = mapped_column(String(60))
    reference: Mapped[str | None] = mapped_column(String(100))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    notice_value: Mapped[int | None] = mapped_column(Integer)
    notice_unit: Mapped[str | None] = mapped_column(String(8))
    auto_renew: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    renewal_months: Mapped[int | None] = mapped_column(Integer)
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    billing: Mapped[str] = mapped_column(String(10), nullable=False, server_default="none")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="active")
    terminated_on: Mapped[date | None] = mapped_column(Date)
    termination_effective_on: Mapped[date | None] = mapped_column(Date)
    termination_note: Mapped[str | None] = mapped_column(String(500))
    responsible_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        table_fk("customer_id", "customers"),
        member_fk("responsible_membership_id"),
        CheckConstraint("object_type = 'contract'", name="object_type_contract"),
        CheckConstraint(_in("status", CONTRACT_STATUS), name="status_valid"),
        CheckConstraint(_in("billing", BILLING), name="billing_valid"),
        CheckConstraint("notice_unit IS NULL OR " + _in("notice_unit", UNITS), name="notice_unit_valid"),
        CheckConstraint("(notice_value IS NULL) = (notice_unit IS NULL)", name="notice_complete"),
        CheckConstraint("notice_value IS NULL OR notice_value BETWEEN 0 AND 3650", name="notice_range"),
        CheckConstraint("renewal_months IS NULL OR renewal_months BETWEEN 1 AND 120", name="renewal_range"),
        CheckConstraint("NOT auto_renew OR renewal_months IS NOT NULL", name="renewal_needs_months"),
        CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date", name="dates_ordered"),
        CheckConstraint("amount_minor IS NULL OR amount_minor >= 0", name="amount_not_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("(status = 'terminated') = (terminated_on IS NOT NULL)", name="terminated_consistent"),
        CheckConstraint(f"char_length(notes) <= {MAX_NOTES}", name="notes_length"),
        Index("ix_contracts_tenant_end", "tenant_id", "end_date"),
        Index("ix_contracts_tenant_customer", "tenant_id", "customer_id"),
    )
