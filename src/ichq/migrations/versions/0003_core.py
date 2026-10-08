"""C0 Core-Plattform: Objektmodell, Verknüpfungen, Freigaben, Aktivitäten, Aufgaben, Kommentare,
Dokumente, Benachrichtigungen; öffentliche ID für Mitgliedschaften.

Revision: 0003_core
Vorgänger: 0002_authentication

Nur erweiternd (Expand): neue Tabellen, eine neue Spalte mit Standardwert. Typlisten sind hier
EINGEFROREN — eine Änderung der Registry braucht eine neue Migration (ADR-008).
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0003_core"
down_revision = "0002_authentication"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
PUBLIC_ID = r"public_id ~ '^[0-9a-f]{32}$'"
OBJECT_TYPES = ("asset", "company", "contract", "customer", "document", "employee", "entertainment", "invoice",
                "payment", "project", "receipt", "supplier", "task", "travel", "trip", "website")
LINK_RULE = (
    "(link_type = 'attachment' AND target_type IN ('document')) OR "
    "(link_type = 'billed_to' AND source_type IN ('invoice') AND target_type IN ('company', 'customer')) OR "
    "(link_type = 'evidence' AND source_type IN ('document', 'receipt') AND target_type IN ('asset', 'contract', "
    "'entertainment', 'invoice', 'payment', 'travel', 'trip')) OR "
    "(link_type = 'part_of' AND source_type IN ('contract', 'document', 'invoice', 'receipt', 'task', 'website') "
    "AND target_type IN ('project')) OR "
    "(link_type = 'party' AND source_type IN ('contract') AND target_type IN ('company', 'customer', 'employee', "
    "'supplier')) OR "
    "(link_type = 'pays' AND source_type IN ('payment') AND target_type IN ('invoice', 'receipt')) OR "
    "(link_type = 'related')"
)
TABLES = ["objects", "object_links", "object_grants", "activities", "comments", "comment_mentions", "tasks",
          "documents", "notifications"]


def _tenant(table: str) -> list[sa.schema.SchemaItem]:
    return [sa.Column("tenant_id", UUID, nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                    name=f"fk_{table}_tenant_id_tenants")]


def _mfk(table: str, col: str, ondelete: str = "RESTRICT") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], ["memberships.tenant_id", "memberships.id"],
                                   ondelete=ondelete, name=f"fk_{table}_tenant_id_{col}_memberships")


def _ofk(table: str, col: str, ondelete: str = "RESTRICT") -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col], ["objects.tenant_id", "objects.id"],
                                   ondelete=ondelete, name=f"fk_{table}_tenant_id_{col}_objects")


def _typed(table: str, col: str, typ_col: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", col, typ_col], ["objects.tenant_id", "objects.id", "objects.type"],
                                   ondelete="CASCADE", name=f"fk_{table}_tenant_id_{col}_{typ_col}_objects")


def upgrade() -> None:
    # --- Mitgliedschaften: öffentliche ID (Expand: Standardwert füllt Bestand) ----------
    op.add_column("memberships", sa.Column("public_id", sa.String(32), nullable=False,
                                           server_default=sa.text("replace(gen_random_uuid()::text, '-', '')")))
    op.create_unique_constraint("uq_memberships_public_id", "memberships", ["public_id"])
    op.create_check_constraint("ck_memberships_public_id_format", "memberships", PUBLIC_ID)

    types = ", ".join(f"'{t}'" for t in OBJECT_TYPES)
    op.create_table(
        "objects",
        sa.Column("id", UUID, primary_key=True), *_tenant("objects"),
        sa.Column("type", sa.String(24), nullable=False),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("search_text", sa.Text),
        sa.Column("search_vector", pg.TSVECTOR, sa.Computed(
            "to_tsvector('simple'::regconfig, (title::text || ' '::text) || COALESCE(search_text, ''::text))",
            persisted=True)),
        sa.Column("created_by_membership_id", UUID),
        sa.Column("archived_at", TS),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_objects"),
        sa.UniqueConstraint("public_id", name="uq_objects_public_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_objects_tenant_id_id"),
        sa.UniqueConstraint("tenant_id", "id", "type", name="uq_objects_tenant_id_id_type"),
        _mfk("objects", "created_by_membership_id"),
        sa.CheckConstraint(f"type IN ({types})", name="ck_objects_type_known"),
        sa.CheckConstraint(PUBLIC_ID, name="ck_objects_public_id_format"),
        sa.CheckConstraint("char_length(btrim(title)) > 0", name="ck_objects_title_not_blank"),
        sa.CheckConstraint("search_text IS NULL OR char_length(search_text) <= 4000",
                           name="ck_objects_search_text_length"),
    )
    op.create_index("ix_objects_tenant_id", "objects", ["tenant_id"])
    op.create_index("ix_objects_tenant_type_created", "objects", ["tenant_id", "type", "created_at"])
    op.create_index("ix_objects_search_vector", "objects", ["search_vector"], postgresql_using="gin")

    op.create_table(
        "object_links",
        sa.Column("id", UUID, primary_key=True), *_tenant("object_links"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("link_type", sa.String(24), nullable=False),
        sa.Column("source_id", UUID, nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("target_id", UUID, nullable=False),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("created_by_membership_id", UUID),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_object_links"),
        sa.UniqueConstraint("public_id", name="uq_object_links_public_id"),
        sa.UniqueConstraint("tenant_id", "source_id", "target_id", "link_type",
                            name="uq_object_links_tenant_id_source_id_target_id_link_type"),
        _typed("object_links", "source_id", "source_type"),
        _typed("object_links", "target_id", "target_type"),
        _mfk("object_links", "created_by_membership_id"),
        sa.CheckConstraint("source_id <> target_id", name="ck_object_links_not_self"),
        sa.CheckConstraint(LINK_RULE, name="ck_object_links_rule"),
        sa.CheckConstraint(PUBLIC_ID, name="ck_object_links_public_id_format"),
    )
    op.create_index("ix_object_links_tenant_id", "object_links", ["tenant_id"])
    op.create_index("ix_object_links_tenant_target", "object_links", ["tenant_id", "target_id"])

    op.create_table(
        "object_grants",
        *_tenant("object_grants"),
        sa.Column("object_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column("granted_by_membership_id", UUID),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("object_id", "membership_id", name="pk_object_grants"),
        _ofk("object_grants", "object_id", "CASCADE"),
        _mfk("object_grants", "membership_id", "CASCADE"),
        _mfk("object_grants", "granted_by_membership_id"),
    )
    op.create_index("ix_object_grants_tenant_id", "object_grants", ["tenant_id"])
    op.create_index("ix_object_grants_tenant_membership", "object_grants", ["tenant_id", "membership_id"])

    op.create_table(
        "activities",
        sa.Column("id", UUID, primary_key=True), *_tenant("activities"),
        sa.Column("object_id", UUID, nullable=False),
        sa.Column("actor_membership_id", UUID),
        sa.Column("verb", sa.String(48), nullable=False),
        sa.Column("data", pg.JSONB, nullable=False, server_default="{}"),
        sa.Column("occurred_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_activities"),
        _ofk("activities", "object_id"),
        _mfk("activities", "actor_membership_id"),
        sa.CheckConstraint(r"verb ~ '^[a-z][a-z_]*\.[a-z][a-z_]*$'", name="ck_activities_verb_format"),
    )
    op.create_index("ix_activities_tenant_id", "activities", ["tenant_id"])
    op.create_index("ix_activities_tenant_time", "activities", ["tenant_id", "occurred_at", "id"])
    op.create_index("ix_activities_tenant_object_time", "activities", ["tenant_id", "object_id", "occurred_at"])

    op.create_table(
        "comments",
        sa.Column("id", UUID, primary_key=True), *_tenant("comments"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("object_id", UUID, nullable=False),
        sa.Column("author_membership_id", UUID, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False, server_default="note"),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("edited_at", TS),
        sa.Column("deleted_at", TS),
        sa.Column("deleted_by_membership_id", UUID),
        sa.PrimaryKeyConstraint("id", name="pk_comments"),
        sa.UniqueConstraint("public_id", name="uq_comments_public_id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_comments_tenant_id_id"),
        _ofk("comments", "object_id"),
        _mfk("comments", "author_membership_id"),
        _mfk("comments", "deleted_by_membership_id"),
        sa.CheckConstraint("kind IN ('note','question')", name="ck_comments_kind_valid"),
        sa.CheckConstraint("char_length(body) <= 10000", name="ck_comments_body_length"),
        sa.CheckConstraint("deleted_at IS NULL OR body = ''", name="ck_comments_deleted_is_empty"),
        sa.CheckConstraint("deleted_at IS NOT NULL OR char_length(btrim(body)) > 0",
                           name="ck_comments_body_not_blank"),
        sa.CheckConstraint(PUBLIC_ID, name="ck_comments_public_id_format"),
    )
    op.create_index("ix_comments_tenant_id", "comments", ["tenant_id"])
    op.create_index("ix_comments_tenant_object_created", "comments", ["tenant_id", "object_id", "created_at"])

    op.create_table(
        "comment_mentions",
        *_tenant("comment_mentions"),
        sa.Column("comment_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.PrimaryKeyConstraint("comment_id", "membership_id", name="pk_comment_mentions"),
        sa.ForeignKeyConstraint(["tenant_id", "comment_id"], ["comments.tenant_id", "comments.id"],
                                ondelete="CASCADE", name="fk_comment_mentions_tenant_id_comment_id_comments"),
        _mfk("comment_mentions", "membership_id", "CASCADE"),
    )
    op.create_index("ix_comment_mentions_tenant_id", "comment_mentions", ["tenant_id"])

    op.create_table(
        "tasks",
        sa.Column("id", UUID, primary_key=True), *_tenant("tasks"),
        sa.Column("object_type", sa.String(24), nullable=False, server_default="task"),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(8), nullable=False, server_default="normal"),
        sa.Column("assignee_membership_id", UUID),
        sa.Column("due_date", sa.Date),
        sa.Column("subject_object_id", UUID),
        sa.Column("source_comment_id", UUID),
        sa.Column("completed_at", TS),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
        _typed("tasks", "id", "object_type"),
        _mfk("tasks", "assignee_membership_id"),
        _ofk("tasks", "subject_object_id"),
        sa.ForeignKeyConstraint(["tenant_id", "source_comment_id"], ["comments.tenant_id", "comments.id"],
                                ondelete="RESTRICT", name="fk_tasks_tenant_id_source_comment_id_comments"),
        sa.CheckConstraint("object_type = 'task'", name="ck_tasks_object_type_task"),
        sa.CheckConstraint("status IN ('open','in_progress','blocked','done','cancelled')", name="ck_tasks_status_valid"),
        sa.CheckConstraint("priority IN ('low','normal','high','urgent')", name="ck_tasks_priority_valid"),
        sa.CheckConstraint("char_length(description) <= 20000", name="ck_tasks_description_length"),
        sa.CheckConstraint("subject_object_id IS NULL OR subject_object_id <> id", name="ck_tasks_subject_not_self"),
    )
    op.create_index("ix_tasks_tenant_id", "tasks", ["tenant_id"])
    op.create_index("ix_tasks_tenant_assignee", "tasks", ["tenant_id", "assignee_membership_id"])
    op.create_index("ix_tasks_tenant_status_due", "tasks", ["tenant_id", "status", "due_date"])

    op.create_table(
        "documents",
        sa.Column("id", UUID, primary_key=True), *_tenant("documents"),
        sa.Column("object_type", sa.String(24), nullable=False, server_default="document"),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(200), nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("scan_status", sa.String(16), nullable=False, server_default="quarantined"),
        sa.Column("review_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reviewed_by_membership_id", UUID),
        sa.Column("reviewed_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        _typed("documents", "id", "object_type"),
        _mfk("documents", "reviewed_by_membership_id"),
        sa.CheckConstraint("object_type = 'document'", name="ck_documents_object_type_document"),
        sa.CheckConstraint("scan_status IN ('quarantined','clean','infected')", name="ck_documents_scan_status_valid"),
        sa.CheckConstraint("review_status IN ('pending','approved','rejected')",
                           name="ck_documents_review_status_valid"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_documents_size_positive"),
        sa.CheckConstraint(r"sha256 ~ '^[0-9a-f]{64}$'", name="ck_documents_sha256_format"),
        sa.CheckConstraint("(review_status = 'pending') = (reviewed_at IS NULL)",
                           name="ck_documents_review_consistent"),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])

    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True), *_tenant("notifications"),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("recipient_membership_id", UUID, nullable=False),
        sa.Column("kind", sa.String(48), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default="in_app"),
        sa.Column("object_id", UUID),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("dedup_key", sa.String(160)),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.Column("read_at", TS),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.UniqueConstraint("public_id", name="uq_notifications_public_id"),
        sa.UniqueConstraint("tenant_id", "recipient_membership_id", "dedup_key",
                            name="uq_notifications_tenant_id_recipient_membership_id_dedup_key"),
        _mfk("notifications", "recipient_membership_id", "CASCADE"),
        _ofk("notifications", "object_id", "CASCADE"),
        sa.CheckConstraint(r"kind ~ '^[a-z][a-z_]*\.[a-z][a-z_]*$'", name="ck_notifications_kind_format"),
        sa.CheckConstraint("channel IN ('in_app','email','push')", name="ck_notifications_channel_valid"),
        sa.CheckConstraint(PUBLIC_ID, name="ck_notifications_public_id_format"),
    )
    op.create_index("ix_notifications_tenant_id", "notifications", ["tenant_id"])
    op.create_index("ix_notifications_tenant_recipient_created", "notifications",
                    ["tenant_id", "recipient_membership_id", "created_at"])

    for t in ("objects", "tasks"):
        op.execute(f"CREATE TRIGGER trg_{t}_updated_at BEFORE UPDATE ON {t} "
                   f"FOR EACH ROW EXECUTE FUNCTION ichq_set_updated_at()")

    # --- Rechte: nur was die Services brauchen. Aktivitäten: nur anhängend. ------------
    op.execute(f"REVOKE ALL ON {', '.join(TABLES)} FROM PUBLIC")
    op.execute("""
    GRANT SELECT, INSERT ON objects, activities, comment_mentions TO ichq_app;
    GRANT UPDATE (title, search_text, archived_at) ON objects TO ichq_app;
    GRANT SELECT, INSERT, DELETE ON object_links, object_grants TO ichq_app;
    GRANT SELECT, INSERT ON comments TO ichq_app;
    GRANT UPDATE (body, edited_at, deleted_at, deleted_by_membership_id) ON comments TO ichq_app;
    GRANT SELECT, INSERT ON tasks TO ichq_app;
    GRANT UPDATE (description, status, priority, assignee_membership_id, due_date, completed_at) ON tasks TO ichq_app;
    GRANT SELECT, INSERT ON documents TO ichq_app;
    GRANT UPDATE (review_status, reviewed_by_membership_id, reviewed_at) ON documents TO ichq_app;
    GRANT SELECT, INSERT ON notifications TO ichq_app;
    GRANT UPDATE (read_at) ON notifications TO ichq_app;
    """)

    # --- Row-Level Security ------------------------------------------------------------
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        if t == "activities":
            op.execute("CREATE POLICY p_activities_tenant_read ON activities FOR SELECT TO ichq_app "
                       "USING (tenant_id = ichq_current_tenant())")
            op.execute("CREATE POLICY p_activities_tenant_insert ON activities FOR INSERT TO ichq_app "
                       "WITH CHECK (tenant_id = ichq_current_tenant())")
        else:
            op.execute(f"""CREATE POLICY p_{t}_tenant ON {t} TO ichq_app
                           USING (tenant_id = ichq_current_tenant())
                           WITH CHECK (tenant_id = ichq_current_tenant())""")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
    op.drop_constraint("ck_memberships_public_id_format", "memberships", type_="check")
    op.drop_constraint("uq_memberships_public_id", "memberships", type_="unique")
    op.drop_column("memberships", "public_id")
