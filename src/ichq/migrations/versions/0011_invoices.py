"""Rechnungen, Positionen, Nummernkreis, Zahlungen, Mahn- und Versandhistorie (ADR-020).

Revision: 0011_invoices
Vorgänger: 0010_projects

Die Datenbank schützt ausgestellte Rechnungen selbst (Trigger) — unabhängig vom Service:
* Rechnung: nach dem Ausstellen sind Kunde, Projekt, Nummer, Daten, Währung, Beträge, Notiz, Kundenstand und
  Ausstellungsdaten unveränderlich; kein Weg zurück in den Entwurf, kein Weg aus „storniert"; Löschen nur im Entwurf.
* Positionen: Einfügen/Ändern/Löschen nur, solange die Rechnung ein Entwurf ist.
* Zahlungen nur auf ausgestellte, nicht stornierte Rechnungen in derselben Währung.
* Historien (Kontakt-/Mahnverlauf, Versand) sind für die App nur anhängend (keine UPDATE/DELETE-Rechte).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.namen import kurz

revision = "0011_invoices"
down_revision = "0010_projects"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TABLES = ["invoices", "invoice_lines", "invoice_number_counters", "payments", "invoice_followups",
          "invoice_dispatches"]
CHANNEL = "channel IS NULL OR channel IN ('phone','email','letter','in_person','other')"


def _tenant(table: str) -> list[sa.schema.SchemaItem]:
    return [sa.Column("tenant_id", UUID, nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                    name=f"fk_{table}_tenant_id_tenants")]


def _typed(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", "id", "object_type"], ["objects.tenant_id", "objects.id", "objects.type"],
                                   ondelete="CASCADE", name=kurz(f"fk_{table}_tenant_id_id_object_type_objects"))


def _mfk(table: str, col: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], ["memberships.tenant_id", "memberships.id"],
                                   ondelete="RESTRICT", name=kurz(f"fk_{table}_tenant_id_{col}_memberships"))


def _tfk(table: str, col: str, ziel: str, ondelete: str = "RESTRICT") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], [f"{ziel}.tenant_id", f"{ziel}.id"], ondelete=ondelete,
                                   name=kurz(f"fk_{table}_tenant_id_{col}_{ziel}"))


def _ck(table: str, name: str, sql: str) -> sa.CheckConstraint:
    return sa.CheckConstraint(sql, name=kurz(f"ck_{table}_{name}"))


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", UUID, primary_key=True), *_tenant("invoices"),
        sa.Column("object_type", sa.String(24), nullable=False, server_default="invoice"),
        sa.Column("kind", sa.String(14), nullable=False, server_default="invoice"),
        sa.Column("cancels_invoice_id", UUID),
        sa.Column("customer_id", UUID),
        sa.Column("project_id", UUID),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("number", sa.String(40)),
        sa.Column("issue_date", sa.Date),
        sa.Column("service_date", sa.Date),
        sa.Column("due_date", sa.Date),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("net_minor", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("tax_minor", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("gross_minor", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("customer_snapshot", pg.JSONB),
        sa.Column("responsible_membership_id", UUID),
        sa.Column("dunning_level", sa.Integer, nullable=False, server_default="0"),
        sa.Column("next_follow_up", sa.Date),
        sa.Column("issued_at", TS),
        sa.Column("issued_by_membership_id", UUID),
        sa.Column("sent_at", TS),
        sa.Column("cancelled_at", TS),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_invoices"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_invoices_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "number", name="uq_invoices_tenant_id_number"),
        sa.UniqueConstraint("tenant_id", "cancels_invoice_id", name=kurz("uq_invoices_tenant_id_cancels_invoice_id")),
        _typed("invoices"), _tfk("invoices", "cancels_invoice_id", "invoices"),
        _tfk("invoices", "customer_id", "customers"), _tfk("invoices", "project_id", "projects"),
        _mfk("invoices", "responsible_membership_id"), _mfk("invoices", "issued_by_membership_id"),
        _ck("invoices", "object_type_invoice", "object_type = 'invoice'"),
        _ck("invoices", "status_valid", "status IN ('draft','issued','sent','partially_paid','paid','cancelled')"),
        _ck("invoices", "kind_valid", "kind IN ('invoice','cancellation')"),
        _ck("invoices", "cancellation_ref", "(kind = 'cancellation') = (cancels_invoice_id IS NOT NULL)"),
        _ck("invoices", "currency_format", "currency ~ '^[A-Z]{3}$'"),
        _ck("invoices", "gross_is_sum", "gross_minor = net_minor + tax_minor"),
        _ck("invoices", "number_iff_issued", "(status = 'draft') = (number IS NULL)"),
        _ck("invoices", "issued_complete", "status = 'draft' OR (issue_date IS NOT NULL AND issued_at IS NOT NULL "
                                           "AND customer_id IS NOT NULL AND due_date IS NOT NULL)"),
        _ck("invoices", "due_after_issue", "due_date IS NULL OR issue_date IS NULL OR due_date >= issue_date"),
        _ck("invoices", "dunning_level_range", "dunning_level BETWEEN 0 AND 9"),
        _ck("invoices", "notes_length", "char_length(notes) <= 5000"),
    )
    for name, cols in (("ix_invoices_tenant_id", ["tenant_id"]),
                       ("ix_invoices_tenant_status_due", ["tenant_id", "status", "due_date"]),
                       ("ix_invoices_tenant_customer", ["tenant_id", "customer_id"]),
                       ("ix_invoices_tenant_project", ["tenant_id", "project_id"])):
        op.create_index(name, "invoices", cols)

    op.create_table(
        "invoice_lines",
        sa.Column("id", UUID, primary_key=True), *_tenant("invoice_lines"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("invoice_id", UUID, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("quantity_milli", sa.BigInteger, nullable=False),
        sa.Column("unit", sa.String(20)),
        sa.Column("unit_price_minor", sa.BigInteger, nullable=False),
        sa.Column("tax_rate_bp", sa.Integer, nullable=False),
        sa.Column("net_minor", sa.BigInteger, nullable=False),
        sa.Column("tax_minor", sa.BigInteger, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_lines"),
        sa.UniqueConstraint("public_id", name="uq_invoice_lines_public_id"),
        sa.UniqueConstraint("invoice_id", "position", name="uq_invoice_lines_invoice_id_position"),
        _tfk("invoice_lines", "invoice_id", "invoices", "CASCADE"),
        _ck("invoice_lines", "public_id_format", r"public_id ~ '^[0-9a-f]{32}$'"),
        _ck("invoice_lines", "description_not_blank", "char_length(btrim(description)) > 0"),
        _ck("invoice_lines", "quantity_not_zero", "quantity_milli <> 0"),
        _ck("invoice_lines", "tax_rate_range", "tax_rate_bp BETWEEN 0 AND 10000"),
    )
    op.create_index("ix_invoice_lines_tenant_id", "invoice_lines", ["tenant_id"])
    op.create_index("ix_invoice_lines_tenant_invoice", "invoice_lines", ["tenant_id", "invoice_id"])

    op.create_table(
        "invoice_number_counters",
        *_tenant("invoice_number_counters"),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("next_value", sa.Integer, nullable=False),
        sa.Column("prefix", sa.String(12), nullable=False, server_default="RE-"),
        sa.PrimaryKeyConstraint("tenant_id", "year", name="pk_invoice_number_counters"),
        _ck("invoice_number_counters", "next_value_positive", "next_value >= 1"),
        _ck("invoice_number_counters", "prefix_format", r"prefix ~ '^[A-Za-z0-9\-_/]{0,12}$'"),
    )
    op.create_index("ix_invoice_number_counters_tenant_id", "invoice_number_counters", ["tenant_id"])

    op.create_table(
        "payments",
        sa.Column("id", UUID, primary_key=True), *_tenant("payments"),
        sa.Column("object_type", sa.String(24), nullable=False, server_default="payment"),
        sa.Column("invoice_id", UUID, nullable=False),
        sa.Column("paid_on", sa.Date, nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("method", sa.String(16), nullable=False, server_default="bank_transfer"),
        sa.Column("reference", sa.String(200)),
        sa.Column("reverses_payment_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_payments_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "reverses_payment_id", name=kurz("uq_payments_tenant_id_reverses_payment_id")),
        _typed("payments"), _tfk("payments", "invoice_id", "invoices"),
        _tfk("payments", "reverses_payment_id", "payments"),
        _ck("payments", "object_type_payment", "object_type = 'payment'"),
        _ck("payments", "amount_sign", "(reverses_payment_id IS NULL AND amount_minor > 0) OR "
                                       "(reverses_payment_id IS NOT NULL AND amount_minor < 0)"),
        _ck("payments", "currency_format", "currency ~ '^[A-Z]{3}$'"),
        _ck("payments", "method_valid", "method IN ('bank_transfer','cash','card','direct_debit','other')"),
    )
    op.create_index("ix_payments_tenant_id", "payments", ["tenant_id"])
    op.create_index("ix_payments_tenant_invoice", "payments", ["tenant_id", "invoice_id"])
    op.create_index("ix_payments_tenant_paid_on", "payments", ["tenant_id", "paid_on"])

    op.create_table(
        "invoice_followups",
        sa.Column("id", UUID, primary_key=True), *_tenant("invoice_followups"),
        sa.Column("invoice_id", UUID, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("channel", sa.String(10)),
        sa.Column("note", sa.String(5000), nullable=False, server_default=""),
        sa.Column("dunning_level", sa.Integer),
        sa.Column("next_follow_up", sa.Date),
        sa.Column("created_by_membership_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_followups"),
        _tfk("invoice_followups", "invoice_id", "invoices", "CASCADE"),
        _mfk("invoice_followups", "created_by_membership_id"),
        _ck("invoice_followups", "kind_valid", "kind IN ('contact_attempt','reminder_noted','dunning_level','note')"),
        _ck("invoice_followups", "channel_valid", CHANNEL),
        _ck("invoice_followups", "dunning_level_range", "dunning_level IS NULL OR dunning_level BETWEEN 0 AND 9"),
    )
    op.create_index("ix_invoice_followups_tenant_id", "invoice_followups", ["tenant_id"])
    op.create_index("ix_invoice_followups_tenant_invoice", "invoice_followups", ["tenant_id", "invoice_id"])

    op.create_table(
        "invoice_dispatches",
        sa.Column("id", UUID, primary_key=True), *_tenant("invoice_dispatches"),
        sa.Column("invoice_id", UUID, nullable=False),
        sa.Column("action", sa.String(12), nullable=False),
        sa.Column("channel", sa.String(10)),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_by_membership_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_invoice_dispatches"),
        _tfk("invoice_dispatches", "invoice_id", "invoices", "CASCADE"),
        _mfk("invoice_dispatches", "created_by_membership_id"),
        _ck("invoice_dispatches", "action_valid", "action IN ('sent','printed','exported')"),
        _ck("invoice_dispatches", "channel_valid", CHANNEL),
    )
    op.create_index("ix_invoice_dispatches_tenant_id", "invoice_dispatches", ["tenant_id"])
    op.create_index("ix_invoice_dispatches_tenant_invoice", "invoice_dispatches", ["tenant_id", "invoice_id"])

    op.execute("""
    CREATE FUNCTION ichq_invoice_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        IF OLD.status <> 'draft' THEN
          RAISE EXCEPTION 'ichq: ausgestellte Rechnung kann nicht gelöscht werden';
        END IF;
        RETURN OLD;
      END IF;
      IF OLD.status <> 'draft' THEN
        IF NEW.status = 'draft' THEN
          RAISE EXCEPTION 'ichq: ausgestellte Rechnung kann kein Entwurf mehr werden';
        END IF;
        IF OLD.status = 'cancelled' AND NEW.status <> 'cancelled' THEN
          RAISE EXCEPTION 'ichq: stornierte Rechnung bleibt storniert';
        END IF;
        IF (NEW.kind, NEW.cancels_invoice_id, NEW.customer_id, NEW.project_id, NEW.number, NEW.issue_date,
            NEW.service_date, NEW.due_date, NEW.currency, NEW.net_minor, NEW.tax_minor, NEW.gross_minor, NEW.notes,
            NEW.customer_snapshot, NEW.issued_at, NEW.issued_by_membership_id)
           IS DISTINCT FROM
           (OLD.kind, OLD.cancels_invoice_id, OLD.customer_id, OLD.project_id, OLD.number, OLD.issue_date,
            OLD.service_date, OLD.due_date, OLD.currency, OLD.net_minor, OLD.tax_minor, OLD.gross_minor, OLD.notes,
            OLD.customer_snapshot, OLD.issued_at, OLD.issued_by_membership_id) THEN
          RAISE EXCEPTION 'ichq: ausgestellte Rechnung ist unveränderlich — Korrektur nur per Storno';
        END IF;
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_invoices_guard BEFORE UPDATE OR DELETE ON invoices
      FOR EACH ROW EXECUTE FUNCTION ichq_invoice_guard();

    CREATE FUNCTION ichq_invoice_line_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE st text;
    BEGIN
      IF TG_OP = 'UPDATE' AND NEW.invoice_id <> OLD.invoice_id THEN
        RAISE EXCEPTION 'ichq: Position kann nicht in eine andere Rechnung wandern';
      END IF;
      SELECT status INTO st FROM invoices WHERE id = (CASE WHEN TG_OP = 'DELETE' THEN OLD.invoice_id
                                                           ELSE NEW.invoice_id END);
      IF st IS DISTINCT FROM 'draft' THEN
        RAISE EXCEPTION 'ichq: Positionen einer ausgestellten Rechnung sind unveränderlich';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_invoice_lines_guard BEFORE INSERT OR UPDATE OR DELETE ON invoice_lines
      FOR EACH ROW EXECUTE FUNCTION ichq_invoice_line_guard();

    CREATE FUNCTION ichq_payment_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r record; o record;
    BEGIN
      IF NEW.reverses_payment_id IS NOT NULL THEN       -- Rücknahme: genau der Gegenbetrag derselben Rechnung
        SELECT invoice_id, amount_minor, currency, reverses_payment_id AS rev INTO o FROM payments
          WHERE id = NEW.reverses_payment_id;
        IF o.invoice_id IS DISTINCT FROM NEW.invoice_id OR o.amount_minor <> -NEW.amount_minor
           OR o.currency <> NEW.currency OR o.rev IS NOT NULL THEN
          RAISE EXCEPTION 'ichq: Rücknahme muss genau eine Zahlung derselben Rechnung aufheben';
        END IF;
        RETURN NEW;
      END IF;
      SELECT status, kind, currency INTO r FROM invoices WHERE id = NEW.invoice_id;
      IF r.status IS NULL OR r.status IN ('draft', 'cancelled') OR r.kind <> 'invoice' THEN
        RAISE EXCEPTION 'ichq: Zahlung nur auf ausgestellte, nicht stornierte Rechnungen';
      END IF;
      IF r.currency <> NEW.currency THEN
        RAISE EXCEPTION 'ichq: Zahlungswährung weicht von der Rechnung ab';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_payments_guard BEFORE INSERT ON payments FOR EACH ROW EXECUTE FUNCTION ichq_payment_guard();

    CREATE TRIGGER trg_invoices_updated_at BEFORE UPDATE ON invoices
      FOR EACH ROW EXECUTE FUNCTION ichq_set_updated_at();
    """)
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM PUBLIC")
    op.execute("""
    GRANT SELECT, INSERT ON invoices TO ichq_app;
    GRANT UPDATE (customer_id, project_id, status, number, issue_date, service_date, due_date, currency, net_minor,
                  tax_minor, gross_minor, notes, customer_snapshot, responsible_membership_id, dunning_level,
                  next_follow_up, issued_at, issued_by_membership_id, sent_at, cancelled_at) ON invoices TO ichq_app;
    GRANT SELECT, INSERT, DELETE ON invoice_lines TO ichq_app;
    GRANT UPDATE (position, description, quantity_milli, unit, unit_price_minor, tax_rate_bp, net_minor, tax_minor)
      ON invoice_lines TO ichq_app;
    GRANT SELECT, INSERT ON invoice_number_counters TO ichq_app;
    GRANT UPDATE (next_value, prefix) ON invoice_number_counters TO ichq_app;
    GRANT SELECT, INSERT ON payments, invoice_followups, invoice_dispatches TO ichq_app;
    """)
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY p_{t}_tenant ON {t} TO ichq_app
                       USING (tenant_id = ichq_current_tenant())
                       WITH CHECK (tenant_id = ichq_current_tenant())""")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
    op.execute("DROP FUNCTION ichq_invoice_guard(); DROP FUNCTION ichq_invoice_line_guard(); "
               "DROP FUNCTION ichq_payment_guard();")
