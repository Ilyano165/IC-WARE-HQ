"""Testwelt für die Core-Plattform (C0): zwei Firmen, mehrere Rollen, echte Rechte aus Rollen."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from ichq.authz.registry import PERMISSIONS
from ichq.authz.service import Principal, permissions_for_membership
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.identity.service import add_membership, create_user
from ichq.objects.service import create_object
from tests.api_helpers import make_client
from tests.conftest import World

ALLES = sorted(PERMISSIONS)
MITARBEITER = ["tasks.read", "tasks.create", "tasks.update", "comments.read", "comments.create", "files.read",
               "files.upload", "files.update", "finance.read", "activity.read", "users.read", "objects.read_all",
               "invoices.read", "customers.read", "projects.read"]
# Steuerberater: liest Belege/Dokumente/Aufgaben und kommentiert — sieht aber nur Freigegebenes (kein read_all)
STEUERBERATER = ["tasks.read", "comments.read", "comments.create", "files.read", "finance.read", "activity.read",
                 "invoices.read"]
LESER = ["tasks.read", "comments.read", "files.read", "activity.read", "objects.read_all"]


class CoreWorld:
    def __init__(self, world: World, engines: Engines, settings: Settings) -> None:
        self.w, self.engines, self.settings = world, engines, settings
        self.a, self.b = world.a.id, world.b.id
        self.admin_a = self._mitglied(self.a, "chef@alpha.test", "Chefin Alpha", ALLES, mid=world.mem_a)
        self.mitarbeiter = self._mitglied(self.a, "ma@alpha.test", "Max Mitarbeiter", MITARBEITER)
        self.stb = self._mitglied(self.a, "stb@kanzlei.test", "Sabine Steuerberaterin", STEUERBERATER)
        self.leser = self._mitglied(self.a, "leser@alpha.test", "Lena Leserin", LESER)
        self.ohne = self._mitglied(self.a, "ohne@alpha.test", "Otto Ohnerecht", [])
        self.admin_b = self._mitglied(self.b, "chef@beta.test", "Chef Beta", ALLES, mid=world.mem_b)
        self.mitarbeiter_b = self._mitglied(self.b, "ma@beta.test", "Mia Beta", MITARBEITER)

    def _mitglied(self, tid: uuid.UUID, email: str, name: str, perms: list[str],
                  mid: uuid.UUID | None = None) -> uuid.UUID:
        if mid is None:
            with platform_transaction(self.engines.platform) as s:
                uid = create_user(s, email=email, display_name=name)
            with tenant_transaction(self.engines.app, tid) as s:
                mid = add_membership(s, user_id=uid)
        if perms:
            self.w.assign(tid, mid, self.w.role(tid, f"Rolle {name}", perms))
        return mid

    def tenant_of(self, mid: uuid.UUID) -> uuid.UUID:
        return self.b if mid in (self.admin_b, getattr(self, "mitarbeiter_b", None)) else self.a

    def principal(self, mid: uuid.UUID) -> Principal:
        tid = self.tenant_of(mid)
        with tenant_transaction(self.engines.app, tid) as s:
            uid = s.execute(text("SELECT user_id FROM memberships WHERE id = :m"), {"m": mid}).scalar_one()
            perms = permissions_for_membership(s, mid)
        return Principal(user_id=uid, tenant_id=tid, membership_id=mid, permissions=perms)

    def client(self, mid: uuid.UUID) -> TestClient:
        p = self.principal(mid)
        c, _ = make_client(self.settings, self.engines, principal=lambda: p)
        return c

    def public_id(self, mid: uuid.UUID) -> str:
        tid = self.tenant_of(mid)
        with tenant_transaction(self.engines.app, tid) as s:
            return str(s.execute(text("SELECT public_id FROM memberships WHERE id = :m"), {"m": mid}).scalar_one())

    def raw_object(self, tid: uuid.UUID, type_: str, title: str, by: uuid.UUID | None = None,
                   search_text: str | None = None) -> str:
        """Objekt eines reservierten Typs (Fachmodul folgt) direkt über den Service anlegen."""
        with tenant_transaction(self.engines.app, tid) as s:
            return create_object(s, type_=type_, title=title, actor_membership_id=by, search_text=search_text).public_id


def ok(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, f"{r.status_code}: {r.text}"
    return r.json() if r.content and r.headers.get("content-type", "").startswith("application/json") else r


def run_worker(engines: Engines) -> Any:
    from ichq.jobs.worker import run_once
    from ichq.notifications import handlers
    handlers.assert_handlers()
    return run_once(engines, limit=100)
