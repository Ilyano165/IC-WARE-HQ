"""CRM: Kunden, Kontaktpersonen, Anfragen; neue Objekttypen ``inquiry`` und ``deadline`` (ADR-020).

Revision: 0009_crm
Vorgänger: 0008_mail_outbox

Nur erweiternd. Die Typliste von ``objects`` ist hier EINGEFROREN (wie in 0003): Registry-Änderung ⇒ neue Migration.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.datenpflege import ohne_force

revision = "0009_crm"
down_revision = "0008_mail_outbox"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TYPES_ALT = ("asset", "company", "contract", "customer", "document", "employee", "entertainment", "invoice",
             "payment", "project", "receipt", "supplier", "task", "travel", "trip", "website")
TYPES_NEU = tuple(sorted((*TYPES_ALT, "deadline", "inquiry")))
TABLES = ["customers", "customer_contacts", "inquiries"]


def _types(werte: tuple[str, ...]) -> str:
    return "type IN (" + ", ".join(f"'{t}'" for t in werte) + ")"


def _tenant(table: str) -> list[sa.schema.SchemaItem]:
    return [sa.Column("tenant_id", UUID, nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                    name=f"fk_{table}_tenant_id_tenants")]


def _typed(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", "id", "object_type"], ["objects.tenant_id", "objects.id", "objects.type"],
                                   ondelete="CASCADE", name=f"fk_{table}_tenant_id_id_object_type_objects")


def _mfk(table: str, col: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], ["memberships.tenant_id", "memberships.id"],
                                   ondelete="RESTRICT", name=f"fk_{table}_tenant_id_{col}_memberships")


def _tfk(table: str, col: str, ziel: str, ondelete: str = "RESTRICT") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], [f"{ziel}.tenant_id", f"{ziel}.id"], ondelete=ondelete,
                                   name=f"fk_{table}_tenant_id_{col}_{ziel}")


def _set_types(werte: tuple[str, ...]) -> None:
    op.execute("ALTER TABLE objects DROP CONSTRAINT ck_objects_ck_objects_type_known")
    op.execute(f"ALTER TABLE objects ADD CONSTRAINT ck_objects_ck_objects_type_known CHECK ({_types(werte)})")


def upgrade() -> None:
    _set_types(TYPES_NEU)
    op.create_table(
        "customers",
        sa.Column("id", UUID, primary_key=True), *_tenant("customers"),
        sa.Column("object_type", sa.String(24), nullable=False, server_default="customer"),
        sa.Column("kind", sa.String(12), nullable=False, server_default="company"),
        sa.Column("status", sa.String(12), nullable=False, server_default="active"),
        sa.Column("legal_name", sa.String(300)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(50)),
        sa.Column("website", sa.String(300)),
        sa.Column("street", sa.String(200)),
        sa.Column("postal_code", sa.String(20)),
        sa.Column("city", sa.String(100)),
        sa.Column("country", sa.String(2)),
        sa.Column("vat_id", sa.String(30)),
        sa.Column("owner_membership_id", UUID),
        sa.Column("notes", sa.Text, nullable=False, server_default=""),
        sa.Column("dedup_key", sa.String(300), nullable=False),
        sa.Column("merged_into_id", UUID),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_customers"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
        _typed("customers"), _mfk("customers", "owner_membership_id"),
        _tfk("customers", "merged_into_id", "customers"),
        sa.CheckConstraint("object_type = 'customer'", name="ck_customers_object_type_customer"),
        sa.CheckConstraint("kind IN ('company', 'person')", name="ck_customers_kind_valid"),
        sa.CheckConstraint("status IN ('lead', 'active', 'inactive')", name="ck_customers_status_valid"),
        sa.CheckConstraint("country IS NULL OR country ~ '^[A-Z]{2}$'", name="ck_customers_country_format"),
        sa.CheckConstraint("char_length(notes) <= 20000", name="ck_customers_notes_length"),
        sa.CheckConstraint("merged_into_id IS NULL OR merged_into_id <> id", name="ck_customers_merge_not_self"),
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])
    op.create_index("ix_customers_tenant_dedup", "customers", ["tenant_id", "dedup_key"])
    op.create_index("ix_customers_tenant_email", "customers", ["tenant_id", "email"])

    op.create_table(
        "customer_contacts",
        sa.Column("id", UUID, primary_key=True), *_tenant("customer_contacts"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("customer_id", UUID, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(100)),
        sa.Column("email", sa.String(320)),
        sa.Column("phone", sa.String(50)),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_customer_contacts"),
        sa.UniqueConstraint("public_id", name="uq_customer_contacts_public_id"),
        _tfk("customer_contacts", "customer_id", "customers", "CASCADE"),
        sa.CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="ck_customer_contacts_public_id_format"),
        sa.CheckConstraint("char_length(btrim(name)) > 0", name="ck_customer_contacts_name_not_blank"),
    )
    op.create_index("ix_customer_contacts_tenant_id", "customer_contacts", ["tenant_id"])
    op.create_index("ix_customer_contacts_tenant_customer", "customer_contacts", ["tenant_id", "customer_id"])

    op.create_table(
        "inquiries",
        sa.Column("id", UUID, primary_key=True), *_tenant("inquiries"),
        sa.Column("object_type", sa.String(24), nullable=False, server_default="inquiry"),
        sa.Column("customer_id", UUID),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("source", sa.String(12), nullable=False, server_default="other"),
        sa.Column("received_on", sa.Date, nullable=False),
        sa.Column("priority", sa.String(8), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(12), nullable=False, server_default="new"),
        sa.Column("owner_membership_id", UUID),
        sa.Column("next_action", sa.String(300)),
        sa.Column("follow_up_on", sa.Date),
        sa.Column("closed_at", TS),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_inquiries"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_inquiries_tenant_id_id"),
        _typed("inquiries"), _tfk("inquiries", "customer_id", "customers"), _mfk("inquiries", "owner_membership_id"),
        sa.CheckConstraint("object_type = 'inquiry'", name="ck_inquiries_object_type_inquiry"),
        sa.CheckConstraint("status IN ('new', 'in_progress', 'waiting', 'won', 'lost', 'closed')",
                           name="ck_inquiries_status_valid"),
        sa.CheckConstraint("source IN ('email', 'phone', 'website', 'referral', 'event', 'other')",
                           name="ck_inquiries_source_valid"),
        sa.CheckConstraint("priority IN ('low', 'normal', 'high', 'urgent')", name="ck_inquiries_priority_valid"),
        sa.CheckConstraint("char_length(description) <= 20000", name="ck_inquiries_description_length"),
        sa.CheckConstraint("(status IN ('won','lost','closed')) = (closed_at IS NOT NULL)",
                           name="ck_inquiries_closed_consistent"),
    )
    op.create_index("ix_inquiries_tenant_id", "inquiries", ["tenant_id"])
    op.create_index("ix_inquiries_tenant_status_follow", "inquiries", ["tenant_id", "status", "follow_up_on"])
    op.create_index("ix_inquiries_tenant_customer", "inquiries", ["tenant_id", "customer_id"])

    for t in ("customers", "inquiries"):
        op.execute(f"CREATE TRIGGER trg_{t}_updated_at BEFORE UPDATE ON {t} "
                   f"FOR EACH ROW EXECUTE FUNCTION ichq_set_updated_at()")
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM PUBLIC")
    op.execute("""
    GRANT SELECT, INSERT ON customers TO ichq_app;
    GRANT UPDATE (kind, status, legal_name, email, phone, website, street, postal_code, city, country, vat_id,
                  owner_membership_id, notes, dedup_key, merged_into_id) ON customers TO ichq_app;
    GRANT SELECT, INSERT, DELETE ON customer_contacts TO ichq_app;
    GRANT UPDATE (customer_id, name, role, email, phone, is_primary) ON customer_contacts TO ichq_app;
    GRANT SELECT, INSERT ON inquiries TO ichq_app;
    GRANT UPDATE (customer_id, description, source, received_on, priority, status, owner_membership_id, next_action,
                  follow_up_on, closed_at) ON inquiries TO ichq_app;
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
    with ohne_force("objects"):
        op.execute("DELETE FROM objects WHERE type IN ('deadline', 'inquiry')")
    _set_types(TYPES_ALT)
