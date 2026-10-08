"""M3 Mandanten: Firmenprofil durch die Firma änderbar, Einladungen.

Revision: 0004_m3_tenancy
Vorgänger: 0003_core

* ``tenants``: Die App-Rolle darf in der EIGENEN Firma genau die Profilspalten ändern (Spaltenrechte + Policy).
  Slug, Status, Plan, Löschfelder bleiben Sache der Control Plane.
* ``invitations``: einmaliger Token nur als SHA-256, 7 Tage gültig, widerrufbar. Die Auth-Rolle darf
  Einladungen per Token-Hash LESEN (die Firma ist beim Annehmen noch unbekannt) — ändern nur die App-Rolle
  im Mandantenkontext.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0004_m3_tenancy"
down_revision = "0003_core"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
PROFIL = "name, legal_name, timezone, language, currency"


def upgrade() -> None:
    op.execute(f"GRANT UPDATE ({PROFIL}) ON tenants TO ichq_app")
    op.execute("""CREATE POLICY p_tenants_own_update ON tenants FOR UPDATE TO ichq_app
                  USING (id = ichq_current_tenant()) WITH CHECK (id = ichq_current_tenant())""")

    op.create_table(
        "invitations",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("title", sa.String(120)),
        sa.Column("token_hash", sa.LargeBinary(32), nullable=False),
        sa.Column("invited_by_membership_id", UUID),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("accepted_at", TS),
        sa.Column("accepted_membership_id", UUID),
        sa.Column("revoked_at", TS),
        sa.Column("revoked_by_membership_id", UUID),
        sa.PrimaryKeyConstraint("id", name="pk_invitations"),
        sa.UniqueConstraint("public_id", name="uq_invitations_public_id"),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                name="fk_invitations_tenant_id_tenants"),
        *[sa.ForeignKeyConstraint(["tenant_id", c], ["memberships.tenant_id", "memberships.id"], ondelete="RESTRICT",
                                  name=f"fk_invitations_tenant_id_{c}_memberships")
          for c in ("invited_by_membership_id", "accepted_membership_id", "revoked_by_membership_id")],
        sa.CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="ck_invitations_public_id_format"),
        sa.CheckConstraint("position('@' in email) > 1 AND email = lower(email)", name="ck_invitations_email_shape"),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="ck_invitations_token_hash_length"),
        sa.CheckConstraint("expires_at > created_at", name="ck_invitations_expiry_after_creation"),
        sa.CheckConstraint("NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)", name="ck_invitations_one_end"),
    )
    op.create_index("ix_invitations_tenant_id", "invitations", ["tenant_id"])
    op.create_index("ix_invitations_tenant_created", "invitations", ["tenant_id", "created_at"])
    # Höchstens eine offene Einladung je Firma und E-Mail
    op.create_index("uq_invitations_open_email", "invitations", ["tenant_id", "email"], unique=True,
                    postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"))

    op.execute("""
    REVOKE ALL ON invitations FROM PUBLIC;
    GRANT SELECT, INSERT ON invitations TO ichq_app;
    GRANT UPDATE (accepted_at, accepted_membership_id, revoked_at, revoked_by_membership_id) ON invitations TO ichq_app;
    GRANT SELECT (id, tenant_id, email, token_hash, expires_at, accepted_at, revoked_at) ON invitations TO ichq_auth;
    ALTER TABLE invitations ENABLE ROW LEVEL SECURITY;
    ALTER TABLE invitations FORCE ROW LEVEL SECURITY;
    CREATE POLICY p_invitations_tenant ON invitations TO ichq_app
      USING (tenant_id = ichq_current_tenant()) WITH CHECK (tenant_id = ichq_current_tenant());
    CREATE POLICY p_invitations_auth ON invitations FOR SELECT TO ichq_auth USING (true);
    """)


def downgrade() -> None:
    op.drop_table("invitations")
    op.execute("DROP POLICY IF EXISTS p_tenants_own_update ON tenants")
    op.execute(f"REVOKE UPDATE ({PROFIL}) ON tenants FROM ichq_app")
