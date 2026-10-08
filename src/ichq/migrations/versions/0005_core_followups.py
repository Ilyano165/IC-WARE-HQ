"""C0-Nachträge: Herkunft von Objektfreigaben, Kommentar-Historie (Tombstones), Löschgrund.

Revision: 0005_core_followups
Vorgänger: 0004_m3_tenancy

* ``object_grants.source``: ``manual`` (über die API erteilt) oder ``task_assignment`` (automatisch durch
  Zuweisung). Beide können nebeneinander bestehen — der Primärschlüssel enthält deshalb die Quelle.
  Bestehende Zeilen werden zu ``manual`` (die Herkunft war bisher nicht gespeichert).
* ``comment_revisions``: jede Fassung eines Kommentars, geschrieben von einem Trigger (SECURITY DEFINER) —
  nicht vom Anwendungscode. Die App-Rolle darf sie nur LESEN; UPDATE/DELETE/TRUNCATE verhindert ein Trigger
  auch für den Besitzer.
* Gelöschte Kommentare: Grund ist Pflicht; nach dem Löschen ist der Kommentar unveränderlich.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.datenpflege import ohne_force

revision = "0005_core_followups"
down_revision = "0004_m3_tenancy"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    # --- Freigaben: Quelle -----------------------------------------------------------
    op.add_column("object_grants", sa.Column("source", sa.String(24), nullable=False, server_default="manual"))
    op.create_check_constraint("ck_object_grants_source_valid", "object_grants",
                               "source IN ('manual','task_assignment')")
    op.drop_constraint("pk_object_grants", "object_grants", type_="primary")
    op.create_primary_key("pk_object_grants", "object_grants", ["object_id", "membership_id", "source"])

    # --- Kommentare: Löschgrund, keine Änderung nach dem Löschen -------------------------
    op.add_column("comments", sa.Column("delete_reason", sa.String(500)))
    with ohne_force("comments"):    # sonst sieht ichq_owner wegen RLS keine Zeile (datenpflege.py)
        op.execute("UPDATE comments SET delete_reason = 'vor Migration 0005 gelöscht (Grund nicht erfasst)' "
                   "WHERE deleted_at IS NOT NULL")
    op.create_check_constraint("ck_comments_delete_reason_required", "comments",
                               "deleted_at IS NULL OR char_length(btrim(delete_reason)) >= 3")
    op.execute("GRANT UPDATE (delete_reason) ON comments TO ichq_app")
    op.execute("""
    CREATE FUNCTION ichq_comment_frozen() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.deleted_at IS NOT NULL THEN
        RAISE EXCEPTION 'Gelöschter Kommentar % ist unveränderlich', OLD.id USING ERRCODE = 'insufficient_privilege';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER trg_comments_frozen BEFORE UPDATE ON comments
      FOR EACH ROW EXECUTE FUNCTION ichq_comment_frozen();
    """)

    # --- Kommentar-Historie --------------------------------------------------------------
    op.create_table(
        "comment_revisions",
        sa.Column("seq", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("comment_id", UUID, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("actor_membership_id", UUID),
        sa.Column("reason", sa.String(500)),
        sa.Column("recorded_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("seq", name="pk_comment_revisions"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                name="fk_comment_revisions_tenant_id_tenants"),
        sa.ForeignKeyConstraint(["tenant_id", "comment_id"], ["comments.tenant_id", "comments.id"],
                                ondelete="RESTRICT", name="fk_comment_revisions_tenant_id_comment_id_comments"),
        sa.ForeignKeyConstraint(["tenant_id", "actor_membership_id"], ["memberships.tenant_id", "memberships.id"],
                                ondelete="RESTRICT", name="fk_comment_revisions_tenant_id_actor_membership_id_memberships"),
        sa.CheckConstraint("kind IN ('created','edited','deleted')", name="ck_comment_revisions_kind_valid"),
    )
    op.create_index("ix_comment_revisions_tenant_id", "comment_revisions", ["tenant_id"])
    op.create_index("ix_comment_revisions_tenant_comment", "comment_revisions", ["tenant_id", "comment_id", "seq"])
    op.execute("""
    REVOKE ALL ON comment_revisions FROM PUBLIC;
    GRANT SELECT ON comment_revisions TO ichq_app;
    ALTER TABLE comment_revisions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE comment_revisions FORCE ROW LEVEL SECURITY;
    CREATE POLICY p_comment_revisions_tenant_read ON comment_revisions FOR SELECT TO ichq_app
      USING (tenant_id = ichq_current_tenant());
    -- Nur die Trigger-Funktion (läuft als Besitzer) schreibt — und nur in die Firma der Kommentarzeile.
    CREATE POLICY p_comment_revisions_trigger_insert ON comment_revisions FOR INSERT TO ichq_owner
      WITH CHECK (true);
    CREATE TRIGGER trg_comment_revisions_append_only BEFORE UPDATE OR DELETE ON comment_revisions
      FOR EACH ROW EXECUTE FUNCTION ichq_append_only();
    CREATE TRIGGER trg_comment_revisions_no_truncate BEFORE TRUNCATE ON comment_revisions
      FOR EACH STATEMENT EXECUTE FUNCTION ichq_append_only();

    CREATE FUNCTION ichq_comment_history() RETURNS trigger LANGUAGE plpgsql
      SECURITY DEFINER SET search_path = public, pg_temp AS $$
    BEGIN
      IF TG_OP = 'INSERT' THEN
        INSERT INTO comment_revisions(tenant_id, comment_id, kind, body, actor_membership_id)
        VALUES (NEW.tenant_id, NEW.id, 'created', NEW.body, NEW.author_membership_id);
      ELSIF NEW.deleted_at IS NOT NULL AND OLD.deleted_at IS NULL THEN
        INSERT INTO comment_revisions(tenant_id, comment_id, kind, body, actor_membership_id, reason)
        VALUES (NEW.tenant_id, NEW.id, 'deleted', OLD.body, NEW.deleted_by_membership_id, NEW.delete_reason);
      ELSIF NEW.body IS DISTINCT FROM OLD.body THEN
        INSERT INTO comment_revisions(tenant_id, comment_id, kind, body, actor_membership_id)
        VALUES (NEW.tenant_id, NEW.id, 'edited', NEW.body, NEW.author_membership_id);
      END IF;
      RETURN NULL;
    END $$;
    REVOKE ALL ON FUNCTION ichq_comment_history() FROM PUBLIC;
    CREATE TRIGGER trg_comments_history AFTER INSERT OR UPDATE ON comments
      FOR EACH ROW EXECUTE FUNCTION ichq_comment_history();
    """)
    # Bestand (vor 0005 angelegte Kommentare): erste Fassung nachtragen, soweit der Text noch da ist
    with ohne_force("comments", "comment_revisions"):
        op.execute("""INSERT INTO comment_revisions(tenant_id, comment_id, kind, body, actor_membership_id,
                                                    recorded_at)
                      SELECT tenant_id, id, 'created', body, author_membership_id, created_at FROM comments""")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_comments_history ON comments")
    op.execute("DROP TRIGGER IF EXISTS trg_comments_frozen ON comments")
    op.drop_table("comment_revisions")
    op.execute("DROP FUNCTION IF EXISTS ichq_comment_history(), ichq_comment_frozen()")
    op.drop_constraint("ck_comments_delete_reason_required", "comments", type_="check")
    op.drop_column("comments", "delete_reason")
    op.drop_constraint("pk_object_grants", "object_grants", type_="primary")
    with ohne_force("object_grants"):
        op.execute("DELETE FROM object_grants WHERE source <> 'manual'")
    op.create_primary_key("pk_object_grants", "object_grants", ["object_id", "membership_id"])
    op.drop_constraint("ck_object_grants_source_valid", "object_grants", type_="check")
    op.drop_column("object_grants", "source")
