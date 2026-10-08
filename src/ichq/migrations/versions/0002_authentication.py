"""M2 Authentication: Kontozustände, Sitzungen, Reset-Tokens, 2FA, Anmeldeversuche, Auth-Audit.

Revision: 0002_authentication
Vorgänger: 0001_foundation

Neue Rolle ichq_auth (deploy/postgres/init-roles.sql). Wichtigste Rechteänderung:
App- und Plattform-Rolle sehen an ``users`` nur noch Stammdaten-Spalten — Passwort-Hash
und 2FA-Geheimnis liest allein ichq_auth.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0002_authentication"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
AUTH_TABLES = ("auth_sessions", "password_reset_tokens", "recovery_codes", "login_attempts", "auth_events")
STAMMDATEN = "id, email, username, display_name, status, created_at, updated_at"


def _user_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE", name=f"fk_{name}_user_id_users")


def upgrade() -> None:
    op.execute("""
    DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ichq_auth') THEN
        RAISE EXCEPTION 'Datenbankrolle ichq_auth fehlt — deploy/postgres/init-roles.sql erneut ausführen';
      END IF;
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ichq_auth' AND (rolsuper OR rolbypassrls)) THEN
        RAISE EXCEPTION 'Rolle ichq_auth darf weder SUPERUSER noch BYPASSRLS sein';
      END IF;
    END $$;
    CREATE FUNCTION ichq_current_user() RETURNS uuid LANGUAGE sql STABLE AS
      $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$;
    """)

    # --- Konten ---------------------------------------------------------------
    op.drop_constraint("ck_users_status_valid", "users", type_="check")
    # M1-Konten hatten Status 'active' ohne Passwort bzw. 'disabled'
    op.execute("UPDATE users SET status = 'pending' WHERE status = 'active' AND password_hash IS NULL")
    op.execute("UPDATE users SET status = 'deactivated' WHERE status = 'disabled'")
    op.alter_column("users", "status", server_default="pending")
    op.add_column("users", sa.Column("username", sa.String(32)))
    op.add_column("users", sa.Column("password_changed_at", TS))
    op.add_column("users", sa.Column("failed_logins", sa.Integer, nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked_until", TS))
    op.add_column("users", sa.Column("last_login_at", TS))
    op.add_column("users", sa.Column("totp_secret_enc", sa.LargeBinary))
    op.add_column("users", sa.Column("totp_pending_enc", sa.LargeBinary))
    op.add_column("users", sa.Column("totp_enabled_at", TS))
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger))
    op.create_index("uq_users_username_lower", "users", [sa.text("lower(username)")], unique=True)
    for name, sql in (
        ("status_valid", "status IN ('pending','active','locked','suspended','deactivated')"),
        ("username_format", r"username IS NULL OR username ~ '^[a-z0-9][a-z0-9._-]{2,31}$'"),
        ("password_argon2id", "password_hash IS NULL OR password_hash LIKE '$argon2id$%'"),
        ("active_needs_password", "status <> 'active' OR password_hash IS NOT NULL"),
        ("failed_logins_positive", "failed_logins >= 0"),
    ):
        op.create_check_constraint(f"ck_users_{name}", "users", sql)

    # --- Tabellen -------------------------------------------------------------
    op.create_table(
        "auth_sessions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("stage", sa.String(16), nullable=False),
        sa.Column("active_tenant_id", UUID),
        sa.Column("active_membership_id", UUID),
        sa.Column("mfa_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ip", sa.String(64)),
        sa.Column("user_agent", sa.String(200)),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("last_seen_at", TS, server_default=NOW, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS),
        sa.Column("revoke_reason", sa.String(40)),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        _user_fk("auth_sessions"),
        sa.CheckConstraint("stage IN ('mfa_pending','full')", name="ck_auth_sessions_stage_valid"),
        sa.CheckConstraint("(active_tenant_id IS NULL) = (active_membership_id IS NULL)",
                           name="ck_auth_sessions_tenant_pair"),
        sa.CheckConstraint("stage = 'full' OR active_tenant_id IS NULL", name="ck_auth_sessions_no_tenant_before_mfa"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_user_active", "auth_sessions", ["user_id"],
                    postgresql_where=sa.text("revoked_at IS NULL"))

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS),
        sa.Column("invalidated_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        _user_fk("password_reset_tokens"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])

    op.create_table(
        "recovery_codes",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("code_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("used_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_recovery_codes"),
        sa.UniqueConstraint("code_hash", name="uq_recovery_codes_code_hash"),
        _user_fk("recovery_codes"),
    )
    op.create_index("ix_recovery_codes_user_id", "recovery_codes", ["user_id"])

    op.create_table(
        "login_attempts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("subject_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("ip", sa.String(64), nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("occurred_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_login_attempts"),
        sa.CheckConstraint("kind IN ('login','reset','mfa')", name="ck_login_attempts_kind_valid"),
    )
    op.create_index("ix_login_attempts_subject", "login_attempts", ["kind", "subject_hash", "occurred_at"])
    op.create_index("ix_login_attempts_ip", "login_attempts", ["kind", "ip", "occurred_at"])

    op.create_table(
        "auth_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("event", sa.String(60), nullable=False),
        sa.Column("user_id", UUID),
        sa.Column("session_id", UUID),
        sa.Column("ip", sa.String(64)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("data", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("occurred_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_events"),
        sa.CheckConstraint(r"event ~ '^[a-z][a-z0-9_.]{2,59}$'", name="ck_auth_events_event_format"),
    )
    op.create_index("ix_auth_events_user_id", "auth_events", ["user_id"])
    op.create_index("ix_auth_events_occurred_at", "auth_events", ["occurred_at"])
    op.execute("CREATE TRIGGER trg_auth_events_append_only BEFORE UPDATE OR DELETE ON auth_events "
               "FOR EACH ROW EXECUTE FUNCTION ichq_append_only()")
    op.execute("CREATE TRIGGER trg_auth_events_no_truncate BEFORE TRUNCATE ON auth_events "
               "FOR EACH STATEMENT EXECUTE FUNCTION ichq_append_only()")

    # --- Rechte -----------------------------------------------------------------
    op.execute(f"""
    REVOKE ALL ON {", ".join(AUTH_TABLES)} FROM PUBLIC;
    REVOKE SELECT ON users FROM ichq_app;
    GRANT SELECT ({STAMMDATEN}) ON users TO ichq_app;

    REVOKE SELECT, INSERT, UPDATE ON users FROM ichq_platform;
    GRANT SELECT ({STAMMDATEN}, failed_logins, locked_until, last_login_at) ON users TO ichq_platform;
    GRANT INSERT (id, email, username, display_name, status) ON users TO ichq_platform;
    GRANT UPDATE (display_name) ON users TO ichq_platform;

    GRANT USAGE ON SCHEMA public TO ichq_auth;
    GRANT SELECT, UPDATE ON users TO ichq_auth;
    GRANT SELECT ON memberships, tenants, alembic_version TO ichq_auth;
    GRANT SELECT, INSERT, UPDATE, DELETE ON auth_sessions, password_reset_tokens, recovery_codes, login_attempts
      TO ichq_auth;
    GRANT SELECT, INSERT ON auth_events TO ichq_auth;
    """)

    # --- Row-Level Security -------------------------------------------------------
    for t in AUTH_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY p_{t}_auth ON {t} TO ichq_auth USING (true) WITH CHECK (true)")
    op.execute("""
    CREATE POLICY p_users_auth ON users TO ichq_auth USING (true) WITH CHECK (true);
    -- Firmenauswahl: nur die eigenen Mitgliedschaften und Firmen des angemeldeten Kontos
    CREATE POLICY p_memberships_auth ON memberships FOR SELECT TO ichq_auth
      USING (user_id = ichq_current_user());
    CREATE POLICY p_tenants_auth ON tenants FOR SELECT TO ichq_auth USING (
      EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = tenants.id AND m.user_id = ichq_current_user()));
    """)


def downgrade() -> None:
    op.execute("""
    DROP POLICY IF EXISTS p_tenants_auth ON tenants;
    DROP POLICY IF EXISTS p_memberships_auth ON memberships;
    DROP POLICY IF EXISTS p_users_auth ON users;
    """)
    for t in reversed(AUTH_TABLES):
        op.drop_table(t)
    op.execute("""
    REVOKE ALL ON users, memberships, tenants, alembic_version FROM ichq_auth;
    REVOKE ALL ON SCHEMA public FROM ichq_auth;
    REVOKE ALL ON users FROM ichq_app;
    GRANT SELECT ON users TO ichq_app;
    REVOKE ALL ON users FROM ichq_platform;
    GRANT SELECT, INSERT, UPDATE ON users TO ichq_platform;
    """)
    for name in ("status_valid", "username_format", "password_argon2id", "active_needs_password",
                 "failed_logins_positive"):
        op.drop_constraint(f"ck_users_{name}", "users", type_="check")
    op.drop_index("uq_users_username_lower", table_name="users")
    for col in ("totp_last_step", "totp_enabled_at", "totp_pending_enc", "totp_secret_enc", "last_login_at",
                "locked_until", "failed_logins", "password_changed_at", "username"):
        op.drop_column("users", col)
    op.execute("UPDATE users SET status = 'disabled' WHERE status IN ('locked','suspended','deactivated')")
    op.execute("UPDATE users SET status = 'active' WHERE status = 'pending'")
    op.alter_column("users", "status", server_default="active")
    op.create_check_constraint("ck_users_status_valid", "users", "status IN ('active','disabled')")
    op.execute("DROP FUNCTION IF EXISTS ichq_current_user()")

