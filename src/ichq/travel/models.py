"""Reisen und Fahrtenbuch (ADR-020 Nr. 8).

Fahrtenbuch: ``trips`` trägt nur die Identität (Fahrzeug, Fahrer); die Fahrtdaten stehen ausschließlich in
``trip_versions`` — nur anhängend (App-Rolle: INSERT/SELECT; Trigger sperrt Ändern/Löschen auch für den Superuser).
Jede Korrektur ist eine neue Version mit Grund und bleibt **in der Fahrt selbst** sichtbar (FG Düsseldorf 24.11.2023,
3 K 1887/22 H(L)). Erfassungszeitpunkt (``recorded_at``) und Fahrtdatum werden getrennt gespeichert und angezeigt.
HQ trifft keine Aussage, ob ein Fahrtenbuch steuerlich ordnungsgemäß ist.

Dienstreisen: Antrag → Genehmigung (``travel.approve``, nie die eigene). Verpflegungspauschalen o. Ä. werden NICHT
berechnet — dafür sind keine amtlichen Werte hinterlegt (CLAUDE.md, Steuerregel 1).
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

PURPOSE = ("business", "private", "commute")
TRAVEL_STATUS = ("draft", "submitted", "approved", "rejected", "cancelled")
USAGE = ("company", "mixed")


def _in(spalte: str, werte: tuple[str, ...]) -> str:
    return f"{spalte} IN ({', '.join(repr(w) for w in werte)})"


class Vehicle(TenantScoped, Base):
    __tablename__ = "vehicles"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    license_plate: Mapped[str] = mapped_column(String(20), nullable=False)
    usage: Mapped[str] = mapped_column(String(8), nullable=False, server_default="mixed")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        UniqueConstraint("tenant_id", "id"),
        UniqueConstraint("tenant_id", "license_plate"),
        CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="public_id_format"),
        CheckConstraint("char_length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("char_length(btrim(license_plate)) > 0", name="plate_not_blank"),
        CheckConstraint(_in("usage", USAGE), name="usage_valid"),
    )


class Trip(TenantScoped, Base):
    """Objekttyp ``trip``: nur Identität. Daten in ``trip_versions``."""

    __tablename__ = "trips"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="trip")
    vehicle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    driver_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        table_fk("vehicle_id", "vehicles"),
        member_fk("driver_membership_id"),
        CheckConstraint("object_type = 'trip'", name="object_type_trip"),
        Index("ix_trips_tenant_vehicle", "tenant_id", "vehicle_id"),
    )


class TripVersion(TenantScoped, Base):
    __tablename__ = "trip_versions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    trip_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    trip_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_km: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_km: Mapped[int] = mapped_column(BigInteger, nullable=False)
    purpose: Mapped[str] = mapped_column(String(10), nullable=False)
    start_place: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    destination: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    reason: Mapped[str] = mapped_column(String(500), nullable=False, server_default="")
    business_partner: Mapped[str] = mapped_column(String(300), nullable=False, server_default="")
    voided: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    change_reason: Mapped[str | None] = mapped_column(String(500))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    recorded_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    __table_args__ = (
        UniqueConstraint("trip_id", "version"),
        table_fk("trip_id", "trips", "RESTRICT"),
        member_fk("recorded_by_membership_id"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("start_km >= 0 AND end_km >= start_km", name="km_ordered"),
        CheckConstraint("end_km - start_km <= 5000", name="km_plausible"),
        CheckConstraint(_in("purpose", PURPOSE), name="purpose_valid"),
        CheckConstraint("(version = 1) = (change_reason IS NULL)", name="change_reason_for_corrections"),
        CheckConstraint("purpose <> 'business' OR voided OR (char_length(btrim(destination)) > 0 "
                        "AND char_length(btrim(reason)) > 0)", name="business_needs_destination_reason"),
        Index("ix_trip_versions_tenant_trip", "tenant_id", "trip_id"),
    )


class Travel(TenantScoped, Base):
    """Objekttyp ``travel`` (Dienstreise) mit Genehmigung."""

    __tablename__ = "travels"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    object_type: Mapped[str] = mapped_column(String(24), nullable=False, server_default="travel")
    traveller_membership_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    destination: Mapped[str] = mapped_column(String(300), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    estimated_cost_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="EUR")
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="draft")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    decision_note: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    __table_args__ = (
        typed_object_fk(),
        UniqueConstraint("tenant_id", "id"),
        member_fk("traveller_membership_id"),
        member_fk("decided_by_membership_id"),
        table_fk("project_id", "projects"),
        CheckConstraint("object_type = 'travel'", name="object_type_travel"),
        CheckConstraint(_in("status", TRAVEL_STATUS), name="status_valid"),
        CheckConstraint("end_date >= start_date", name="dates_ordered"),
        CheckConstraint("estimated_cost_minor IS NULL OR estimated_cost_minor >= 0", name="cost_not_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("char_length(purpose) <= 5000", name="purpose_length"),
        CheckConstraint("status = 'cancelled' OR (status IN ('approved','rejected')) = (decided_at IS NOT NULL)",
                        name="decided_consistent"),                  # Storno behält die frühere Entscheidung
        CheckConstraint("decided_by_membership_id IS NULL OR decided_by_membership_id <> traveller_membership_id",
                        name="no_self_approval"),
        Index("ix_travels_tenant_status", "tenant_id", "status"),
    )
