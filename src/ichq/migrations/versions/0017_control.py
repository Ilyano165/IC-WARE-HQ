"""Betreiber (platform_operators) und Einrichtungscodes (platform_setup_codes) — ADR-021.

Revision: 0017_control
Vorgänger: 0016_travel_logbook
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0017_control"
down_revision = "0016_travel_logbook"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TABLES = ["platform_operators", "platform_setup_codes"]


def upgrade() -> None:
    op.create_table(
        "platform_operators",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("created_by", sa.String(120), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("user_id", name="pk_platform_operators"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT",
                                name="fk_platform_operators_user_id_users"),
    )
    op.create_table(
        "platform_setup_codes",
        sa.Column("id", UUID, nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_platform_setup_codes"),
        sa.UniqueConstraint("code_hash", name="uq_platform_setup_codes_code_hash"),
        sa.CheckConstraint("code_hash ~ '^[0-9a-f]{64}$'", name="ck_platform_setup_codes_code_hash_format"),
    )
    for t in TABLES:   # nur die Control Plane; App-, Auth- und Worker-Rolle sehen nichts
        op.execute(f"""
        REVOKE ALL ON {t} FROM PUBLIC;
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_{t}_platform ON {t} TO ichq_platform USING (true) WITH CHECK (true);
        """)
    op.execute("""
    GRANT SELECT, INSERT, DELETE ON platform_operators TO ichq_platform;
    GRANT SELECT, INSERT ON platform_setup_codes TO ichq_platform;
    GRANT UPDATE (used_at) ON platform_setup_codes TO ichq_platform;
    """)


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
