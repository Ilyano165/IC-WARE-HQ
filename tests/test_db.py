"""Datenbankverbindung, Rollen, Transaktionen, Mandantenwächter."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, select, text

from ichq.core.errors import TenantContextMissing
from ichq.db.engine import Engines
from ichq.db.session import platform_transaction, tenant_transaction
from ichq.identity.models import Membership
from tests.conftest import World


def test_jede_engine_nutzt_eigene_eingeschraenkte_rolle(engines: Engines) -> None:
    for engine, rolle in ((engines.app, "ichq_app"), (engines.platform, "ichq_platform"),
                          (engines.worker, "ichq_worker")):
        with engine.connect() as c:
            row = c.execute(text("SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r "
                                 "WHERE r.rolname = current_user")).one()
        assert tuple(row) == (rolle, False, False)


def test_statement_timeout_gesetzt(engines: Engines) -> None:
    with engines.app.connect() as c:
        assert c.execute(text("SHOW statement_timeout")).scalar() == "15s"


def test_wachter_ohne_mandantenkontext(engines: Engines) -> None:
    from ichq.db.session import TenantSession
    with TenantSession(engines.app) as s, pytest.raises(TenantContextMissing):
        s.execute(select(Membership))


def test_rollback_bei_fehler(world: World, engines: Engines) -> None:
    with pytest.raises(RuntimeError), tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("INSERT INTO roles(id, tenant_id, name) VALUES (:i, :t, 'Weg')"),
                  {"i": uuid.uuid4(), "t": world.a.id})
        raise RuntimeError("Abbruch")
    with tenant_transaction(engines.app, world.a.id) as s:
        assert s.execute(text("SELECT count(*) FROM roles WHERE name='Weg'")).scalar() == 0


def test_mandant_haftet_nicht_an_gepoolter_verbindung(world: World, single_conn_app_engine: Engine) -> None:
    eng = single_conn_app_engine
    with tenant_transaction(eng, world.a.id) as s:
        assert s.execute(text("SELECT count(*) FROM memberships")).scalar() == 1
        pid = s.execute(text("SELECT pg_backend_pid()")).scalar()
    with eng.connect() as c:   # gleiche physische Verbindung, ohne Kontext
        assert c.execute(text("SELECT pg_backend_pid()")).scalar() == pid
        assert c.execute(text("SELECT current_setting('app.tenant_id', true)")).scalar() in (None, "")
        assert c.execute(text("SELECT count(*) FROM memberships")).scalar() == 0


def test_plattform_rolle_hat_keinen_zugriff_auf_mandantendaten(world: World, engines: Engines) -> None:
    from sqlalchemy.exc import ProgrammingError
    with pytest.raises(ProgrammingError, match="permission denied"), platform_transaction(engines.platform) as s:
        s.execute(text("SELECT count(*) FROM memberships"))
