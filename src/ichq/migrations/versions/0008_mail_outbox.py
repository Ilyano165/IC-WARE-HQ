"""E-Mail-Outbox: jede Mail wird in der Transaktion ihres Anlasses gespeichert und vom Worker versendet.

Revision: 0008_mail_outbox
Vorgänger: 0007_documents_scan

* Systemtabelle mit optionaler Firma (Einladungen) — RLS mit FORCE:
  ``ichq_app`` darf nur für die eigene Firma EINFÜGEN, ``ichq_auth`` nur ohne Firma (Reset, Sicherheitshinweise),
  beide dürfen nichts lesen. ``ichq_worker`` liest und ändert (Versand), ``ichq_platform`` legt Betreiberwarnungen
  an und kann Status lesen/erneut zustellen.
* Mails mit Token liegen nur verschlüsselt vor (``body_enc``) und werden nach Versand/Ablauf geleert.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0008_mail_outbox"
down_revision = "0007_documents_scan"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "mail_outbox",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tenant_id", UUID),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("body_text", sa.Text()),
        sa.Column("body_html", sa.Text()),
        sa.Column("body_enc", sa.LargeBinary()),
        sa.Column("dedup_key", sa.String(200)),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="6", nullable=False),
        sa.Column("available_at", TS, server_default=NOW, nullable=False),
        sa.Column("locked_at", TS),
        sa.Column("expires_at", TS),
        sa.Column("last_error", sa.String(300)),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("sent_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_mail_outbox"),
        sa.UniqueConstraint("dedup_key", name="uq_mail_outbox_dedup_key"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                name="fk_mail_outbox_tenant_id_tenants"),
        sa.CheckConstraint("status IN ('pending','sending','sent','failed','expired','cancelled')",
                           name="ck_mail_outbox_status_valid"),
        sa.CheckConstraint(r"kind ~ '^[a-z][a-z0-9_.]{2,39}$'", name="ck_mail_outbox_kind_format"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts BETWEEN 1 AND 20", name="ck_mail_outbox_attempts_range"),
        sa.CheckConstraint("status NOT IN ('pending','sending') OR body_enc IS NOT NULL OR body_text IS NOT NULL",
                           name="ck_mail_outbox_body_present"),
        sa.CheckConstraint("body_enc IS NULL OR (body_text IS NULL AND body_html IS NULL)",
                           name="ck_mail_outbox_body_one_form"),
    )
    op.create_index("ix_mail_outbox_due", "mail_outbox", ["available_at"],
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_index("ix_mail_outbox_recipient_sent", "mail_outbox", ["recipient", "sent_at"])
    op.execute("""
    ALTER TABLE mail_outbox ENABLE ROW LEVEL SECURITY;
    ALTER TABLE mail_outbox FORCE ROW LEVEL SECURITY;
    GRANT INSERT ON mail_outbox TO ichq_app, ichq_auth;
    GRANT SELECT, INSERT, UPDATE ON mail_outbox TO ichq_worker, ichq_platform;
    GRANT DELETE ON mail_outbox TO ichq_worker;   -- Aufräumen: abgeschlossene Mails nach 90 Tagen (Datensparsamkeit)
    CREATE POLICY p_mail_outbox_app_insert ON mail_outbox FOR INSERT TO ichq_app
      WITH CHECK (tenant_id = ichq_current_tenant());
    CREATE POLICY p_mail_outbox_auth_insert ON mail_outbox FOR INSERT TO ichq_auth
      WITH CHECK (tenant_id IS NULL);
    CREATE POLICY p_mail_outbox_betrieb ON mail_outbox TO ichq_worker, ichq_platform
      USING (true) WITH CHECK (true);
    """)


def downgrade() -> None:
    op.drop_table("mail_outbox")
