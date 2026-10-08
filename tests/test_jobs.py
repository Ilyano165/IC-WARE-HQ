"""Outbox und Worker: Ereignis nur bei Commit, Ausführung im richtigen Mandanten, Wiederholung."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction, worker_transaction
from ichq.jobs import worker
from ichq.jobs.service import emit_event
from tests.conftest import World


def _status(engines: Engines) -> list[tuple[str, str, int]]:
    with worker_transaction(engines.worker) as s:
        sql = text("SELECT type, status, attempts FROM outbox_events ORDER BY created_at")
        return [tuple(r) for r in s.execute(sql)]


def test_ereignis_nur_bei_commit(world: World, engines: Engines) -> None:
    with pytest.raises(RuntimeError), tenant_transaction(engines.app, world.a.id) as s:
        emit_event(s, "system.ping")
        raise RuntimeError("Abbruch")
    assert _status(engines) == []
    with tenant_transaction(engines.app, world.a.id) as s:
        emit_event(s, "system.ping")
    assert _status(engines) == [("system.ping", "pending", 0)]


def test_worker_arbeitet_im_richtigen_mandanten(world: World, engines: Engines) -> None:
    with tenant_transaction(engines.app, world.b.id) as s:
        emit_event(s, "system.ping")
    r = worker.run_once(engines)
    assert (r.claimed, r.done, r.ok) == (1, 1, True)
    assert _status(engines) == [("system.ping", "done", 1)]
    with tenant_transaction(engines.app, world.b.id) as s:
        assert s.execute(text("SELECT count(*) FROM audit_events WHERE action='system.ping_processed'")).scalar() == 1
    with tenant_transaction(engines.app, world.a.id) as s:
        assert s.execute(text("SELECT count(*) FROM audit_events")).scalar() == 0
    assert worker.run_once(engines).claimed == 0


def test_fehler_wiederholung_und_endgueltig(world: World, engines: Engines, monkeypatch: pytest.MonkeyPatch) -> None:
    def kaputt(s: object, job: worker.Job) -> None:
        raise ValueError("token=abc123geheim kaputt")
    monkeypatch.setitem(worker.HANDLERS, "test.kaputt", kaputt)
    with tenant_transaction(engines.app, world.a.id) as s:
        emit_event(s, "test.kaputt", max_attempts=2)
    r = worker.run_once(engines)
    assert (r.retrying, r.ok) == (1, False)
    with worker_transaction(engines.worker) as s:
        st, versuch, fehler, warten = s.execute(text(
            "SELECT status, attempts, last_error, available_at > now() FROM outbox_events")).one()
    assert (st, versuch, warten) == ("pending", 1, True)
    assert "abc123geheim" not in fehler and "ValueError" in fehler
    with worker_transaction(engines.worker) as s:
        s.execute(text("UPDATE outbox_events SET available_at = now()"))
    assert worker.run_once(engines).failed == 1
    assert _status(engines) == [("test.kaputt", "failed", 2)]


def test_unbekannter_typ_scheitert(world: World, engines: Engines) -> None:
    with tenant_transaction(engines.app, world.a.id) as s:
        emit_event(s, "gibt.es_nicht", max_attempts=1)
    worker.run_once(engines)
    assert _status(engines) == [("gibt.es_nicht", "failed", 1)]


def test_parallele_worker_holen_nichts_doppelt(world: World, engines: Engines) -> None:
    with tenant_transaction(engines.app, world.a.id) as s:
        for _ in range(5):
            emit_event(s, "system.ping")
    erste = worker._claim(engines, 3)
    zweite = worker._claim(engines, 10)
    assert len(erste) == 3 and len(zweite) == 2
    assert not {j.id for j in erste} & {j.id for j in zweite}


def test_haengende_eintraege_werden_freigegeben(world: World, engines: Engines) -> None:
    with tenant_transaction(engines.app, world.a.id) as s:
        emit_event(s, "system.ping")
    assert len(worker._claim(engines, 10)) == 1
    with worker_transaction(engines.worker) as s:
        s.execute(text("UPDATE outbox_events SET locked_at = now() - interval '10 minutes'"))
    assert worker.run_once(engines).done == 1
    assert _status(engines)[0][1] == "done"


def test_worker_rolle_sieht_keine_mandantendaten(world: World, engines: Engines) -> None:
    from sqlalchemy.exc import ProgrammingError
    with pytest.raises(ProgrammingError, match="permission denied"), worker_transaction(engines.worker) as s:
        s.execute(text("SELECT count(*) FROM memberships"))


def test_app_rolle_kann_outbox_nicht_manipulieren(world: World, engines: Engines) -> None:
    from sqlalchemy.exc import ProgrammingError
    with tenant_transaction(engines.app, world.a.id) as s:
        emit_event(s, "system.ping")
    with pytest.raises(ProgrammingError, match="permission denied"), tenant_transaction(engines.app, world.a.id) as s:
        s.execute(text("UPDATE outbox_events SET status='done'"))


def test_handler_doppelt_registrieren() -> None:
    with pytest.raises(RuntimeError):
        worker.handler("system.ping")(lambda s, j: None)
    assert uuid.UUID(int=1)
