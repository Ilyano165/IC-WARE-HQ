"""Einstiegspunkte in FRISCHEN Prozessen.

Innerhalb der Testsuite sind alle Module längst importiert — ein Fehler, bei dem
ein Prozess ein Modell nicht lädt, bleibt dort unsichtbar. Genau so war der
Worker-Fehler aus M1 entstanden. Deshalb hier: echte Unterprozesse.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import text

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.db.session import tenant_transaction, worker_transaction
from ichq.jobs.service import emit_event
from tests.conftest import World

ERWARTET = {"tenants", "users", "memberships", "roles", "role_permissions", "membership_roles",
            "audit_events", "platform_audit_events", "outbox_events", "auth_sessions", "password_reset_tokens",
            "recovery_codes", "login_attempts", "auth_events", "objects", "object_links", "object_grants",
            "activities", "comments", "comment_mentions", "tasks", "documents", "notifications"}


def _umgebung(settings: Settings) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ICHQ_")}
    for name in ("database_url", "platform_database_url", "worker_database_url", "auth_database_url",
                 "secret_key", "session_secret"):
        env[f"ICHQ_{name.upper()}"] = getattr(settings, name).get_secret_value()
    env["ICHQ_STORAGE_PATH"] = str(settings.storage_path)
    env["ICHQ_LOG_FORMAT"] = "json"
    return env


@pytest.mark.parametrize("modul", ["ichq.app", "ichq.cli", "ichq.asgi"])
def test_einstiegspunkt_registriert_alle_tabellen(modul: str, settings: Settings) -> None:
    code = (f"import {modul}\nfrom ichq.db.base import Base\n"
            "print(','.join(sorted(Base.metadata.tables)))")
    r = subprocess.run([sys.executable, "-c", code], env=_umgebung(settings), capture_output=True, text=True,
                       timeout=60)
    assert r.returncode == 0, r.stderr[-500:]
    assert set(r.stdout.strip().splitlines()[-1].split(",")) >= ERWARTET


def test_worker_als_eigener_prozess(world: World, settings: Settings, engines: Engines) -> None:
    with tenant_transaction(engines.app, world.a.id) as s:
        emit_event(s, "system.ping")
    r = subprocess.run([sys.executable, "-m", "ichq.cli", "worker", "--once"], env=_umgebung(settings),
                       capture_output=True, text=True, timeout=60)
    zusammenfassung = [z for z in r.stdout.splitlines() if z.startswith("abgeholt")]
    assert r.returncode == 0, r.stdout[-800:] + r.stderr[-800:]
    assert zusammenfassung == ["abgeholt 1 · erledigt 1 · wird wiederholt 0 · endgültig gescheitert 0"]
    with worker_transaction(engines.worker) as s:
        assert s.execute(text("SELECT status FROM outbox_events")).scalar() == "done"
    with tenant_transaction(engines.app, world.a.id) as s:
        assert s.execute(text("SELECT count(*) FROM audit_events WHERE action='system.ping_processed'")).scalar() == 1


def test_worker_meldet_fehlschlag_mit_exitcode(world: World, settings: Settings, engines: Engines) -> None:
    with tenant_transaction(engines.app, world.a.id) as s:
        emit_event(s, "gibt.es_nicht", max_attempts=1)
    r = subprocess.run([sys.executable, "-m", "ichq.cli", "worker", "--once"], env=_umgebung(settings),
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 1
    assert "endgültig gescheitert 1" in r.stdout


def test_fehlende_registrierung_wird_erkannt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gegenprobe: zeigt ein Fremdschlüssel auf eine nicht registrierte Tabelle, schlägt der Start fehl."""
    import types

    import sqlalchemy as sa

    import ichq.models as reg
    m = sa.MetaData()
    sa.Table("a", m, sa.Column("x", sa.Integer, sa.ForeignKey("fehlt.id")))
    monkeypatch.setattr(reg, "Base", types.SimpleNamespace(metadata=m))
    with pytest.raises(RuntimeError, match="a → fehlt"):
        reg.assert_complete()
