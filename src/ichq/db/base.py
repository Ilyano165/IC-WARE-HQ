"""Gemeinsame Basis für alle Tabellen.

* Einheitliche Namen für Constraints und Indizes (Alembic-Vergleich bleibt stabil).
* ``TenantScoped`` gibt einer Tabelle ``tenant_id NOT NULL`` mit Fremdschlüssel und Index.
  Verweise zwischen Mandantentabellen laufen über zusammengesetzte Fremdschlüssel
  ``(tenant_id, x_id) → (tenant_id, id)`` — siehe docs/architecture.md.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from ichq.core.ids import uuid7

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class IdMixin:
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class TenantScoped:
    """Markiert eine Tabelle als mandantengebunden. Die Migration aktiviert dafür RLS."""

    __tenant_scoped__ = True

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="RESTRICT"),
                             nullable=False, index=True)
