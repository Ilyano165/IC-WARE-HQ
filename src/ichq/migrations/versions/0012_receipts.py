"""Ausgaben mit Beleg (receipts) — Belegprinzip, Stornierung statt Löschen (ADR-020).

Revision: 0012_receipts
Vorgänger: 0011_invoices
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.namen import kurz

revision = "0012_receipts"
down_revision = "0011_invoices"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def _ck(name: str, sql: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sql, name=kurz(f"ck_receipts_{name}"))


def upgrade() -> None:
    op.create_table(
        "receipts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("object_type", sa.String(24), nullable=False, server_default="receipt"),
        sa.Column("expense_date", sa.Date, nullable=False),
        sa.Column("supplier_name", sa.String(200)),
        sa.Column("category", sa.String(60)),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("tax_rate_bp", sa.Integer),
        sa.Column("project_id", UUID),
        sa.Column("responsible_membership_id", UUID),
        sa.Column("payment_status", sa.String(8), nullable=False, server_default="unpaid"),
        sa.Column("paid_on", sa.Date),
        sa.Column("due_date", sa.Date),
        sa.Column("document_id", UUID),
        sa.Column("document_type", sa.String(24), nullable=False, server_default="document"),
        sa.Column("missing_reason", sa.String(500)),
        sa.Column("follow_up_on", sa.Date),
        sa.Column("voided_at", TS),
        sa.Column("void_reason", sa.String(500)),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_receipts"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_receipts_tenant_id_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT", name="fk_receipts_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["tenant_id", "id", "object_type"], ["objects.tenant_id", "objects.id", "objects.type"],
                                ondelete="CASCADE", name="fk_receipts_tenant_id_id_object_type_objects"),
        sa.ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"],
                                ondelete="RESTRICT", name="fk_receipts_tenant_id_project_id_projects"),
        sa.ForeignKeyConstraint(["tenant_id", "responsible_membership_id"], ["memberships.tenant_id", "memberships.id"],
                                ondelete="RESTRICT", name=kurz("fk_receipts_tenant_id_responsible_membership_id_memberships")),
        sa.ForeignKeyConstraint(["tenant_id", "document_id", "document_type"],
                                ["objects.tenant_id", "objects.id", "objects.type"], ondelete="RESTRICT",
                                name=kurz("fk_receipts_tenant_id_document_id_document_type_objects")),
        _ck("object_type_receipt", "object_type = 'receipt'"),
        _ck("document_type_document", "document_type = 'document'"),
        _ck("amount_positive", "amount_minor > 0"),
        _ck("currency_format", "currency ~ '^[A-Z]{3}$'"),
        _ck("tax_rate_range", "tax_rate_bp IS NULL OR tax_rate_bp BETWEEN 0 AND 10000"),
        _ck("payment_status_valid", "payment_status IN ('unpaid','paid')"),
        _ck("paid_consistent", "(payment_status = 'paid') = (paid_on IS NOT NULL)"),
        _ck("description_length", "char_length(description) <= 5000"),
        _ck("void_reason_required", "(voided_at IS NULL) = (void_reason IS NULL)"),
    )
    for name, cols in (("ix_receipts_tenant_id", ["tenant_id"]), ("ix_receipts_tenant_date", ["tenant_id", "expense_date"]),
                       ("ix_receipts_tenant_project", ["tenant_id", "project_id"]),
                       ("ix_receipts_tenant_document", ["tenant_id", "document_id"])):
        op.create_index(name, "receipts", cols)
    op.execute("""
    CREATE FUNCTION ichq_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ichq: Ausgaben werden nicht gelöscht — stornieren';
      END IF;
      IF OLD.voided_at IS NOT NULL THEN
        RAISE EXCEPTION 'ichq: stornierte Ausgabe ist unveränderlich';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_receipts_guard BEFORE UPDATE OR DELETE ON receipts
      FOR EACH ROW EXECUTE FUNCTION ichq_receipt_guard();
    CREATE TRIGGER trg_receipts_updated_at BEFORE UPDATE ON receipts
      FOR EACH ROW EXECUTE FUNCTION ichq_set_updated_at();
    REVOKE ALL ON receipts FROM PUBLIC;
    GRANT SELECT, INSERT ON receipts TO ichq_app;
    GRANT UPDATE (expense_date, supplier_name, category, description, amount_minor, currency, tax_rate_bp, project_id,
                  responsible_membership_id, payment_status, paid_on, due_date, document_id, missing_reason,
                  follow_up_on, voided_at, void_reason) ON receipts TO ichq_app;
    ALTER TABLE receipts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE receipts FORCE ROW LEVEL SECURITY;
    CREATE POLICY p_receipts_tenant ON receipts TO ichq_app
      USING (tenant_id = ichq_current_tenant()) WITH CHECK (tenant_id = ichq_current_tenant());
    """)


def downgrade() -> None:
    op.drop_table("receipts")
    op.execute("DROP FUNCTION ichq_receipt_guard()")
