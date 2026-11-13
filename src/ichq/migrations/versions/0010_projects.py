"""Projekte: projects, project_members, time_entries; Freigabequelle ``project_team`` (ADR-020).

Revision: 0010_projects
Vorgänger: 0009_crm
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.datenpflege import ohne_force

revision = "0010_projects"
down_revision = "0009_crm"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
TABLES = ["projects", "project_members", "time_entries"]


def _tenant(table: str) -> list[sa.schema.SchemaItem]:
    return [sa.Column("tenant_id", UUID, nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                    name=f"fk_{table}_tenant_id_tenants")]


def _mfk(table: str, col: str, ondelete: str = "RESTRICT") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], ["memberships.tenant_id", "memberships.id"],
                                   ondelete=ondelete, name=f"fk_{table}_tenant_id_{col}_memberships")


def _tfk(table: str, col: str, ziel: str, ondelete: str = "RESTRICT") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], [f"{ziel}.tenant_id", f"{ziel}.id"], ondelete=ondelete,
                                   name=f"fk_{table}_tenant_id_{col}_{ziel}")


def _quellen(sql: str) -> None:
    op.execute("ALTER TABLE object_grants DROP CONSTRAINT ck_object_grants_ck_object_grants_source_valid")
    op.execute(f"ALTER TABLE object_grants ADD CONSTRAINT ck_object_grants_ck_object_grants_source_valid CHECK ({sql})")


def upgrade() -> None:
    _quellen("source IN ('manual', 'project_team', 'task_assignment')")
    op.create_table(
        "projects",
        sa.Column("id", UUID, primary_key=True), *_tenant("projects"),
        sa.Column("object_type", sa.String(24), nullable=False, server_default="project"),
        sa.Column("customer_id", UUID),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(12), nullable=False, server_default="planned"),
        sa.Column("priority", sa.String(8), nullable=False, server_default="normal"),
        sa.Column("owner_membership_id", UUID),
        sa.Column("start_date", sa.Date),
        sa.Column("end_date", sa.Date),
        sa.Column("budget_minor", sa.BigInteger),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("completed_at", TS),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_projects_tenant_id_id"),
        sa.ForeignKeyConstraint(["tenant_id", "id", "object_type"], ["objects.tenant_id", "objects.id", "objects.type"],
                                ondelete="CASCADE", name="fk_projects_tenant_id_id_object_type_objects"),
        _tfk("projects", "customer_id", "customers"), _mfk("projects", "owner_membership_id"),
        sa.CheckConstraint("object_type = 'project'", name="ck_projects_object_type_project"),
        sa.CheckConstraint("status IN ('planned','active','on_hold','completed','cancelled')",
                           name="ck_projects_status_valid"),
        sa.CheckConstraint("priority IN ('low','normal','high','urgent')", name="ck_projects_priority_valid"),
        sa.CheckConstraint("end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
                           name="ck_projects_dates_ordered"),
        sa.CheckConstraint("budget_minor IS NULL OR budget_minor >= 0", name="ck_projects_budget_not_negative"),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_projects_currency_format"),
        sa.CheckConstraint("char_length(description) <= 20000", name="ck_projects_description_length"),
        sa.CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL)",
                           name="ck_projects_completed_consistent"),
    )
    op.create_index("ix_projects_tenant_id", "projects", ["tenant_id"])
    op.create_index("ix_projects_tenant_status", "projects", ["tenant_id", "status"])
    op.create_index("ix_projects_tenant_customer", "projects", ["tenant_id", "customer_id"])

    op.create_table(
        "project_members",
        *_tenant("project_members"),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column("role", sa.String(100)),
        sa.Column("hourly_cost_minor", sa.BigInteger),
        sa.Column("added_by_membership_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("project_id", "membership_id", name="pk_project_members"),
        _tfk("project_members", "project_id", "projects", "CASCADE"),
        _mfk("project_members", "membership_id", "CASCADE"), _mfk("project_members", "added_by_membership_id"),
        sa.CheckConstraint("hourly_cost_minor IS NULL OR hourly_cost_minor >= 0",
                           name="ck_project_members_cost_not_negative"),
    )
    op.create_index("ix_project_members_tenant_id", "project_members", ["tenant_id"])
    op.create_index("ix_project_members_tenant_membership", "project_members", ["tenant_id", "membership_id"])

    op.create_table(
        "time_entries",
        sa.Column("id", UUID, primary_key=True), *_tenant("time_entries"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column("work_date", sa.Date, nullable=False),
        sa.Column("minutes", sa.Integer, nullable=False),
        sa.Column("billable", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("created_by_membership_id", UUID),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.PrimaryKeyConstraint("id", name="pk_time_entries"),
        sa.UniqueConstraint("public_id", name="uq_time_entries_public_id"),
        _tfk("time_entries", "project_id", "projects", "CASCADE"),
        _mfk("time_entries", "membership_id"), _mfk("time_entries", "created_by_membership_id"),
        sa.CheckConstraint(r"public_id ~ '^[0-9a-f]{32}$'", name="ck_time_entries_public_id_format"),
        sa.CheckConstraint("minutes > 0 AND minutes <= 1440", name="ck_time_entries_minutes_range"),
    )
    op.create_index("ix_time_entries_tenant_id", "time_entries", ["tenant_id"])
    op.create_index("ix_time_entries_tenant_project_date", "time_entries", ["tenant_id", "project_id", "work_date"])

    op.execute("CREATE TRIGGER trg_projects_updated_at BEFORE UPDATE ON projects "
               "FOR EACH ROW EXECUTE FUNCTION ichq_set_updated_at()")
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM PUBLIC")
    op.execute("""
    GRANT SELECT, INSERT ON projects TO ichq_app;
    GRANT UPDATE (customer_id, description, status, priority, owner_membership_id, start_date, end_date, budget_minor,
                  currency, completed_at) ON projects TO ichq_app;
    GRANT SELECT, INSERT, DELETE ON project_members TO ichq_app;
    GRANT UPDATE (role, hourly_cost_minor) ON project_members TO ichq_app;
    GRANT SELECT, INSERT, DELETE ON time_entries TO ichq_app;
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
    with ohne_force("object_grants"):
        op.execute("DELETE FROM object_grants WHERE source = 'project_team'")
    _quellen("source IN ('manual', 'task_assignment')")
