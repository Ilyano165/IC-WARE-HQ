"""Globales Objektmodell (ADR-008): Supertyp-Tabelle ``objects`` plus typisierte Beziehungen.

* Jedes Fachobjekt hat genau eine Zeile in ``objects``. Die Fachtabelle (``tasks``, ``documents``, …)
  verweist mit ``(tenant_id, id, object_type) → objects(tenant_id, id, type)`` darauf — damit ist der
  Typ durch die Datenbank garantiert, nicht durch eine Konvention.
* Kommentare, Aktivitäten, Verknüpfungen, Freigaben und Benachrichtigungen zeigen per echtem,
  zusammengesetztem Fremdschlüssel auf ``objects`` — keine Spalten der Art ``target_type + target_id``.
* ``public_id`` ist zufällig (128 Bit) und unabhängig vom Primärschlüssel; die API kennt nur sie.
"""
from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ichq.db.base import Base, IdMixin, TenantScoped, TimestampMixin
from ichq.objects.registry import ANY, LINK_TYPES, OBJECT_TYPES

PUBLIC_ID_CHECK = r"public_id ~ '^[0-9a-f]{32}$'"


def new_public_id() -> str:
    return secrets.token_hex(16)


def _in(spalte: str, werte: Iterable[str]) -> str:
    return f"{spalte} IN ({', '.join(repr(w) for w in sorted(werte))})"


def link_rule_sql() -> str:
    """CHECK-Ausdruck aus der Registry. Die Migration enthält eine eingefrorene Kopie."""
    teile = []
    for lt in sorted(LINK_TYPES.values(), key=lambda x: x.code):
        bedingung = [f"link_type = '{lt.code}'"]
        if lt.sources != ANY:
            bedingung.append(_in("source_type", lt.sources))
        if lt.targets != ANY:
            bedingung.append(_in("target_type", lt.targets))
        teile.append("(" + " AND ".join(bedingung) + ")")
    return " OR ".join(teile)


def _mitglied_fk(spalte: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", spalte], ["memberships.tenant_id", "memberships.id"],
                                ondelete=ondelete)


def _objekt_fk(spalte: str, ondelete: str = "RESTRICT") -> ForeignKeyConstraint:
    return ForeignKeyConstraint(["tenant_id", spalte], ["objects.tenant_id", "objects.id"], ondelete=ondelete)


class ObjectRow(IdMixin, TenantScoped, TimestampMixin, Base):
    __tablename__ = "objects"
    type: Mapped[str] = mapped_column(String(24), nullable=False)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, default=new_public_id)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    search_text: Mapped[str | None] = mapped_column(Text)
    search_vector: Mapped[str] = mapped_column(TSVECTOR, Computed(
        "to_tsvector('simple'::regconfig, (title::text || ' '::text) || COALESCE(search_text, ''::text))",
        persisted=True))
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "id", "type"),    # Ziel der Fachtabellen: Typ ist Teil des Schlüssels
        _mitglied_fk("created_by_membership_id"),
        CheckConstraint(_in("type", OBJECT_TYPES), name="type_known"),
        CheckConstraint(PUBLIC_ID_CHECK, name="public_id_format"),
        CheckConstraint("char_length(btrim(title)) > 0", name="title_not_blank"),
        CheckConstraint("search_text IS NULL OR char_length(search_text) <= 4000", name="search_text_length"),
        Index("ix_objects_tenant_type_created", "tenant_id", "type", "created_at"),
        Index("ix_objects_search_vector", "search_vector", postgresql_using="gin"),
    )


class ObjectLink(IdMixin, TenantScoped, Base):
    __tablename__ = "object_links"
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, default=new_public_id)
    link_type: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    target_type: Mapped[str] = mapped_column(String(24), nullable=False)
    created_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "source_id", "source_type"],
                             ["objects.tenant_id", "objects.id", "objects.type"], ondelete="CASCADE"),
        ForeignKeyConstraint(["tenant_id", "target_id", "target_type"],
                             ["objects.tenant_id", "objects.id", "objects.type"], ondelete="CASCADE"),
        _mitglied_fk("created_by_membership_id"),
        UniqueConstraint("tenant_id", "source_id", "target_id", "link_type"),
        CheckConstraint("source_id <> target_id", name="not_self"),
        CheckConstraint(link_rule_sql(), name="rule"),
        CheckConstraint(PUBLIC_ID_CHECK, name="public_id_format"),
        Index("ix_object_links_tenant_target", "tenant_id", "target_id"),
    )


GRANT_SOURCES = ("manual", "task_assignment")


class ObjectGrant(TenantScoped, Base):
    """Freigabe eines Objekts für eine Mitgliedschaft (ADR-009)."""

    __tablename__ = "object_grants"
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # manual = über die API erteilt; task_assignment = automatisch durch Zuweisung (entfällt bei Neuzuweisung)
    source: Mapped[str] = mapped_column(String(24), primary_key=True, server_default="manual")
    granted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        CheckConstraint("source IN ('manual','task_assignment')", name="source_valid"),
        _objekt_fk("object_id", "CASCADE"),
        _mitglied_fk("membership_id", "CASCADE"),
        _mitglied_fk("granted_by_membership_id"),
        Index("ix_object_grants_tenant_membership", "tenant_id", "membership_id"),
    )
