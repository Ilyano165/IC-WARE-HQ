"""Monatsabschluss mit Periodensperre (ADR-020 Nr. 7) und Export-Historie (Nr. 11).

Die Sperre gilt in der Datenbank: Trigger auf Rechnungen, Zahlungen und Ausgaben lehnen Buchungsdaten in einem
abgeschlossenen Monat ab — auch bei direktem Zugriff der App-Rolle. Abschlüsse werden nie gelöscht; Wiedereröffnen
setzt ``reopened_*`` (mit Grund) und ein neuer Abschluss ist eine neue Zeile.

Revision: 0015_month_close_export
Vorgänger: 0014_deadlines_contracts
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.namen import kurz

revision = "0015_month_close_export"
down_revision = "0014_deadlines_contracts"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TABLES = ["month_closes", "exports"]


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
        "month_closes",
        sa.Column("id", UUID, primary_key=True), *_tenant("month_closes"),
        sa.Column("period", sa.Date, nullable=False),
        sa.Column("closed_at", TS, nullable=False, server_default=NOW),
        sa.Column("closed_by_membership_id", UUID),
        sa.Column("close_note", sa.String(500), nullable=False, server_default=""),
        sa.Column("warnings", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("reopened_at", TS),
        sa.Column("reopened_by_membership_id", UUID),
        sa.Column("reopen_reason", sa.String(500)),
        sa.PrimaryKeyConstraint("id", name="pk_month_closes"),
        _mfk("month_closes", "closed_by_membership_id"),
        _mfk("month_closes", "reopened_by_membership_id"),
        _ck("month_closes", "period_first_day", "extract(day FROM period) = 1"),
        _ck("month_closes", "reopen_consistent", "(reopened_at IS NULL) = (reopen_reason IS NULL)"),
    )
    op.create_index("ix_month_closes_tenant_id", "month_closes", ["tenant_id"])
    op.create_index("uq_month_closes_active", "month_closes", ["tenant_id", "period"], unique=True,
                    postgresql_where=sa.text("reopened_at IS NULL"))
    op.create_table(
        "exports",
        sa.Column("id", UUID, primary_key=True), *_tenant("exports"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("format", sa.String(24), nullable=False),
        sa.Column("period_from", sa.Date, nullable=False),
        sa.Column("period_to", sa.Date, nullable=False),
        sa.Column("row_count", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("report", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("repeats_export_id", UUID),
        sa.Column("created_by_membership_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_exports"),
        sa.UniqueConstraint("public_id", name="uq_exports_public_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_exports_tenant_id_id"),
        sa.ForeignKeyConstraint(["tenant_id", "repeats_export_id"], ["exports.tenant_id", "exports.id"],
                                ondelete="RESTRICT", name=kurz("fk_exports_tenant_id_repeats_export_id_exports")),
        _mfk("exports", "created_by_membership_id"),
        _ck("exports", "public_id_format", r"public_id ~ '^[0-9a-f]{32}$'"),
        _ck("exports", "format_valid", "format IN ('ichq-buchungen-v1')"),
        _ck("exports", "range_ordered", "period_to >= period_from"),
        _ck("exports", "sha256_format", "sha256 ~ '^[0-9a-f]{64}$'"),
    )
    op.create_index("ix_exports_tenant_id", "exports", ["tenant_id"])
    for t in TABLES:
        op.execute(f"""
        REVOKE ALL ON {t} FROM PUBLIC;
        ALTER TABLE {t} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {t} FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_{t}_tenant ON {t} TO ichq_app
          USING (tenant_id = ichq_current_tenant()) WITH CHECK (tenant_id = ichq_current_tenant());
        """)
    op.execute("""
    GRANT SELECT, INSERT ON month_closes, exports TO ichq_app;
    GRANT UPDATE (reopened_at, reopened_by_membership_id, reopen_reason) ON month_closes TO ichq_app;

    CREATE FUNCTION ichq_month_close_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'ichq: Monatsabschlüsse werden nicht gelöscht';
      END IF;
      IF OLD.reopened_at IS NOT NULL OR NEW.period <> OLD.period OR NEW.closed_at <> OLD.closed_at
         OR NEW.closed_by_membership_id IS DISTINCT FROM OLD.closed_by_membership_id THEN
        RAISE EXCEPTION 'ichq: Monatsabschluss ist unveränderlich — nur einmal wiedereröffnen';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_month_closes_guard BEFORE UPDATE OR DELETE ON month_closes
      FOR EACH ROW EXECUTE FUNCTION ichq_month_close_guard();
    CREATE FUNCTION ichq_export_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      RAISE EXCEPTION 'ichq: Exporte sind Historie und unveränderlich';
    END $$;
    CREATE TRIGGER trg_exports_guard BEFORE UPDATE OR DELETE ON exports
      FOR EACH ROW EXECUTE FUNCTION ichq_export_guard();

    CREATE FUNCTION ichq_period_closed(t uuid, d date) RETURNS boolean LANGUAGE sql STABLE AS $$
      SELECT d IS NOT NULL AND EXISTS (SELECT 1 FROM month_closes m WHERE m.tenant_id = t
        AND m.period = date_trunc('month', d)::date AND m.reopened_at IS NULL)
    $$;

    CREATE FUNCTION ichq_lock_invoice() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        IF ichq_period_closed(OLD.tenant_id, OLD.issue_date) THEN
          RAISE EXCEPTION 'ichq: Monat % ist abgeschlossen', to_char(OLD.issue_date, 'YYYY-MM');
        END IF;
        RETURN OLD;
      END IF;
      IF (TG_OP = 'INSERT' OR NEW.issue_date IS DISTINCT FROM OLD.issue_date)
         AND ichq_period_closed(NEW.tenant_id, NEW.issue_date) THEN
        RAISE EXCEPTION 'ichq: Monat % ist abgeschlossen', to_char(NEW.issue_date, 'YYYY-MM');
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_invoices_period_lock BEFORE INSERT OR UPDATE OR DELETE ON invoices
      FOR EACH ROW EXECUTE FUNCTION ichq_lock_invoice();

    CREATE FUNCTION ichq_lock_payment() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF ichq_period_closed(CASE WHEN TG_OP = 'DELETE' THEN OLD.tenant_id ELSE NEW.tenant_id END,
                            CASE WHEN TG_OP = 'DELETE' THEN OLD.paid_on ELSE NEW.paid_on END)
         OR (TG_OP = 'UPDATE' AND ichq_period_closed(OLD.tenant_id, OLD.paid_on)) THEN
        RAISE EXCEPTION 'ichq: Monat der Zahlung ist abgeschlossen';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_payments_period_lock BEFORE INSERT OR UPDATE OR DELETE ON payments
      FOR EACH ROW EXECUTE FUNCTION ichq_lock_payment();

    -- Ausgaben: Buchungsfelder im abgeschlossenen Monat gesperrt. Beleg nachreichen (document_id, missing_reason,
    -- follow_up_on) und Bezahlen in einem offenen Monat bleiben erlaubt (Belegprinzip, Zahlung ist eigenes Ereignis).
    CREATE FUNCTION ichq_lock_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'INSERT' THEN
        IF ichq_period_closed(NEW.tenant_id, NEW.expense_date) OR ichq_period_closed(NEW.tenant_id, NEW.paid_on) THEN
          RAISE EXCEPTION 'ichq: Monat % ist abgeschlossen', to_char(NEW.expense_date, 'YYYY-MM');
        END IF;
        RETURN NEW;
      END IF;
      IF ichq_period_closed(OLD.tenant_id, OLD.expense_date) OR ichq_period_closed(NEW.tenant_id, NEW.expense_date) THEN
        IF (NEW.expense_date, NEW.amount_minor, NEW.currency, NEW.tax_rate_bp, NEW.supplier_name, NEW.category,
            NEW.description, NEW.project_id, NEW.voided_at)
           IS DISTINCT FROM
           (OLD.expense_date, OLD.amount_minor, OLD.currency, OLD.tax_rate_bp, OLD.supplier_name, OLD.category,
            OLD.description, OLD.project_id, OLD.voided_at) THEN
          RAISE EXCEPTION 'ichq: Monat % ist abgeschlossen', to_char(OLD.expense_date, 'YYYY-MM');
        END IF;
      END IF;
      IF NEW.paid_on IS DISTINCT FROM OLD.paid_on
         AND (ichq_period_closed(OLD.tenant_id, OLD.paid_on) OR ichq_period_closed(NEW.tenant_id, NEW.paid_on)) THEN
        RAISE EXCEPTION 'ichq: Monat der Zahlung ist abgeschlossen';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_receipts_period_lock BEFORE INSERT OR UPDATE ON receipts
      FOR EACH ROW EXECUTE FUNCTION ichq_lock_receipt();
    """)


def downgrade() -> None:
    op.execute("""
    DROP TRIGGER trg_receipts_period_lock ON receipts;
    DROP TRIGGER trg_payments_period_lock ON payments;
    DROP TRIGGER trg_invoices_period_lock ON invoices;
    DROP FUNCTION ichq_lock_receipt(); DROP FUNCTION ichq_lock_payment(); DROP FUNCTION ichq_lock_invoice();
    DROP FUNCTION ichq_period_closed(uuid, date);
    """)
    for t in reversed(TABLES):
        op.drop_table(t)
    op.execute("DROP FUNCTION ichq_month_close_guard(); DROP FUNCTION ichq_export_guard();")
