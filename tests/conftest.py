"""Gemeinsame Testumgebung.

Braucht einen PostgreSQL-Server und eine Admin-Verbindung in ``ICHQ_TEST_ADMIN_URL``.
Die Tests legen die vier Rollen (mit Testpasswörtern) und eine frische Datenbank an,
spielen die echten Migrationen ein und arbeiten danach ausschließlich mit den
eingeschränkten Rollen — nie als Superuser. Sonst würde Row-Level Security umgangen
und die Isolationstests bewiesen nichts.

ACHTUNG: Setzt die Passwörter der ichq_*-Rollen auf Testwerte. Nur gegen einen
eigenen Test-Server laufen lassen.
"""
from __future__ import annotations

import os
import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from sqlalchemy import text

from ichq.cli import _alembic
from ichq.core.config import Settings, load_settings
from ichq.db.engine import Engines, build_engines, make_engine
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.identity.service import add_membership, create_user
from ichq.tenancy.service import create_tenant, set_status

ADMIN_URL = os.environ.get("ICHQ_TEST_ADMIN_URL", "")
PW = {"ichq_owner": "t-owner-" + "x" * 24, "ichq_app": "t-app-" + "x" * 26,
      "ichq_platform": "t-platform-" + "x" * 21, "ichq_worker": "t-worker-" + "x" * 23,
      "ichq_auth": "t-auth-" + "x" * 25}
HOST = os.environ.get("ICHQ_TEST_HOST", "localhost:5432")


def _admin(dbname: str = "postgres") -> psycopg.Connection:
    base = ADMIN_URL.rsplit("/", 1)[0]
    return psycopg.connect(f"{base}/{dbname}", autocommit=True)


def url(role: str, db: str) -> str:
    return f"postgresql://{role}:{PW[role]}@{HOST}/{db}"


def create_database(name: str) -> None:
    with _admin() as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        c.execute(f'CREATE DATABASE "{name}" OWNER ichq_owner')
    with _admin(name) as c:
        c.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
        c.execute("GRANT CREATE, USAGE ON SCHEMA public TO ichq_owner")


def drop_database(name: str) -> None:
    with _admin() as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def pg_roles() -> None:
    if not ADMIN_URL:
        pytest.fail("ICHQ_TEST_ADMIN_URL fehlt — die Tests brauchen einen echten PostgreSQL-Server.")
    with _admin() as c:
        for role, pw in PW.items():
            exists = c.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            c.execute(f"{verb} ROLE {role} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB "
                      f"PASSWORD '{pw}'")


@pytest.fixture(scope="session")
def db_name(pg_roles: None) -> Iterator[str]:
    name = f"ichq_test_{secrets.token_hex(4)}"
    create_database(name)
    command.upgrade(_alembic(url("ichq_owner", name)), "head")
    yield name
    drop_database(name)


def make_settings(db: str, storage: Path, **extra: str) -> Settings:
    env = {
        "ICHQ_ENV": "test",
        "ICHQ_DATABASE_URL": url("ichq_app", db),
        "ICHQ_PLATFORM_DATABASE_URL": url("ichq_platform", db),
        "ICHQ_WORKER_DATABASE_URL": url("ichq_worker", db),
        "ICHQ_MIGRATION_DATABASE_URL": url("ichq_owner", db),
        "ICHQ_AUTH_DATABASE_URL": url("ichq_auth", db),
        # Argon2 bewusst leicht, damit die Suite schnell bleibt — Produktion verlangt >= 64 MiB
        "ICHQ_ARGON2_MEMORY_KIB": "8192", "ICHQ_ARGON2_TIME_COST": "1", "ICHQ_ARGON2_PARALLELISM": "1",
        "ICHQ_SECRET_KEY": "s" * 40,
        "ICHQ_SESSION_SECRET": "z" * 40,
        "ICHQ_STORAGE_BACKEND": "local",
        "ICHQ_STORAGE_PATH": str(storage),
        "ICHQ_LOG_FORMAT": "json",
    }
    env.update(extra)
    return load_settings(env)


@pytest.fixture(scope="session")
def settings(db_name: str, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    return make_settings(db_name, tmp_path_factory.mktemp("storage"))


@pytest.fixture(scope="session")
def engines(settings: Settings) -> Iterator[Engines]:
    e = build_engines(settings)
    yield e
    e.dispose()


@pytest.fixture(autouse=True)
def _clean(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if "db_name" not in request.fixturenames:
        return
    name = request.getfixturevalue("db_name")
    with _admin(name) as c:
        # replica-Modus schaltet die Nur-anhängen-Trigger nur für diese Bereinigung ab
        c.execute("SET session_replication_role = replica")
        c.execute("TRUNCATE mail_outbox, outbox_events, audit_events, platform_audit_events, membership_roles, "
                  "role_permissions, roles, memberships, auth_sessions, password_reset_tokens, recovery_codes, "
                  "login_attempts, auth_events, users, tenants CASCADE")


class World:
    """Zwei aktive Firmen mit je einem Mitglied — Grundlage aller Isolationstests."""

    def __init__(self, engines: Engines) -> None:
        self.engines = engines
        with platform_transaction(engines.platform) as s:
            self.a = create_tenant(s, name="Alpha GmbH", slug="alpha", actor="test")
            self.b = create_tenant(s, name="Beta AG", slug="beta", actor="test")
            set_status(s, self.a.id, "active", actor="test", reason="test")
            set_status(s, self.b.id, "active", actor="test", reason="test")
            self.user_a = create_user(s, email="anna@alpha.test", display_name="Anna")
            self.user_b = create_user(s, email="bert@beta.test", display_name="Bert")
        with tenant_transaction(engines.app, self.a.id) as s:
            self.mem_a = add_membership(s, user_id=self.user_a)
        with tenant_transaction(engines.app, self.b.id) as s:
            self.mem_b = add_membership(s, user_id=self.user_b)

    def role(self, tenant_id: uuid.UUID, name: str, perms: list[str], archived: bool = False) -> uuid.UUID:
        with tenant_transaction(self.engines.app, tenant_id) as s:
            rid = uuid.uuid4()
            s.execute(text("INSERT INTO roles(id, tenant_id, name, archived_at) "
                           "VALUES (:id, :t, :n, CASE WHEN :a THEN now() END)"),
                      {"id": rid, "t": tenant_id, "n": name, "a": archived})
            for p in perms:
                s.execute(text("INSERT INTO role_permissions(tenant_id, role_id, permission) VALUES (:t,:r,:p)"),
                          {"t": tenant_id, "r": rid, "p": p})
        return rid

    def assign(self, tenant_id: uuid.UUID, membership_id: uuid.UUID, role_id: uuid.UUID) -> None:
        with tenant_transaction(self.engines.app, tenant_id) as s:
            s.execute(text("INSERT INTO membership_roles(tenant_id, membership_id, role_id) VALUES (:t,:m,:r)"),
                      {"t": tenant_id, "m": membership_id, "r": role_id})


@pytest.fixture
def world(engines: Engines) -> World:
    return World(engines)


@pytest.fixture
def rw(world: World, engines: Engines, settings: Settings) -> Any:
    """M4-Testwelt (Rollenvorlagen, Company Admin je Firma) — tests/m4_helpers.py."""
    from tests.m4_helpers import RbacWorld
    return RbacWorld(world, engines, settings)


@pytest.fixture
def single_conn_app_engine(settings: Settings) -> Iterator[object]:
    """App-Engine mit genau einer Verbindung — beweist, dass nichts über den Pool hinweg haftet."""
    e = make_engine(settings.database_url.get_secret_value(), "app-single", pool_size=1)
    e.pool._max_overflow = 0  # type: ignore[attr-defined]
    yield e
    e.dispose()
