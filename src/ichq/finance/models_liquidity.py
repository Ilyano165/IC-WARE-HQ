"""Liquidität (ADR-020): Konten mit MANUELL gepflegten Ständen und Planposten. Keine Bankanbindung — HQ kennt keinen
Live-Kontostand und behauptet keinen. Stände sind nur anhängend (Historie: wer hat wann welchen Stand erfasst)."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, TenantScoped
from ichq.objects.fach import member_fk, table_fk

ACCOUNT_KIND = ("bank", "cash", "other")
FORECAST_STATUS = ("open", "done", "cancelled")


class LiquidityAccount(TenantScoped, Base):
    __tablename__ = "liquidity_accounts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False, server_default="bank")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="public_id_format"),
        CheckConstraint("char_length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("kind IN ('bank','cash','other')", name="kind_valid"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
    )


class LiquidityBalance(TenantScoped, Base):
    """Ein manuell erfasster Kontostand zu einem Stichtag — nie geändert, nur durch einen neueren ersetzt."""

    __tablename__ = "liquidity_balances"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    balance_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    note: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        table_fk("account_id", "liquidity_accounts"),
        member_fk("created_by_membership_id"),
        Index("ix_liquidity_balances_tenant_account_asof", "tenant_id", "account_id", "as_of"),
    )


class LiquidityForecast(TenantScoped, Base):
    """Planposten: erwartete Ein- (+) oder Auszahlung (−), die (noch) nicht als Rechnung/Ausgabe erfasst ist."""

    __tablename__ = "liquidity_forecasts"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    expected_on: Mapped[date] = mapped_column(Date, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str | None] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        member_fk("created_by_membership_id"),
        CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="public_id_format"),
        CheckConstraint("amount_minor <> 0", name="amount_not_zero"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("status IN ('open','done','cancelled')", name="status_valid"),
        CheckConstraint("char_length(btrim(label)) > 0", name="label_not_blank"),
        Index("ix_liquidity_forecasts_tenant_expected", "tenant_id", "expected_on"),
    )
