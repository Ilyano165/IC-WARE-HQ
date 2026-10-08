"""Migrationen: hoch, runter, wieder hoch; Schema stimmt mit den Modellen überein; RLS überall."""
from __future__ import annotations

import secrets

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from ichq.audit import models as _a  # noqa: F401  — Modelle registrieren
from ichq.authz import models as _z  # noqa: F401
from ichq.cli import _alembic
from ichq.db.base import Base
from ichq.health.checks import expected_head
from ichq.identity import models as _i  # noqa: F401
from ichq.jobs import models as _j  # noqa: F401
from ichq.tenancy import models as _t  # noqa: F401
from tests.conftest import _admin, create_database, drop_database, url


@pytest.fixture
def frische_db(pg_roles: None):  # type: ignore[no-untyped-def]
    name = f"ichq_mig_{secrets.token_hex(4)}"
    create_database(name)
    yield name
    drop_database(name)


def _eng(name: str):  # type: ignore[no-untyped-def]
    return create_engine(url("ichq_owner", name).replace("postgresql://", "postgresql+psycopg://"))


def test_hoch_runter_hoch(frische_db: str) -> None:
    cfg = _alembic(url("ichq_owner", frische_db))
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    e = _eng(frische_db)
    with e.connect() as c:
        tabellen = c.execute(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' "
                                  "AND tablename <> 'alembic_version'")).scalar()
        funktionen = c.execute(text("SELECT count(*) FROM pg_proc WHERE proname LIKE 'ichq_%'")).scalar()
    assert tabellen == 0 and funktionen == 0
    command.upgrade(cfg, "head")
    with e.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == expected_head()
    e.dispose()


def test_modelle_und_migration_stimmen_ueberein(db_name: str) -> None:
    e = _eng(db_name)
    with e.connect() as c:
        diffs = compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata)
    e.dispose()
    assert diffs == [], f"Schema weicht von den Modellen ab: {diffs}"


def test_jede_mandantentabelle_hat_erzwungene_rls(db_name: str) -> None:
    mandanten = {t.name for t in Base.metadata.sorted_tables
                 if "tenant_id" in t.c and t.name != "platform_audit_events"}
    erwartet = {"memberships", "roles", "role_permissions", "membership_roles", "audit_events", "outbox_events"}
    assert erwartet <= mandanten
    with _admin(db_name) as c:
        rows = dict(c.execute("SELECT relname, relrowsecurity AND relforcerowsecurity FROM pg_class "
                              "WHERE relkind='r' AND relnamespace='public'::regnamespace").fetchall())
    ohne = [t for t in mandanten | {"tenants", "users"} if not rows.get(t)]
    assert ohne == [], f"Tabellen ohne erzwungene RLS: {ohne}"


def test_mandanten_fremdschluessel_sind_zusammengesetzt(db_name: str) -> None:
    with _admin(db_name) as c:
        fks = c.execute("""SELECT conrelid::regclass::text, array_length(conkey,1)
                           FROM pg_constraint WHERE contype='f'
                           AND confrelid::regclass::text IN ('memberships','roles')
                           AND conrelid::regclass::text IN ('role_permissions','membership_roles','audit_events')"""
                        ).fetchall()
    assert fks and all(n == 2 for _, n in fks), fks


def test_migration_verweigert_rolle_mit_bypassrls(frische_db: str) -> None:
    with _admin() as c:
        c.execute("ALTER ROLE ichq_worker BYPASSRLS")
    try:
        with pytest.raises(Exception, match="BYPASSRLS"):
            command.upgrade(_alembic(url("ichq_owner", frische_db)), "head")
    finally:
        with _admin() as c:
            c.execute("ALTER ROLE ichq_worker NOBYPASSRLS")


def test_app_rolle_kann_kein_schema_aendern(db_name: str) -> None:
    with psycopg.connect(url("ichq_app", db_name)) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("CREATE TABLE eingeschleust(id int)")


def test_m1_altdaten_nach_0002(frische_db: str) -> None:
    """M2-Restpunkt: M1-Bestand mit Konto 'active' ohne Passwort und 'disabled' → nach 0002 'pending' bzw.
    'deactivated'. Danach ganz zurück und wieder hoch."""
    cfg = _alembic(url("ichq_owner", frische_db))
    command.upgrade(cfg, "0001_foundation")
    with _admin(frische_db) as c:
        c.execute("INSERT INTO users(id, email, display_name, status) VALUES "
                  "('00000000-0000-7000-8000-000000000001', 'alt-aktiv@m1.test', 'Alt Aktiv', 'active'), "
                  "('00000000-0000-7000-8000-000000000002', 'alt-aus@m1.test', 'Alt Aus', 'disabled')")
    command.upgrade(cfg, "0002_authentication")
    with _admin(frische_db) as c:
        status = dict(c.execute("SELECT email, status FROM users ORDER BY email").fetchall())
    assert status == {"alt-aktiv@m1.test": "pending", "alt-aus@m1.test": "deactivated"}
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    e = _eng(frische_db)
    with e.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == expected_head()
    e.dispose()


def test_0005_nachtraege_mit_bestand(frische_db: str) -> None:
    """Daten-Pflege in Migrationen läuft trotz FORCE RLS: Historie und Löschgrund für vorhandene Kommentare."""
    cfg = _alembic(url("ichq_owner", frische_db))
    command.upgrade(cfg, "0004_m3_tenancy")
    with _admin(frische_db) as c:
        c.execute("""
          INSERT INTO tenants(id, slug, name, status) VALUES ('00000000-0000-7000-8000-0000000000a1', 'altfirma',
                 'Alt GmbH', 'active');
          INSERT INTO users(id, email, display_name) VALUES ('00000000-0000-7000-8000-0000000000b1', 'k@alt.test', 'K');
          INSERT INTO memberships(id, tenant_id, user_id) VALUES ('00000000-0000-7000-8000-0000000000c1',
                 '00000000-0000-7000-8000-0000000000a1', '00000000-0000-7000-8000-0000000000b1');
          INSERT INTO objects(id, tenant_id, type, public_id, title) VALUES ('00000000-0000-7000-8000-0000000000d1',
                 '00000000-0000-7000-8000-0000000000a1', 'task', repeat('d', 32), 'Alt');
          INSERT INTO comments(id, tenant_id, public_id, object_id, author_membership_id, body, deleted_at) VALUES
            ('00000000-0000-7000-8000-0000000000e1', '00000000-0000-7000-8000-0000000000a1', repeat('e', 32),
             '00000000-0000-7000-8000-0000000000d1', '00000000-0000-7000-8000-0000000000c1', 'Bestandstext', NULL),
            ('00000000-0000-7000-8000-0000000000e2', '00000000-0000-7000-8000-0000000000a1', repeat('f', 32),
             '00000000-0000-7000-8000-0000000000d1', '00000000-0000-7000-8000-0000000000c1', '', now());
          INSERT INTO object_grants(tenant_id, object_id, membership_id) VALUES
            ('00000000-0000-7000-8000-0000000000a1', '00000000-0000-7000-8000-0000000000d1',
             '00000000-0000-7000-8000-0000000000c1');""")
    command.upgrade(cfg, "head")
    with _admin(frische_db) as c:
        revs = c.execute("SELECT comment_id::text, kind, body FROM comment_revisions ORDER BY comment_id").fetchall()
        gruende = c.execute("SELECT delete_reason FROM comments WHERE deleted_at IS NOT NULL").fetchall()
        quellen = c.execute("SELECT source FROM object_grants").fetchall()
        force = c.execute("SELECT relforcerowsecurity FROM pg_class WHERE relname IN "
                          "('comments','comment_revisions','users','object_grants')").fetchall()
    assert revs == [("00000000-0000-7000-8000-0000000000e1", "created", "Bestandstext"),
                    ("00000000-0000-7000-8000-0000000000e2", "created", "")]
    assert gruende == [("vor Migration 0005 gelöscht (Grund nicht erfasst)",)]
    assert quellen == [("manual",)]
    assert force and all(f for (f,) in force)            # FORCE ist nach der Daten-Pflege wieder an
    command.downgrade(cfg, "0004_m3_tenancy")
    with _admin(frische_db) as c:
        assert c.execute("SELECT count(*) FROM object_grants").fetchone() == (1,)
