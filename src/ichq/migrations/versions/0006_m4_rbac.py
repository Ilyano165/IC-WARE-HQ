"""M4 Rollen & Rechte (ADR-011).

Revision: 0006_m4_rbac
Vorgänger: 0005_core_followups

* ``roles``: ``public_id`` (API), ``grants_all`` (die gesperrte Systemrolle „Company Admin" — Rechte werden
  BERECHNET, nicht gespeichert). Höchstens eine solche Rolle je Firma; ein Trigger verhindert, dass sie
  umbenannt, archiviert, gelöscht oder eine andere Rolle nachträglich dazu gemacht wird — auch wenn der
  Anwendungscode es versuchte. ``priority`` ist der Rang (1–999, höher = mächtiger).
* Die M3-Übergangsrolle „Company Admin" (is_system, gespeicherte Rechteliste) wird zur gesperrten Rolle.
* ``permission_overrides``: Einzelrechte ALLOW/DENY je Mitgliedschaft.
* ``object_denies``: Ressourcen-DENY je Objekt und Mitgliedschaft — schlägt jede Sichtbarkeit.
* ``tenant_feature_flags``: Modul je Firma aus/an. Schreiben nur die Control Plane (``ichq_platform``),
  lesen die App-Rolle im eigenen Mandanten.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from ichq.migrations.datenpflege import ohne_force

revision = "0006_m4_rbac"
down_revision = "0005_core_followups"
branch_labels = None
depends_on = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")
PUBLIC_ID = r"public_id ~ '^[0-9a-f]{32}$'"
PERMISSION = r"permission ~ '^[a-z][a-z_]*(\.[a-z][a-z_]*)+$'"


def _mandant(tabelle: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="RESTRICT",
                                   name=f"fk_{tabelle}_tenant_id_tenants")


def _mitglied(tabelle: str, spalte: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id", spalte], ["memberships.tenant_id", "memberships.id"],
                                   ondelete=ondelete, name=f"fk_{tabelle}_tenant_id_{spalte}_memberships")


def _rls(tabelle: str) -> None:
    op.execute(f"""
    ALTER TABLE {tabelle} ENABLE ROW LEVEL SECURITY;
    ALTER TABLE {tabelle} FORCE ROW LEVEL SECURITY;
    CREATE POLICY p_{tabelle}_tenant ON {tabelle} TO ichq_app
      USING (tenant_id = ichq_current_tenant()) WITH CHECK (tenant_id = ichq_current_tenant());
    """)


def upgrade() -> None:
    # --- Rollen -------------------------------------------------------------------------
    op.add_column("roles", sa.Column("public_id", sa.String(32), nullable=False,
                                     server_default=sa.text("replace(gen_random_uuid()::text, '-', '')")))
    op.create_unique_constraint("uq_roles_public_id", "roles", ["public_id"])
    op.create_check_constraint("ck_roles_public_id_format", "roles", PUBLIC_ID)
    op.add_column("roles", sa.Column("grants_all", sa.Boolean, nullable=False, server_default=sa.false()))
    op.create_check_constraint("ck_roles_grants_all_is_system", "roles", "NOT grants_all OR is_system")
    op.create_index("uq_roles_one_grants_all", "roles", ["tenant_id"], unique=True,
                    postgresql_where=sa.text("grants_all"))
    with ohne_force("roles", "role_permissions"):   # ichq_owner hat keine Policy (datenpflege.py)
        op.execute("""UPDATE roles SET grants_all = true, priority = 100,
                      description = 'Gesperrt: hält immer alle Rechte der Registry'
                      WHERE is_system AND name = 'Company Admin'""")
        op.execute("DELETE FROM role_permissions rp USING roles r WHERE r.id = rp.role_id AND r.grants_all")
    op.execute("""
    CREATE FUNCTION ichq_role_locked() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP = 'DELETE' THEN
        IF OLD.grants_all THEN RAISE EXCEPTION 'gesperrte Rolle kann nicht gelöscht werden'; END IF;
        RETURN OLD;
      END IF;
      IF NEW.grants_all IS DISTINCT FROM OLD.grants_all OR NEW.is_system IS DISTINCT FROM OLD.is_system THEN
        RAISE EXCEPTION 'grants_all/is_system sind unveränderlich';
      END IF;
      IF OLD.grants_all AND (NEW.name IS DISTINCT FROM OLD.name OR NEW.archived_at IS NOT NULL
                             OR NEW.priority IS DISTINCT FROM OLD.priority) THEN
        RAISE EXCEPTION 'gesperrte Rolle kann nicht geändert werden';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER tr_roles_locked BEFORE UPDATE OR DELETE ON roles FOR EACH ROW EXECUTE FUNCTION ichq_role_locked();

    CREATE FUNCTION ichq_role_permissions_locked() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM roles WHERE id = NEW.role_id AND grants_all) THEN
        RAISE EXCEPTION 'gesperrte Rolle speichert keine Rechte (sie werden berechnet)';
      END IF;
      RETURN NEW;
    END $$;
    CREATE TRIGGER tr_role_permissions_locked BEFORE INSERT ON role_permissions
      FOR EACH ROW EXECUTE FUNCTION ichq_role_permissions_locked();
    """)

    # --- Einzelrechte -------------------------------------------------------------------
    t = "permission_overrides"
    op.create_table(
        t,
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column("permission", sa.String(64), nullable=False),
        sa.Column("effect", sa.String(8), nullable=False),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),   # wer: Mandanten-Audit
        sa.PrimaryKeyConstraint("membership_id", "permission", name=f"pk_{t}"),
        _mandant(t),
        _mitglied(t, "membership_id", "CASCADE"),
        sa.CheckConstraint("effect IN ('allow','deny')", name=f"ck_{t}_effect_valid"),
        sa.CheckConstraint(PERMISSION, name=f"ck_{t}_permission_format"),
    )
    op.create_index(f"ix_{t}_tenant_id", t, ["tenant_id"])

    # --- Ressourcen-DENY ----------------------------------------------------------------
    t = "object_denies"
    op.create_table(
        t,
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("object_id", UUID, nullable=False),
        sa.Column("membership_id", UUID, nullable=False),
        sa.Column("created_by_membership_id", UUID),
        sa.Column("created_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("object_id", "membership_id", name=f"pk_{t}"),
        _mandant(t),
        sa.ForeignKeyConstraint(["tenant_id", "object_id"], ["objects.tenant_id", "objects.id"], ondelete="CASCADE",
                                name=f"fk_{t}_tenant_id_object_id_objects"),
        _mitglied(t, "membership_id", "CASCADE"),
        _mitglied(t, "created_by_membership_id", "RESTRICT"),
    )
    op.create_index(f"ix_{t}_tenant_id", t, ["tenant_id"])
    op.create_index(f"ix_{t}_tenant_membership", t, ["tenant_id", "membership_id"])

    # --- Feature-Flags ------------------------------------------------------------------
    t = "tenant_feature_flags"
    op.create_table(
        t,
        sa.Column("tenant_id", UUID, nullable=False),
        sa.Column("module", sa.String(32), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False),
        sa.Column("updated_by", sa.String(120), nullable=False),
        sa.Column("updated_at", TS, server_default=NOW, nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "module", name=f"pk_{t}"),
        _mandant(t),
        sa.CheckConstraint("module ~ '^[a-z][a-z_]*$'", name=f"ck_{t}_module_format"),
    )
    op.create_index(f"ix_{t}_tenant_id", t, ["tenant_id"])

    op.execute("""
    REVOKE ALL ON permission_overrides, object_denies, tenant_feature_flags FROM PUBLIC;
    GRANT SELECT, INSERT, UPDATE, DELETE ON permission_overrides TO ichq_app;
    GRANT SELECT, INSERT, DELETE ON object_denies TO ichq_app;
    GRANT SELECT ON tenant_feature_flags TO ichq_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_feature_flags TO ichq_platform;
    """)
    for tab in ("permission_overrides", "object_denies", "tenant_feature_flags"):
        _rls(tab)
    # Control Plane: Flags aller Firmen (keine Mandantendaten im engeren Sinn — nur Modul an/aus)
    op.execute("""CREATE POLICY p_tenant_feature_flags_platform ON tenant_feature_flags TO ichq_platform
                  USING (true) WITH CHECK (true)""")


def downgrade() -> None:
    op.drop_table("tenant_feature_flags")
    op.drop_table("object_denies")
    op.drop_table("permission_overrides")
    op.execute("DROP TRIGGER tr_role_permissions_locked ON role_permissions")
    op.execute("DROP FUNCTION ichq_role_permissions_locked()")
    op.execute("DROP TRIGGER tr_roles_locked ON roles")
    op.execute("DROP FUNCTION ichq_role_locked()")
    # Gesperrte Rolle wird wieder zur Übergangsrolle mit gespeicherter Liste — die Liste ist beim Downgrade
    # leer; `ichq tenant-admin` des alten Stands füllt sie wieder auf.
    op.drop_index("uq_roles_one_grants_all", table_name="roles")
    op.drop_constraint("ck_roles_grants_all_is_system", "roles", type_="check")
    op.drop_column("roles", "grants_all")
    op.drop_constraint("ck_roles_public_id_format", "roles", type_="check")
    op.drop_constraint("uq_roles_public_id", "roles", type_="unique")
    op.drop_column("roles", "public_id")
