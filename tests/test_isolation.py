"""Mandantenisolation auf Datenbankebene — unabhängig vom Python-Code."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction
from tests.conftest import World, _admin

TABELLEN = ["memberships", "roles", "role_permissions", "membership_roles", "audit_events", "outbox_events"]


def _zaehlen(engines: Engines, tid: uuid.UUID, tabelle: str) -> int:
    with tenant_transaction(engines.app, tid) as s:
        return int(s.execute(text(f"SELECT count(*) FROM {tabelle}")).scalar() or 0)


def test_firma_sieht_nur_eigene_zeilen(world: World, engines: Engines) -> None:
    ra = world.role(world.a.id, "Team", ["dashboard.read"])
    world.assign(world.a.id, world.mem_a, ra)
    world.role(world.b.id, "Team", ["dashboard.read", "audit.read"])
    with tenant_transaction(engines.app, world.a.id) as s:
        assert s.execute(text("SELECT count(*) FROM tenants")).scalar() == 1
        assert s.execute(text("SELECT id FROM tenants")).scalar() == world.a.id
        assert s.execute(text("SELECT count(*) FROM memberships")).scalar() == 1
        assert s.execute(text("SELECT count(*) FROM roles")).scalar() == 1
        assert s.execute(text("SELECT count(*) FROM role_permissions")).scalar() == 1
        assert {r[0] for r in s.execute(text("SELECT email FROM users"))} == {"anna@alpha.test"}
        assert s.execute(text("SELECT count(*) FROM memberships WHERE tenant_id=:b"),
                         {"b": world.b.id}).scalar() == 0


def test_ohne_kontext_sieht_die_app_rolle_nichts(world: World, engines: Engines) -> None:
    with engines.app.connect() as c:   # Wächter umgangen — die Datenbank schützt trotzdem
        for t in [*TABELLEN, "tenants", "users"]:
            assert c.execute(text(f"SELECT count(*) FROM {t}")).scalar() == 0, t


def test_schreiben_in_fremde_firma_verboten(world: World, engines: Engines) -> None:
    with pytest.raises(ProgrammingError, match="row-level security"), \
            tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("INSERT INTO roles(id, tenant_id, name) VALUES (:i, :b, 'Eingeschleust')"),
                  {"i": uuid.uuid4(), "b": world.b.id})


def test_fremde_zeilen_nicht_aenderbar_oder_loeschbar(world: World, engines: Engines) -> None:
    rb = world.role(world.b.id, "Ziel", ["dashboard.read"])
    with tenant_transaction(engines.app, world.a.id) as s:
        assert s.execute(text("UPDATE roles SET name='gekapert' WHERE id=:r"), {"r": rb}).rowcount == 0
        assert s.execute(text("DELETE FROM roles WHERE id=:r"), {"r": rb}).rowcount == 0
    with tenant_transaction(engines.app, world.b.id) as s:
        assert s.execute(text("SELECT name FROM roles WHERE id=:r"), {"r": rb}).scalar() == "Ziel"


def test_zusammengesetzter_fremdschluessel_verhindert_kreuzverweis(world: World, engines: Engines) -> None:
    """Selbst als Datenbank-Admin (ohne RLS) kann eine Rolle von B nicht einem Mitglied von A gehören."""
    rb = world.role(world.b.id, "Fremd", ["dashboard.read"])
    with _admin(engines.app.url.database) as c, pytest.raises(Exception, match="foreign key"):
        c.execute("INSERT INTO membership_roles(tenant_id, membership_id, role_id) VALUES (%s,%s,%s)",
                  (world.a.id, world.mem_a, rb))


def test_audit_ist_nur_anhaengend(world: World, engines: Engines) -> None:
    from ichq.audit.service import record
    with tenant_transaction(engines.app, world.a.id) as s:
        record(s, "test.eintrag", data={"x": 1})
    with _admin(engines.app.url.database) as c:  # sogar Admin-Rechte reichen nicht ohne Trigger-Abschaltung
        with pytest.raises(Exception, match="nur anhängend"):
            c.execute("UPDATE audit_events SET action='gefaelscht'")
        with pytest.raises(Exception, match="nur anhängend"):
            c.execute("DELETE FROM audit_events")
        with pytest.raises(Exception, match="nur anhängend"):
            c.execute("TRUNCATE audit_events")


def test_audit_schwaerzt_daten(world: World, engines: Engines) -> None:
    from ichq.audit.service import record
    with tenant_transaction(engines.app, world.a.id) as s:
        record(s, "test.geheim", data={"password": "hunter2", "note": "Bearer abc.def.ghi"})
    with tenant_transaction(engines.app, world.a.id) as s:
        data = s.execute(text("SELECT data FROM audit_events WHERE action='test.geheim'")).scalar()
    assert data == {"password": "[REDACTED]", "note": "Bearer [REDACTED]"}


def test_mitgliedschaft_nur_fuer_existierendes_konto(world: World, engines: Engines) -> None:
    from ichq.core.errors import Conflict
    from ichq.identity.service import add_membership
    with pytest.raises(Conflict), tenant_transaction(engines.app, world.a.id) as s:
        add_membership(s, user_id=uuid.uuid4())


def test_mandantenkontext_muss_uuid_sein(engines: Engines) -> None:
    with pytest.raises(TypeError):
        with tenant_transaction(engines.app, "alpha"):  # type: ignore[arg-type]
            pass


def test_sql_injection_ueber_kontext_unmoeglich(engines: Engines) -> None:
    with pytest.raises((TypeError, DBAPIError, IntegrityError)):
        with tenant_transaction(engines.app, "x'; DROP TABLE tenants; --"):  # type: ignore[arg-type]
            pass
