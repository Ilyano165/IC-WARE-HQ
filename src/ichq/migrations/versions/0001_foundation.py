"""M1 Foundation: Firmen, Konten, Mitgliedschaften, Rollen-Schema, Audit, Outbox, Row-Level Security.

Revision: 0001_foundation
Vorgänger: —

Datenbankrollen (müssen vorher existieren, siehe deploy/postgres/init-roles.sql):
  ichq_owner    besitzt die Tabellen, führt Migrationen aus — wird zur Laufzeit NIE benutzt
  ichq_app      Mandantenebene: nur mit app.tenant_id, RLS erzwungen
  ichq_platform Control Plane: Firmen, Konten, Plattform-Audit — keine Mandantendaten
  ichq_worker   Outbox abholen und markieren — sonst nichts
"""
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0001_foundation"
down_revision = None
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TENANT_TABLES = ["memberships", "roles", "role_permissions", "membership_roles", "audit_events", "outbox_events"]


def _ts() -> list[sa.Column[datetime]]:
    return [sa.Column("created_at", TS, server_default=NOW, nullable=False),
            sa.Column("updated_at", TS, server_default=NOW, nullable=False)]




def upgrade() -> None:
    op.execute("""
    DO $$
    DECLARE r text;
    BEGIN
      FOREACH r IN ARRAY ARRAY['ichq_app','ichq_platform','ichq_worker'] LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
          RAISE EXCEPTION 'Datenbankrolle % fehlt — zuerst deploy/postgres/init-roles.sql ausführen', r;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r AND (rolsuper OR rolbypassrls)) THEN
          RAISE EXCEPTION 'Rolle % darf weder SUPERUSER noch BYPASSRLS sein', r;
        END IF;
      END LOOP;
    END $$;
    """)

    # --- Hilfsfunktionen ---------------------------------------------------
    op.execute("""
    CREATE FUNCTION ichq_current_tenant() RETURNS uuid
      LANGUAGE sql STABLE AS
      $$ SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid $$;
    COMMENT ON FUNCTION ichq_current_tenant() IS
      'Mandant der laufenden Transaktion (SET LOCAL app.tenant_id). Leer → NULL → RLS liefert nichts.';

    CREATE FUNCTION ichq_set_updated_at() RETURNS trigger LANGUAGE plpgsql AS
      $$ BEGIN NEW.updated_at := now(); RETURN NEW; END $$;

    CREATE FUNCTION ichq_append_only() RETURNS trigger LANGUAGE plpgsql AS
      $$ BEGIN RAISE EXCEPTION 'Tabelle % ist nur anhängend (%)', TG_TABLE_NAME, TG_OP
         USING ERRCODE = 'insufficient_privilege'; END $$;
    """)

    # --- Tabellen ----------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("slug", sa.String(48), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("legal_name", sa.String(200)),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Berlin"),
        sa.Column("language", sa.String(8), nullable=False, server_default="de"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("plan_code", sa.String(32)),
        sa.Column("deletion_requested_at", TS),
        sa.Column("deletion_scheduled_for", TS),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
        sa.CheckConstraint(r"slug ~ '^[a-z0-9](?:[a-z0-9-]{1,46})[a-z0-9]$'", name="ck_tenants_slug_format"),
        sa.CheckConstraint("status IN ('pending','active','paused','suspended','deactivated')",
                           name="ck_tenants_status_valid"),
        sa.CheckConstraint(r"currency ~ '^[A-Z]{3}$'", name="ck_tenants_currency_format"),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_tenants_name_not_blank"),
        sa.CheckConstraint("deletion_scheduled_for IS NULL OR deletion_requested_at IS NOT NULL",
                           name="ck_tenants_deletion_order"),
    )

    op.create_table(
        "users",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("password_hash", sa.String(255)),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_users_status_valid"),
        sa.CheckConstraint("position('@' in email) > 1", name="ck_users_email_shape"),
    )
    op.create_index("uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True)

    op.create_table(
        "memberships",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("title", sa.String(120)),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                name="fk_memberships_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT",
                                name="fk_memberships_user_id_users"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_memberships_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_id_user_id"),
        sa.CheckConstraint("status IN ('invited','active','suspended','left')", name="ck_memberships_status_valid"),
    )
    op.create_index("ix_memberships_tenant_id", "memberships", ["tenant_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    op.create_table(
        "roles",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.Column("priority", sa.Integer, nullable=False, server_default="10"),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("archived_at", TS),
        *_ts(),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                name="fk_roles_tenant_id_tenants"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_roles_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_id_name"),
        sa.CheckConstraint("priority BETWEEN 1 AND 999", name="ck_roles_priority_range"),
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])

    op.create_table(
        "role_permissions",
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("role_id", UUID, nullable=False),
        sa.Column("permission", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("role_id", "permission", name="pk_role_permissions"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                name="fk_role_permissions_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], ondelete="CASCADE",
                                name="fk_role_permissions_tenant_id_role_id_roles"),
        sa.CheckConstraint(r"permission ~ '^[a-z][a-z_]*(\.[a-z][a-z_]*)+$'",
                           name="ck_role_permissions_permission_format"),
    )
    op.create_index("ix_role_permissions_tenant_id", "role_permissions", ["tenant_id"])

    op.create_table(
        "membership_roles",
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column("role_id", UUID, nullable=False),
        sa.PrimaryKeyConstraint("membership_id", "role_id", name="pk_membership_roles"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                name="fk_membership_roles_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["tenant_id", "membership_id"], ["memberships.tenant_id", "memberships.id"],
                                ondelete="CASCADE", name="fk_membership_roles_tenant_id_membership_id_memberships"),
        sa.ForeignKeyConstraint(["tenant_id", "role_id"], ["roles.tenant_id", "roles.id"], ondelete="CASCADE",
                                name="fk_membership_roles_tenant_id_role_id_roles"),
    )
    op.create_index("ix_membership_roles_tenant_id", "membership_roles", ["tenant_id"])

    op.create_table(
        "audit_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("actor_membership_id", UUID),
        sa.Column("target_type", sa.String(40)),
        sa.Column("target_id", sa.String(80)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("data", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("occurred_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                name="fk_audit_events_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["tenant_id", "actor_membership_id"], ["memberships.tenant_id", "memberships.id"],
                                ondelete="RESTRICT",
                                name="fk_audit_events_tenant_id_actor_membership_id_memberships"),
        sa.CheckConstraint(r"action ~ '^[a-z][a-z0-9_.]{2,79}$'", name="ck_audit_events_action_format"),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_events_tenant_time", "audit_events", ["tenant_id", "occurred_at"])

    op.create_table(
        "platform_audit_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("actor", sa.String(120), nullable=False),
        sa.Column("tenant_id", UUID),
        sa.Column("request_id", sa.String(64)),
        sa.Column("data", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("occurred_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_platform_audit_events"),
        sa.CheckConstraint(r"action ~ '^[a-z][a-z0-9_.]{2,79}$'", name="ck_platform_audit_events_action_format"),
    )
    op.create_index("ix_platform_audit_events_occurred_at", "platform_audit_events", ["occurred_at"])

    op.create_table(
        "outbox_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("payload", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="5"),
        sa.Column("available_at", TS, server_default=NOW, nullable=False),
        sa.Column("locked_at", TS),
        sa.Column("last_error", sa.Text),
        sa.Column("request_id", sa.String(64)),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("processed_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_outbox_events"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                name="fk_outbox_events_tenant_id_tenants"),
        sa.CheckConstraint("status IN ('pending','processing','done','failed')", name="ck_outbox_events_status_valid"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts BETWEEN 1 AND 50", name="ck_outbox_events_attempts_range"),
        sa.CheckConstraint(r"type ~ '^[a-z][a-z0-9_.]{2,79}$'", name="ck_outbox_events_type_format"),
    )
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"])
    op.create_index("ix_outbox_events_due", "outbox_events", ["available_at"],
                    postgresql_where=sa.text("status = 'pending'"))

    # --- Trigger -----------------------------------------------------------
    for t in ("tenants", "users", "memberships", "roles"):
        op.execute(f"CREATE TRIGGER trg_{t}_updated_at BEFORE UPDATE ON {t} "
                   f"FOR EACH ROW EXECUTE FUNCTION ichq_set_updated_at()")
    for t in ("audit_events", "platform_audit_events"):
        op.execute(f"CREATE TRIGGER trg_{t}_append_only BEFORE UPDATE OR DELETE ON {t} "
                   f"FOR EACH ROW EXECUTE FUNCTION ichq_append_only()")
        op.execute(f"CREATE TRIGGER trg_{t}_no_truncate BEFORE TRUNCATE ON {t} "
                   f"FOR EACH STATEMENT EXECUTE FUNCTION ichq_append_only()")

    # --- Rechte: erst alles weg, dann gezielt geben ------------------------
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO ichq_app, ichq_platform, ichq_worker")
    op.execute("""
    GRANT SELECT ON tenants, users TO ichq_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON memberships, roles, role_permissions, membership_roles TO ichq_app;
    GRANT SELECT, INSERT ON audit_events, outbox_events TO ichq_app;
    GRANT SELECT ON alembic_version TO ichq_app, ichq_platform;

    GRANT SELECT, INSERT, UPDATE ON tenants, users TO ichq_platform;
    GRANT SELECT, INSERT ON platform_audit_events TO ichq_platform;

    GRANT SELECT, UPDATE ON outbox_events TO ichq_worker;
    """)

    # --- Row-Level Security ------------------------------------------------
    for t in [*TENANT_TABLES, "tenants", "users"]:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")   # gilt auch für den Tabellenbesitzer
    for t in ("memberships", "roles", "role_permissions", "membership_roles"):
        op.execute(f"""CREATE POLICY p_{t}_tenant ON {t} TO ichq_app
                       USING (tenant_id = ichq_current_tenant())
                       WITH CHECK (tenant_id = ichq_current_tenant())""")
    for t in ("audit_events", "outbox_events"):
        op.execute(f"CREATE POLICY p_{t}_tenant_read ON {t} FOR SELECT TO ichq_app "
                   f"USING (tenant_id = ichq_current_tenant())")
        op.execute(f"CREATE POLICY p_{t}_tenant_insert ON {t} FOR INSERT TO ichq_app "
                   f"WITH CHECK (tenant_id = ichq_current_tenant())")
    op.execute("""
    CREATE POLICY p_tenants_own ON tenants FOR SELECT TO ichq_app USING (id = ichq_current_tenant());
    CREATE POLICY p_tenants_platform ON tenants TO ichq_platform USING (true) WITH CHECK (true);
    CREATE POLICY p_users_members ON users FOR SELECT TO ichq_app USING (
        EXISTS (SELECT 1 FROM memberships m
                WHERE m.user_id = users.id AND m.tenant_id = ichq_current_tenant()));
    CREATE POLICY p_users_platform ON users TO ichq_platform USING (true) WITH CHECK (true);
    CREATE POLICY p_outbox_worker ON outbox_events TO ichq_worker USING (true) WITH CHECK (true);
    """)


def downgrade() -> None:
    # Policies zuerst: p_users_members auf users hängt an der Tabelle memberships
    op.execute("DROP POLICY IF EXISTS p_users_members ON users")
    for t in ("outbox_events", "platform_audit_events", "audit_events", "membership_roles", "role_permissions",
              "roles", "memberships", "users", "tenants"):
        op.drop_table(t)
    op.execute("DROP FUNCTION IF EXISTS ichq_append_only(), ichq_set_updated_at(), ichq_current_tenant()")
