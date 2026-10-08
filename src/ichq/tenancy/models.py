from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TimestampMixin

TENANT_STATUS = ("pending", "active", "paused", "suspended", "deactivated")


class Tenant(IdMixin, TimestampMixin, Base):
    """Eine Firma. Gehört der Control Plane; die Mandantenebene sieht per RLS nur die eigene Zeile."""

    __tablename__ = "tenants"
    slug: Mapped[str] = mapped_column(String(48), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Europe/Berlin")
    language: Mapped[str] = mapped_column(String(8), nullable=False, server_default="de")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    plan_code: Mapped[str | None] = mapped_column(String(32))
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(r"slug ~ '^[a-z0-9](?:[a-z0-9-]{1,46})[a-z0-9]$'", name="slug_format"),
        CheckConstraint("status IN ('pending','active','paused','suspended','deactivated')", name="status_valid"),
        CheckConstraint(r"currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("char_length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("deletion_scheduled_for IS NULL OR deletion_requested_at IS NOT NULL",
                        name="deletion_order"),
    )
