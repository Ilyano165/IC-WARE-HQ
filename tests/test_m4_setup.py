"""M4 — Migration mit Bestand (M3-Übergangsrolle), Vorlagen, Control-Plane-Befehle."""
from __future__ import annotations

import subprocess
import sys

from alembic import command
from sqlalchemy import text

from ichq.authz.registry import PERMISSIONS
from ichq.authz.service import permissions_for_membership
from ichq.authz.templates import TEMPLATES, install
from ichq.cli import _alembic
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.identity.service import add_membership, create_user
from ichq.tenancy.service import create_tenant
from tests.auth_helpers import db
from tests.conftest import World, _admin, url
from tests.test_migrations import frische_db  # noqa: F401  (Fixture)

T, U, M, R = ("00000000-0000-7000-8000-0000000000a1", "00000000-0000-7000-8000-0000000000b1",
              "00000000-0000-7000-8000-0000000000c1", "00000000-0000-7000-8000-0000000000f1")


def test_0006_macht_aus_der_uebergangsrolle_die_gesperrte(frische_db: str) -> None:  # noqa: F811
    cfg = _alembic(url("ichq_owner", frische_db))
    command.upgrade(cfg, "0005_core_followups")
    with _admin(frische_db) as c:
        c.execute(f"""
          INSERT INTO tenants(id, slug, name, status) VALUES ('{T}', 'altfirma', 'Alt GmbH', 'active');
          INSERT INTO users(id, email, display_name) VALUES ('{U}', 'k@alt.test', 'K');
          INSERT INTO memberships(id, tenant_id, user_id) VALUES ('{M}', '{T}', '{U}');
          INSERT INTO roles(id, tenant_id, name, priority, is_system) VALUES ('{R}', '{T}', 'Company Admin', 1, true),
                 ('00000000-0000-7000-8000-0000000000f2', '{T}', 'Eigene', 10, false);
          INSERT INTO role_permissions(tenant_id, role_id, permission) VALUES ('{T}', '{R}', 'tasks.read'),
                 ('{T}', '{R}', 'roles.update'), ('{T}', '00000000-0000-7000-8000-0000000000f2', 'tasks.read');
          INSERT INTO membership_roles(tenant_id, membership_id, role_id) VALUES ('{T}', '{M}', '{R}');""")
    command.upgrade(cfg, "head")
    with _admin(frische_db) as c:
        rollen = c.execute("SELECT name, grants_all, priority, length(public_id) FROM roles ORDER BY name").fetchall()
        gespeichert = c.execute("SELECT role_id::text, permission FROM role_permissions").fetchall()
        force = c.execute("SELECT bool_and(relforcerowsecurity) FROM pg_class WHERE relname IN "
                          "('roles','role_permissions','permission_overrides','object_denies',"
                          "'tenant_feature_flags')").fetchone()
    assert rollen == [("Company Admin", True, 100, 32), ("Eigene", False, 10, 32)]
    assert gespeichert == [("00000000-0000-7000-8000-0000000000f2", "tasks.read")]   # CA: nichts gespeichert
    assert force == (True,)
    command.downgrade(cfg, "0005_core_followups")
    command.upgrade(cfg, "head")


def test_vorlagen_idempotent_und_unveraendert(world: World, engines: Engines) -> None:
    with tenant_transaction(engines.app, world.a.id) as s:
        assert install(s) == [t.name for t in TEMPLATES]
        s.execute(text("UPDATE roles SET description = 'angepasst' WHERE name = 'Mitarbeiter'"))
        assert install(s) == []
    assert db(engines, "SELECT description FROM roles WHERE name = 'Mitarbeiter'") == [("angepasst",)]
    assert db(engines, "SELECT name, priority FROM roles WHERE tenant_id = %s ORDER BY priority DESC",
              (world.a.id,)) == [("Company Admin", 100), ("Geschäftsführung", 90), ("Mitarbeiter", 40),
                                 ("Steuerberater", 30)]
    assert db(engines, "SELECT count(*) FROM roles WHERE tenant_id = %s", (world.b.id,))[0][0] == 0
    stb = {r[0] for r in db(engines, "SELECT rp.permission FROM role_permissions rp JOIN roles r ON r.id = "
                                     "rp.role_id WHERE r.name = 'Steuerberater'")}
    assert "objects.read_all" not in stb and "users.read" not in stb and "finance.export" in stb


def _cli(settings: Settings, *args: str) -> subprocess.CompletedProcess[str]:
    from tests.test_entrypoints import _umgebung
    return subprocess.run([sys.executable, "-m", "ichq.cli", *args], env=_umgebung(settings), capture_output=True,
                          text=True, timeout=60)


def test_cli_aktivieren_admin_und_feature(engines: Engines, settings: Settings) -> None:
    with platform_transaction(engines.platform) as s:
        t = create_tenant(s, name="Gamma KG", slug="gamma", actor="test")
        uid = create_user(s, email="gina@gamma.test", display_name="Gina")
    r = _cli(settings, "tenant-status", str(t.id), "active", "--reason", "Onboarding")
    assert r.returncode == 0 and "Rollenvorlagen angelegt: Company Admin, Geschäftsführung" in r.stdout, r.stderr
    with tenant_transaction(engines.app, t.id) as s:
        mid = add_membership(s, user_id=uid)
    r = _cli(settings, "tenant-admin", "--email", "gina@gamma.test", "--tenant", "gamma")
    assert r.returncode == 0 and "Company Admin → gina@gamma.test @ gamma" in r.stdout, r.stderr
    assert "war schon" in _cli(settings, "tenant-admin", "--email", "gina@gamma.test", "--tenant", "gamma").stdout
    with tenant_transaction(engines.app, t.id) as s:
        assert permissions_for_membership(s, mid) == PERMISSIONS
    r = _cli(settings, "tenant-feature", "--tenant", "gamma", "tasks", "off", "--reason", "Plan ohne Aufgaben")
    assert r.returncode == 0, r.stderr
    with tenant_transaction(engines.app, t.id) as s:
        assert "tasks.read" not in permissions_for_membership(s, mid)
    r = _cli(settings, "tenant-feature", "--tenant", "gamma", "roles", "off", "--reason", "x")
    assert r.returncode == 1 and "Kernmodul" in r.stderr
    assert db(engines, "SELECT data->>'module', data->>'enabled' FROM platform_audit_events "
                       "WHERE action = 'tenant.feature_flag_set'") == [("tasks", "false")]
