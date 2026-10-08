"""Testwelt für M4: Firma A mit Rollenvorlagen, Firma B getrennt. Rechte werden je Anfrage NEU berechnet
(Client mit dynamischem Principal) — so wie ``get_principal`` es im Betrieb tut."""
from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from ichq.authz.service import Principal, principal_for
from ichq.authz.templates import install, make_company_admin
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.identity.service import add_membership, create_user
from tests.api_helpers import make_client
from tests.conftest import World


class RbacWorld:
    def __init__(self, world: World, engines: Engines, settings: Settings) -> None:
        self.w, self.engines, self.settings = world, engines, settings
        self.a, self.b = world.a.id, world.b.id
        self._tenant: dict[uuid.UUID, uuid.UUID] = {world.mem_a: self.a, world.mem_b: self.b}
        for tid, mid in ((self.a, world.mem_a), (self.b, world.mem_b)):
            with tenant_transaction(engines.app, tid) as s:
                install(s)
                make_company_admin(s, mid)
        self.admin, self.admin_b = world.mem_a, world.mem_b
        self.gf = self.mitglied("gf@alpha.test", "Geschäftsführung")
        self.ma = self.mitglied("ma@alpha.test", "Mitarbeiter")
        self.ohne = self.mitglied("ohne@alpha.test")

    def mitglied(self, email: str, *rollen: str, tid: uuid.UUID | None = None) -> uuid.UUID:
        tid = tid or self.a
        with platform_transaction(self.engines.platform) as s:
            uid = create_user(s, email=email, display_name=email.split("@")[0])
        with tenant_transaction(self.engines.app, tid) as s:
            mid = add_membership(s, user_id=uid)
        self._tenant[mid] = tid
        for r in rollen:
            self.gib(mid, r)
        return mid

    def rolle(self, name: str, rank: int, perms: list[str] | set[str], tid: uuid.UUID | None = None) -> str:
        """Rolle direkt anlegen (Testaufbau, ohne Delegationsprüfung)."""
        tid = tid or self.a
        with tenant_transaction(self.engines.app, tid) as s:
            rid = uuid.uuid4()
            s.execute(text("INSERT INTO roles(id, tenant_id, name, priority) VALUES (:i, :t, :n, :p)"),
                      {"i": rid, "t": tid, "n": name, "p": rank})
            for p in sorted(perms):
                s.execute(text("INSERT INTO role_permissions(tenant_id, role_id, permission) VALUES (:t, :r, :p)"),
                          {"t": tid, "r": rid, "p": p})
            return str(s.execute(text("SELECT public_id FROM roles WHERE id = :i"), {"i": rid}).scalar_one())

    def gib(self, mid: uuid.UUID, rollenname: str) -> None:
        tid = self._tenant[mid]
        with tenant_transaction(self.engines.app, tid) as s:
            s.execute(text("INSERT INTO membership_roles(tenant_id, membership_id, role_id) "
                           "SELECT :t, :m, id FROM roles WHERE name = :n"), {"t": tid, "m": mid, "n": rollenname})

    def role_id(self, name: str, tid: uuid.UUID | None = None) -> str:
        with tenant_transaction(self.engines.app, tid or self.a) as s:
            return str(s.execute(text("SELECT public_id FROM roles WHERE name = :n"), {"n": name}).scalar_one())

    def principal(self, mid: uuid.UUID) -> Principal:
        tid = self._tenant[mid]
        with tenant_transaction(self.engines.app, tid) as s:
            uid = s.execute(text("SELECT user_id FROM memberships WHERE id = :m"), {"m": mid}).scalar_one()
            return principal_for(s, user_id=uid, tenant_id=tid, membership_id=mid)

    def client(self, mid: uuid.UUID) -> TestClient:
        c, _ = make_client(self.settings, self.engines, principal=lambda: self.principal(mid))
        return c

    def pid(self, mid: uuid.UUID) -> str:
        with tenant_transaction(self.engines.app, self._tenant[mid]) as s:
            return str(s.execute(text("SELECT public_id FROM memberships WHERE id = :m"), {"m": mid}).scalar_one())

    def rechte(self, mid: uuid.UUID) -> frozenset[str]:
        return self.principal(mid).permissions

    def audit(self, action: str) -> list[Any]:
        with tenant_transaction(self.engines.app, self.a) as s:
            return list(s.execute(text("SELECT target_id, data FROM audit_events WHERE action = :a ORDER BY id"),
                                  {"a": action}).all())
