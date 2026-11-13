"""Fristen (deadlines) und Verträge (contracts) auf dem Objektmodell (ADR-020 Nr. 10).

Revision: 0014_deadlines_contracts
Vorgänger: 0013_liquidity
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.namen import kurz

revision = "0014_deadlines_contracts"
down_revision = "0013_liquidity"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TABLES = ["deadlines", "contracts"]


def _basis(table: str, typ: str) -> list[sa.schema.SchemaItem]:
    return [sa.Column("id", UUID, primary_key=True), sa.Column("tenant_id", UUID, nullable=False),
            sa.Column("object_type", sa.String(24), nullable=False, server_default=typ),
            sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
            sa.UniqueConstraint("tenant_id", "id", name=f"uq_{table}_tenant_id_id"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                    name=f"fk_{table}_tenant_id_tenants"),
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
        "deadlines", *_basis("deadlines", "deadline"),
        sa.Column("due_on", sa.Date, nullable=False),
        sa.Column("category", sa.String(12), nullable=False, server_default="other"),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("source_reference", sa.String(500)),
        sa.Column("responsible_membership_id", UUID),
        sa.Column("remind_days_before", sa.Integer, nullable=False, server_default="7"),
        sa.Column("recurrence", sa.String(10), nullable=False, server_default="none"),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("done_at", TS),
        sa.Column("done_by_membership_id", UUID),
        sa.Column("done_note", sa.String(500)),
        sa.Column("follows_deadline_id", UUID),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("tenant_id", "follows_deadline_id", name=kurz("uq_deadlines_tenant_id_follows_deadline_id")),
        _mfk("deadlines", "responsible_membership_id"),
        _mfk("deadlines", "done_by_membership_id"),
        _tfk("deadlines", "follows_deadline_id", "deadlines"),
        _ck("deadlines", "category_valid", "category IN ('tax', 'contract', 'payroll', 'insurance', 'authority', "
                                           "'other')"),
        _ck("deadlines", "recurrence_valid", "recurrence IN ('none', 'monthly', 'quarterly', 'yearly')"),
        _ck("deadlines", "status_valid", "status IN ('open', 'done', 'cancelled')"),
        _ck("deadlines", "remind_range", "remind_days_before BETWEEN 0 AND 365"),
        _ck("deadlines", "description_length", "char_length(description) <= 5000"),
        _ck("deadlines", "done_consistent", "(status = 'open') = (done_at IS NULL)"),
    )
    op.create_index("ix_deadlines_tenant_id", "deadlines", ["tenant_id"])
    op.create_index("ix_deadlines_tenant_status_due", "deadlines", ["tenant_id", "status", "due_on"])
    op.create_table(
        "contracts", *_basis("contracts", "contract"),
        sa.Column("customer_id", UUID),
        sa.Column("counterparty_name", sa.String(200)),
        sa.Column("contract_type", sa.String(60)),
        sa.Column("reference", sa.String(100)),
        sa.Column("start_date", sa.Date),
        sa.Column("end_date", sa.Date),
        sa.Column("notice_value", sa.Integer),
        sa.Column("notice_unit", sa.String(8)),
        sa.Column("auto_renew", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("renewal_months", sa.Integer),
        sa.Column("amount_minor", sa.BigInteger),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("billing", sa.String(10), nullable=False, server_default="none"),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("terminated_on", sa.Date),
        sa.Column("termination_effective_on", sa.Date),
        sa.Column("termination_note", sa.String(500)),
        sa.Column("responsible_membership_id", UUID),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        _tfk("contracts", "customer_id", "customers"),
        _mfk("contracts", "responsible_membership_id"),
        _ck("contracts", "status_valid", "status IN ('draft', 'active', 'terminated')"),
        _ck("contracts", "billing_valid", "billing IN ('none', 'once', 'monthly', 'quarterly', 'yearly')"),
        _ck("contracts", "notice_unit_valid", "notice_unit IS NULL OR notice_unit IN ('days', 'weeks', 'months')"),
        _ck("contracts", "notice_complete", "(notice_value IS NULL) = (notice_unit IS NULL)"),
        _ck("contracts", "notice_range", "notice_value IS NULL OR notice_value BETWEEN 0 AND 3650"),
        _ck("contracts", "renewal_range", "renewal_months IS NULL OR renewal_months BETWEEN 1 AND 120"),
        _ck("contracts", "renewal_needs_months", "NOT auto_renew OR renewal_months IS NOT NULL"),
        _ck("contracts", "dates_ordered", "end_date IS NULL OR start_date IS NULL OR end_date >= start_date"),
        _ck("contracts", "amount_not_negative", "amount_minor IS NULL OR amount_minor >= 0"),
        _ck("contracts", "currency_format", "currency ~ '^[A-Z]{3}$'"),
        _ck("contracts", "terminated_consistent", "(status = 'terminated') = (terminated_on IS NOT NULL)"),
        _ck("contracts", "notes_length", "char_length(notes) <= 20000"),
    )
    op.create_index("ix_contracts_tenant_id", "contracts", ["tenant_id"])
    op.create_index("ix_contracts_tenant_end", "contracts", ["tenant_id", "end_date"])
    op.create_index("ix_contracts_tenant_customer", "contracts", ["tenant_id", "customer_id"])
    for t in TABLES:
        op.execute(f"""
        CREATE TRIGGER trg_{t}_updated_at BEFORE UPDATE ON {t} FOR EACH ROW EXECUTE FUNCTION ichq_set_updated_at();
        REVOKE ALL ON {t} FROM PUBLIC;
        GRANT SELECT, INSERT ON {t} TO ichq_app;
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_{t}_tenant ON {t} TO ichq_app
          USING (tenant_id = ichq_current_tenant()) WITH CHECK (tenant_id = ichq_current_tenant());
        """)
    op.execute("""
    GRANT UPDATE (due_on, category, description, source_reference, responsible_membership_id, remind_days_before,
                  recurrence, status, done_at, done_by_membership_id, done_note, follows_deadline_id)
      ON deadlines TO ichq_app;
    GRANT UPDATE (customer_id, counterparty_name, contract_type, reference, start_date, end_date, notice_value,
                  notice_unit, auto_renew, renewal_months, amount_minor, currency, billing, status, terminated_on,
                  termination_effective_on, termination_note, responsible_membership_id, notes)
      ON contracts TO ichq_app;
    """)


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
