"""Benutzeraktivität — NICHT das Audit.

| | Aktivität (``activities``) | Audit (``audit_events``) |
| --- | --- | --- |
| Zweck | lesbarer Verlauf für Nutzer („Beleg geprüft") | Nachweis für Prüfung und Sicherheit |
| Sichtbar | wer das Objekt sehen darf + ``activity.read`` | nur ``audit.read`` |
| Inhalt | knapp, ohne Beträge/Texte | vollständig (geschwärzt) |
| Änderbar | nur anhängend (keine UPDATE/DELETE-Rechte) | nur anhängend + Trigger gegen UPDATE/DELETE/TRUNCATE |

Beide werden in derselben Transaktion wie die fachliche Änderung geschrieben.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped


class Activity(IdMixin, TenantScoped, Base):
    __tablename__ = "activities"
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    verb: Mapped[str] = mapped_column(String(48), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(),
                                                  nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "object_id"], ["objects.tenant_id", "objects.id"], ondelete="RESTRICT"),
        ForeignKeyConstraint(["tenant_id", "actor_membership_id"], ["memberships.tenant_id", "memberships.id"],
                             ondelete="RESTRICT"),
        CheckConstraint(r"verb ~ '^[a-z][a-z_]*\.[a-z][a-z_]*$'", name="verb_format"),
        Index("ix_activities_tenant_time", "tenant_id", "occurred_at", "id"),
        Index("ix_activities_tenant_object_time", "tenant_id", "object_id", "occurred_at"),
    )
