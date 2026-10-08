"""Berechtigungsfundament: zentrale Abhängigkeiten, fail closed, RLS hinter der API."""
from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter, Depends

from ichq.api.security import authenticated, public, require
from ichq.app import create_app
from ichq.authz.registry import PERMISSIONS
from ichq.authz.service import Principal, decide, permissions_for_membership
from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.tenancy.service import set_status
from tests.api_helpers import make_client, principal_for
from tests.conftest import World


def test_registry_format_und_umfang() -> None:
    assert {"company.read", "users.read", "roles.assign", "invoices.approve"} <= PERMISSIONS
    assert not any("*" in p for p in PERMISSIONS)


def test_unbekanntes_recht_scheitert_beim_definieren() -> None:
    with pytest.raises(ValueError, match="Unbekannte Rechte"):
        require("finance.*")
    with pytest.raises(ValueError):
        require()
    with pytest.raises(ValueError):
        public("  ")


def test_routenpruefung_sieht_alle_echten_routen(settings: Settings, engines: Engines) -> None:
    """Gegenprobe: Der Check darf nicht leer durchlaufen (genau das war hier zuerst passiert)."""
    from ichq.api.security import assert_routes_secured, iter_api_routes
    app = create_app(settings, engines=engines)
    routen = [(p, tuple(sorted(m))) for p, m, _ in iter_api_routes(app)]
    pfade = {p for p, _ in routen}
    assert {"/health", "/readiness", "/api/v1/me", "/api/v1/company", "/api/v1/tasks/{ref}"} <= pfade
    assert len(set(routen)) == len(routen)          # (Pfad, Methode) eindeutig
    assert assert_routes_secured(app) == len(routen)


def test_router_weite_regel_wird_erkannt(settings: Settings, engines: Engines) -> None:
    r = APIRouter(prefix="/api/v1/intern", dependencies=[Depends(require("audit.read"))])

    @r.get("/a")
    def a() -> dict[str, str]:
        return {}
    create_app(settings, engines=engines, extra_routers=(r,))   # genau eine Regel über den Router: ok

    @r.get("/b")
    def b(_: Principal = Depends(authenticated())) -> dict[str, str]:
        return {}
    with pytest.raises(RuntimeError, match="/api/v1/intern/b"):
        create_app(settings, engines=engines, extra_routers=(r,))


def test_route_ohne_regel_verhindert_start(settings: Settings, engines: Engines) -> None:
    r = APIRouter()

    @r.get("/api/v1/vergessen")
    def vergessen() -> dict[str, str]:
        return {}
    with pytest.raises(RuntimeError, match="vergessen"):
        create_app(settings, engines=engines, extra_routers=(r,))


def test_route_mit_zwei_regeln_verhindert_start(settings: Settings, engines: Engines) -> None:
    r = APIRouter()

    @r.get("/api/v1/doppelt")
    def doppelt(_: Principal = Depends(authenticated()), __: None = Depends(public("x"))) -> dict[str, str]:
        return {}
    with pytest.raises(RuntimeError, match="doppelt"):
        create_app(settings, engines=engines, extra_routers=(r,))


def test_ohne_anmeldung_401_problem(settings: Settings, engines: Engines) -> None:
    client, _ = make_client(settings, engines)
    for pfad in ("/api/v1/me", "/api/v1/company"):
        r = client.get(pfad)
        assert r.status_code == 401, pfad
        assert r.headers["content-type"] == "application/problem+json"
        assert r.json()["code"] == "authentication_required"
        assert r.headers["www-authenticate"].startswith("Bearer")


def test_angemeldet_ohne_recht_403(world: World, settings: Settings, engines: Engines) -> None:
    p = principal_for(world, engines, "a")   # keine Rollen
    client, _ = make_client(settings, engines, principal=lambda: p)
    assert client.get("/api/v1/me").status_code == 200
    r = client.get("/api/v1/company")
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"


def test_recht_aus_rolle_gewaehrt_zugriff_nur_auf_eigene_firma(world: World, settings: Settings,
                                                               engines: Engines) -> None:
    world.assign(world.a.id, world.mem_a, world.role(world.a.id, "Lesen", ["company.read"]))
    world.assign(world.b.id, world.mem_b, world.role(world.b.id, "Lesen", ["company.read"]))
    for wer, slug in (("a", "alpha"), ("b", "beta")):
        p = principal_for(world, engines, wer)
        client, _ = make_client(settings, engines, principal=lambda p=p: p)
        r = client.get("/api/v1/company")
        assert r.status_code == 200 and r.json()["slug"] == slug


def test_gefaelschter_principal_sieht_keine_fremde_firma(world: World, settings: Settings,
                                                         engines: Engines) -> None:
    """Principal behauptet Firma B, Mitgliedschaft ist aus A: RLS liefert trotzdem nur B — nie A."""
    p = Principal(user_id=world.user_a, tenant_id=world.b.id, membership_id=world.mem_a,
                  permissions=frozenset({"company.read"}))
    client, _ = make_client(settings, engines, principal=lambda: p)
    assert client.get("/api/v1/company").json()["slug"] == "beta"


def test_archivierte_rolle_gibt_keine_rechte(world: World, engines: Engines) -> None:
    world.assign(world.a.id, world.mem_a, world.role(world.a.id, "Alt", ["audit.read"], archived=True))
    world.assign(world.a.id, world.mem_a, world.role(world.a.id, "Neu", ["company.read", "kein.recht"]))
    with tenant_transaction(engines.app, world.a.id) as s:
        assert permissions_for_membership(s, world.mem_a) == frozenset({"company.read"})


def test_rechte_laden_ist_mandantengetrennt(world: World, engines: Engines) -> None:
    world.assign(world.b.id, world.mem_b, world.role(world.b.id, "B", ["audit.read"]))
    with tenant_transaction(engines.app, world.a.id) as s:
        assert permissions_for_membership(s, world.mem_b) == frozenset()


def test_inaktive_firma_gesperrt(world: World, settings: Settings, engines: Engines) -> None:
    world.assign(world.a.id, world.mem_a, world.role(world.a.id, "Lesen", ["company.read"]))
    p = principal_for(world, engines, "a")
    with platform_transaction(engines.platform) as s:
        set_status(s, world.a.id, "suspended", actor="test", reason="Zahlung")
    client, _ = make_client(settings, engines, principal=lambda: p)
    r = client.get("/api/v1/company")
    assert r.status_code == 403 and "nicht aktiv" in r.json()["detail"]


def test_decide() -> None:
    p = Principal(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), frozenset({"company.read", "erfunden.recht"}))
    assert decide(p, "company.read") is True
    assert decide(p, "erfunden.recht") is False      # unbekannt → nein, auch wenn im Principal
    assert decide(None, "company.read") is False
