from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from ichq.api.security import get_principal, public
from ichq.app import create_app
from ichq.authz.service import Principal, permissions_for_membership
from ichq.core.config import Settings
from ichq.core.errors import Conflict
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from ichq.storage import Storage
from tests.conftest import World

test_router = APIRouter()


@test_router.get("/test/boom")
def boom(_: None = Depends(public("Test: interner Fehler"))) -> dict[str, str]:
    raise RuntimeError("geheimer-interner-text password=hunter2")


@test_router.get("/test/conflict")
def conflict(_: None = Depends(public("Test: Fachfehler"))) -> dict[str, str]:
    raise Conflict("Slug ist schon vergeben")


@test_router.post("/test/echo")
def echo(body: dict[str, int], _: None = Depends(public("Test: Validierung"))) -> dict[str, int]:
    return body


@test_router.get("/onboard/{token}")
def onboard(token: str, _: None = Depends(public("Test: Token im Pfad"))) -> dict[str, bool]:
    return {"ok": True}


def make_client(settings: Settings, engines: Engines, storage: Storage | None = None,
                principal: Callable[[], Principal | None] | None = None, mailer: object = None,
                base_url: str = "http://testserver") -> tuple[TestClient, FastAPI]:
    app = create_app(settings, engines=engines, storage=storage, mailer=mailer,  # type: ignore[arg-type]
                     extra_routers=(test_router,))
    if principal is not None:
        app.dependency_overrides[get_principal] = principal
    return TestClient(app, raise_server_exceptions=False, base_url=base_url), app


def principal_for(world: World, engines: Engines, which: str = "a") -> Principal:
    tid = world.a.id if which == "a" else world.b.id
    mid = world.mem_a if which == "a" else world.mem_b
    uid = world.user_a if which == "a" else world.user_b
    with tenant_transaction(engines.app, tid) as s:
        perms = permissions_for_membership(s, mid)
    return Principal(user_id=uid, tenant_id=tid, membership_id=mid, permissions=perms)
