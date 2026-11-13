"""Liquidität: Konten mit manuell gepflegten Ständen (nur anhängend) und Planposten (ADR-020 Nr. 9).

Revision: 0013_liquidity
Vorgänger: 0012_receipts
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.namen import kurz

revision = "0013_liquidity"
down_revision = "0012_receipts"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TABLES = ["liquidity_accounts", "liquidity_balances", "liquidity_forecasts"]
PUBLIC_ID = r"public_id ~ '^[0-9a-f]{32}$'"


def _tenant(table: str) -> list[sa.schema.SchemaItem]:
    return [sa.Column("tenant_id", UUID, nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                    name=f"fk_{table}_tenant_id_tenants")]


def _mfk(table: str, col: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], ["memberships.tenant_id", "memberships.id"],
                                   ondelete="RESTRICT", name=kurz(f"fk_{table}_tenant_id_{col}_memberships"))


def _ck(table: str, name: str, sql: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sql, name=kurz(f"ck_{table}_{name}"))


def upgrade() -> None:
    op.create_table(
        "liquidity_accounts",
        sa.Column("id", UUID, primary_key=True), *_tenant("liquidity_accounts"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False, server_default="bank"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("archived_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_liquidity_accounts"),
        sa.UniqueConstraint("public_id", name="uq_liquidity_accounts_public_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_liquidity_accounts_tenant_id_id"),
        _ck("liquidity_accounts", "public_id_format", PUBLIC_ID),
        _ck("liquidity_accounts", "name_not_blank", "char_length(btrim(name)) > 0"),
        _ck("liquidity_accounts", "kind_valid", "kind IN ('bank','cash','other')"),
        _ck("liquidity_accounts", "currency_format", "currency ~ '^[A-Z]{3}$'"),
    )
    op.create_index("ix_liquidity_accounts_tenant_id", "liquidity_accounts", ["tenant_id"])
    op.create_table(
        "liquidity_balances",
        sa.Column("id", UUID, primary_key=True), *_tenant("liquidity_balances"),
        sa.Column("account_id", UUID, nullable=False),
        sa.Column("as_of", sa.Date, nullable=False),
        sa.Column("balance_minor", sa.BigInteger, nullable=False),
        sa.Column("note", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_by_membership_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_liquidity_balances"),
        sa.ForeignKeyConstraint(["tenant_id", "account_id"], ["liquidity_accounts.tenant_id", "liquidity_accounts.id"],
                                ondelete="RESTRICT",
                                name=kurz("fk_liquidity_balances_tenant_id_account_id_liquidity_accounts")),
        _mfk("liquidity_balances", "created_by_membership_id"),
    )
    op.create_index("ix_liquidity_balances_tenant_id", "liquidity_balances", ["tenant_id"])
    op.create_index("ix_liquidity_balances_tenant_account_asof", "liquidity_balances",
                    ["tenant_id", "account_id", "as_of"])
    op.create_table(
        "liquidity_forecasts",
        sa.Column("id", UUID, primary_key=True), *_tenant("liquidity_forecasts"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("expected_on", sa.Date, nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("category", sa.String(60)),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("created_by_membership_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_liquidity_forecasts"),
        sa.UniqueConstraint("public_id", name="uq_liquidity_forecasts_public_id"),
        _mfk("liquidity_forecasts", "created_by_membership_id"),
        _ck("liquidity_forecasts", "public_id_format", PUBLIC_ID),
        _ck("liquidity_forecasts", "amount_not_zero", "amount_minor <> 0"),
        _ck("liquidity_forecasts", "currency_format", "currency ~ '^[A-Z]{3}$'"),
        _ck("liquidity_forecasts", "status_valid", "status IN ('open','done','cancelled')"),
        _ck("liquidity_forecasts", "label_not_blank", "char_length(btrim(label)) > 0"),
    )
    op.create_index("ix_liquidity_forecasts_tenant_id", "liquidity_forecasts", ["tenant_id"])
    op.create_index("ix_liquidity_forecasts_tenant_expected", "liquidity_forecasts", ["tenant_id", "expected_on"])
    op.execute("""
    CREATE FUNCTION ichq_liquidity_balance_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'ichq: erfasster Kontostand ist unveränderlich — neuen Stand erfassen';
    END $$;
    CREATE TRIGGER trg_liquidity_balances_guard BEFORE UPDATE OR DELETE ON liquidity_balances
      FOR EACH ROW EXECUTE FUNCTION ichq_liquidity_balance_guard();
    """)
    for t in TABLES:
        op.execute(f"""
        REVOKE ALL ON {t} FROM PUBLIC;
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_{t}_tenant ON {t} TO ichq_app
          USING (tenant_id = ichq_current_tenant()) WITH CHECK (tenant_id = ichq_current_tenant());
        """)
    op.execute("""
    GRANT SELECT, INSERT ON liquidity_accounts, liquidity_balances, liquidity_forecasts TO ichq_app;
    GRANT UPDATE (name, archived_at) ON liquidity_accounts TO ichq_app;
    GRANT UPDATE (expected_on, amount_minor, label, category, status) ON liquidity_forecasts TO ichq_app;
    """)


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
    op.execute("DROP FUNCTION ichq_liquidity_balance_guard()")
