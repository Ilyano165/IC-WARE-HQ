"""Firmen anlegen, nachschlagen, Status."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from ichq.core.errors import Conflict, NotFound, ValidationFailed
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.tenancy.service import create_tenant, current_tenant, get_tenant, get_tenant_by_slug, set_status
from tests.conftest import World


def test_firma_anlegen(engines: Engines) -> None:
    with platform_transaction(engines.platform) as s:
        t = create_tenant(s, name="  Kreativ Studio  ", slug="Kreativ-Studio", actor="test",
                          legal_name="Kreativ Studio GbR")
    assert t.slug == "kreativ-studio" and t.name == "Kreativ Studio" and t.status == "pending"
    assert t.id.version == 7 and t.currency == "EUR" and t.timezone == "Europe/Berlin"
    with platform_transaction(engines.platform) as s:
        audit = s.execute(text("SELECT action, actor, tenant_id FROM platform_audit_events")).one()
    assert tuple(audit) == ("tenant.created", "test", t.id)


@pytest.mark.parametrize("slug", ["ab", "-alpha", "alpha-", "Alpha GmbH", "a_b_c", "admin", "api", "x" * 49])
def test_ungueltige_slugs(engines: Engines, slug: str) -> None:
    with pytest.raises(ValidationFailed), platform_transaction(engines.platform) as s:
        create_tenant(s, name="X", slug=slug, actor="test")


@pytest.mark.parametrize("feld", [{"timezone": "Mars/Base"}, {"language": "fr"}, {"currency": "eur"},
                                  {"name": "   "}])
def test_ungueltige_felder(engines: Engines, feld: dict[str, str]) -> None:
    kw = {"name": "X", "slug": "gueltig", "actor": "test", **feld}
    with pytest.raises(ValidationFailed), platform_transaction(engines.platform) as s:
        create_tenant(s, **kw)  # type: ignore[arg-type]


def test_slug_eindeutig(engines: Engines) -> None:
    with platform_transaction(engines.platform) as s:
        create_tenant(s, name="Eins", slug="doppelt", actor="test")
    with pytest.raises(Conflict), platform_transaction(engines.platform) as s:
        create_tenant(s, name="Zwei", slug="DOPPELT", actor="test")


def test_datenbank_constraint_greift_auch_ohne_service(engines: Engines) -> None:
    with pytest.raises(Exception, match="ck_tenants_slug_format"), platform_transaction(engines.platform) as s:
        s.execute(text("INSERT INTO tenants(id, slug, name) VALUES (gen_random_uuid(), '-x-', 'Y')"))


def test_nachschlagen(world: World, engines: Engines) -> None:
    with platform_transaction(engines.platform) as s:
        assert get_tenant(s, world.a.id).slug == "alpha"
        assert get_tenant_by_slug(s, " BETA ").id == world.b.id
        with pytest.raises(NotFound):
            get_tenant(s, uuid.uuid4())
        with pytest.raises(NotFound):
            get_tenant_by_slug(s, "gibtsnicht")


def test_aktuelle_firma_ueber_rls(world: World, engines: Engines) -> None:
    with tenant_transaction(engines.app, world.b.id) as s:
        assert current_tenant(s).slug == "beta"


def test_statusuebergaenge(world: World, engines: Engines) -> None:
    with platform_transaction(engines.platform) as s:
        assert set_status(s, world.a.id, "paused", actor="test", reason="Saison").status == "paused"
        with pytest.raises(Conflict):
            set_status(s, world.a.id, "pending", actor="test", reason="zurück")
        with pytest.raises(ValidationFailed):
            set_status(s, world.a.id, "active", actor="test", reason="  ")
    with platform_transaction(engines.platform) as s:
        set_status(s, world.a.id, "deactivated", actor="test", reason="Kündigung")
    with pytest.raises(Conflict), platform_transaction(engines.platform) as s:
        set_status(s, world.a.id, "active", actor="test", reason="doch nicht")
    with platform_transaction(engines.platform) as s:
        n = s.execute(text("SELECT count(*) FROM platform_audit_events WHERE action='tenant.status_changed' "
                           "AND tenant_id=:t"), {"t": world.a.id}).scalar()
    assert n == 3   # active (Aufbau), paused, deactivated


def test_app_rolle_kann_keine_firma_anlegen(engines: Engines, world: World) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"), \
            tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("INSERT INTO tenants(id, slug, name) VALUES (gen_random_uuid(), 'neu', 'Neu')"))
