from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped


class OutboxEvent(IdMixin, TenantScoped, Base):
    __tablename__ = "outbox_events"
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                   nullable=False)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                 nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status IN ('pending','processing','done','failed')", name="status_valid"),
        CheckConstraint("attempts >= 0 AND max_attempts BETWEEN 1 AND 50", name="attempts_range"),
        CheckConstraint(r"type ~ '^[a-z][a-z0-9_.]{2,79}$'", name="type_format"),
        Index("ix_outbox_events_due", "available_at", postgresql_where=text("status = 'pending'")),
    )
