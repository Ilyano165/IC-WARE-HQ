"""Fahrzeuge, Fahrtenbuch (Fahrten nur als Versionen) und Dienstreisen mit Genehmigung (ADR-020 Nr. 8).

Revision: 0016_travel_logbook
Vorgänger: 0015_month_close_export
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.namen import kurz

revision = "0016_travel_logbook"
down_revision = "0015_month_close_export"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TABLES = ["vehicles", "trips", "trip_versions", "travels"]


def _tenant(table: str) -> list[sa.schema.SchemaItem]:
    return [sa.Column("tenant_id", UUID, nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                    name=f"fk_{table}_tenant_id_tenants")]


def _typed(table: str, typ: str) -> list[sa.schema.SchemaItem]:
    return [sa.Column("object_type", sa.String(24), nullable=False, server_default=typ),
            sa.ForeignKeyConstraint(["tenant_id", "id", "object_type"],
                                    ["objects.tenant_id", "objects.id", "objects.type"], ondelete="CASCADE",
                                    name=kurz(f"fk_{table}_tenant_id_id_object_type_objects")),
            sa.CheckConstraint(f"object_type = '{typ}'", name=kurz(f"ck_{table}_object_type_{typ}"))]


def _mfk(table: str, col: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], ["memberships.tenant_id", "memberships.id"],
                                   ondelete="RESTRICT", name=kurz(f"fk_{table}_tenant_id_{col}_memberships"))


def _tfk(table: str, col: str, ziel: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], [f"{ziel}.tenant_id", f"{ziel}.id"], ondelete="RESTRICT",
                                   name=kurz(f"fk_{table}_tenant_id_{col}_{ziel}"))


def _ck(table: str, name: str, sql: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sql, name=kurz(f"ck_{table}_{name}"))


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", UUID, primary_key=True), *_tenant("vehicles"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("license_plate", sa.String(20), nullable=False),
        sa.Column("usage", sa.String(8), nullable=False, server_default="mixed"),
        sa.Column("archived_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_vehicles"),
        sa.UniqueConstraint("public_id", name="uq_vehicles_public_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_vehicles_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "license_plate", name="uq_vehicles_tenant_id_license_plate"),
        _ck("vehicles", "public_id_format", r"public_id ~ '^[0-9a-f]{32}$'"),
        _ck("vehicles", "name_not_blank", "char_length(btrim(name)) > 0"),
        _ck("vehicles", "plate_not_blank", "char_length(btrim(license_plate)) > 0"),
        _ck("vehicles", "usage_valid", "usage IN ('company', 'mixed')"),
    )
    op.create_index("ix_vehicles_tenant_id", "vehicles", ["tenant_id"])
    op.create_table(
        "trips",
        sa.Column("id", UUID, primary_key=True), *_tenant("trips"), *_typed("trips", "trip"),
        sa.Column("vehicle_id", UUID, nullable=False),
        sa.Column("driver_membership_id", UUID),
        sa.PrimaryKeyConstraint("id", name="pk_trips"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_trips_tenant_id_id"),
        _tfk("trips", "vehicle_id", "vehicles"),
        _mfk("trips", "driver_membership_id"),
    )
    op.create_index("ix_trips_tenant_id", "trips", ["tenant_id"])
    op.create_index("ix_trips_tenant_vehicle", "trips", ["tenant_id", "vehicle_id"])
    op.create_table(
        "trip_versions",
        sa.Column("id", UUID, primary_key=True), *_tenant("trip_versions"),
        sa.Column("trip_id", UUID, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("trip_date", sa.Date, nullable=False),
        sa.Column("start_km", sa.BigInteger, nullable=False),
        sa.Column("end_km", sa.BigInteger, nullable=False),
        sa.Column("purpose", sa.String(10), nullable=False),
        sa.Column("start_place", sa.String(200), nullable=False, server_default=""),
        sa.Column("destination", sa.String(300), nullable=False, server_default=""),
        sa.Column("reason", sa.String(500), nullable=False, server_default=""),
        sa.Column("business_partner", sa.String(300), nullable=False, server_default=""),
        sa.Column("voided", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("change_reason", sa.String(500)),
        sa.Column("recorded_at", TS, nullable=False, server_default=NOW),
        sa.Column("recorded_by_membership_id", UUID),
        sa.PrimaryKeyConstraint("id", name="pk_trip_versions"),
        sa.UniqueConstraint("trip_id", "version", name="uq_trip_versions_trip_id_version"),
        _tfk("trip_versions", "trip_id", "trips"),
        _mfk("trip_versions", "recorded_by_membership_id"),
        _ck("trip_versions", "version_positive", "version >= 1"),
        _ck("trip_versions", "km_ordered", "start_km >= 0 AND end_km >= start_km"),
        _ck("trip_versions", "km_plausible", "end_km - start_km <= 5000"),
        _ck("trip_versions", "purpose_valid", "purpose IN ('business', 'private', 'commute')"),
        _ck("trip_versions", "change_reason_for_corrections", "(version = 1) = (change_reason IS NULL)"),
        _ck("trip_versions", "business_needs_destination_reason",
            "purpose <> 'business' OR voided OR (char_length(btrim(destination)) > 0 "
            "AND char_length(btrim(reason)) > 0)"),
    )
    op.create_index("ix_trip_versions_tenant_id", "trip_versions", ["tenant_id"])
    op.create_index("ix_trip_versions_tenant_trip", "trip_versions", ["tenant_id", "trip_id"])
    op.create_table(
        "travels",
        sa.Column("id", UUID, primary_key=True), *_tenant("travels"), *_typed("travels", "travel"),
        sa.Column("traveller_membership_id", UUID, nullable=False),
        sa.Column("destination", sa.String(300), nullable=False),
        sa.Column("purpose", sa.Text, nullable=False, server_default=""),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("project_id", UUID),
        sa.Column("estimated_cost_minor", sa.BigInteger),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("submitted_at", TS),
        sa.Column("decided_at", TS),
        sa.Column("decided_by_membership_id", UUID),
        sa.Column("decision_note", sa.String(500)),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_travels"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_travels_tenant_id_id"),
        _mfk("travels", "traveller_membership_id"),
        _mfk("travels", "decided_by_membership_id"),
        _tfk("travels", "project_id", "projects"),
        _ck("travels", "status_valid", "status IN ('draft', 'submitted', 'approved', 'rejected', 'cancelled')"),
        _ck("travels", "dates_ordered", "end_date >= start_date"),
        _ck("travels", "cost_not_negative", "estimated_cost_minor IS NULL OR estimated_cost_minor >= 0"),
        _ck("travels", "currency_format", "currency ~ '^[A-Z]{3}$'"),
        _ck("travels", "purpose_length", "char_length(purpose) <= 5000"),
        _ck("travels", "decided_consistent", "status = 'cancelled' OR (status IN ('approved','rejected')) = (decided_at IS NOT NULL)"),
        _ck("travels", "no_self_approval",
            "decided_by_membership_id IS NULL OR decided_by_membership_id <> traveller_membership_id"),
    )
    op.create_index("ix_travels_tenant_id", "travels", ["tenant_id"])
    op.create_index("ix_travels_tenant_status", "travels", ["tenant_id", "status"])
    for t in TABLES:
        op.execute(f"""
        REVOKE ALL ON {t} FROM PUBLIC;
        GRANT SELECT, INSERT ON {t} TO ichq_app;
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_{t}_tenant ON {t} TO ichq_app
          USING (tenant_id = ichq_current_tenant()) WITH CHECK (tenant_id = ichq_current_tenant());
        """)
    op.execute("""
    GRANT UPDATE (name, usage, archived_at) ON vehicles TO ichq_app;
    GRANT UPDATE (destination, purpose, start_date, end_date, project_id, estimated_cost_minor, currency, status,
                  submitted_at, decided_at, decided_by_membership_id, decision_note) ON travels TO ichq_app;
    CREATE TRIGGER trg_travels_updated_at BEFORE UPDATE ON travels
      FOR EACH ROW EXECUTE FUNCTION ichq_set_updated_at();

    -- Fahrtenbuch: Versionen sind unveränderlich (auch für den Superuser), Versionen lückenlos ab 1,
    -- und eine Fahrt in einem abgeschlossenen Monat bekommt keine neue Version (Periodensperre, 0015).
    CREATE FUNCTION ichq_trip_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE letzte int; alt date;
    BEGIN
      IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'ichq: Fahrtenbuch-Einträge sind unveränderlich — Korrektur als neue Version';
      END IF;
      SELECT max(version) INTO letzte FROM trip_versions WHERE trip_id = NEW.trip_id;
      IF NEW.version <> coalesce(letzte, 0) + 1 THEN
        RAISE EXCEPTION 'ichq: Fahrt-Version muss % sein', coalesce(letzte, 0) + 1;
      END IF;
      SELECT trip_date INTO alt FROM trip_versions WHERE trip_id = NEW.trip_id AND version = letzte;
      IF ichq_period_closed(NEW.tenant_id, NEW.trip_date) OR ichq_period_closed(NEW.tenant_id, alt) THEN
        RAISE EXCEPTION 'ichq: Monat der Fahrt ist abgeschlossen';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_trip_versions_guard BEFORE INSERT OR UPDATE OR DELETE ON trip_versions
      FOR EACH ROW EXECUTE FUNCTION ichq_trip_version_guard();
    CREATE FUNCTION ichq_trip_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'ichq: Fahrten werden nicht geändert oder gelöscht — stornieren als neue Version';
    END $$;
    CREATE TRIGGER trg_trips_guard BEFORE UPDATE OR DELETE ON trips
      FOR EACH ROW EXECUTE FUNCTION ichq_trip_guard();
    """)


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
    op.execute("DROP FUNCTION ichq_trip_version_guard(); DROP FUNCTION ichq_trip_guard();")
