"""Prüfungen für /health und /readiness.

Antworten nach außen nennen nur ``ok``/``fail`` — Ursachen (Hostnamen, Fehlertexte)
gehen ins Log, nie in die Antwort.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from ichq.storage.base import Storage

log = logging.getLogger("ichq.health")
MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    ms: int
    reason: str | None = None   # nur kurze, feste Kennungen — nie Fehlertexte


@lru_cache(maxsize=1)
def expected_head() -> str | None:
    return ScriptDirectory(str(MIGRATIONS)).get_current_head()


def _zeit(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def check_database(engine: Engine) -> Check:
    t0 = time.perf_counter()
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        return Check("database", True, _zeit(t0))
    except Exception:
        log.exception("health_database_fehler")
        return Check("database", False, _zeit(t0), "unreachable")


def check_migrations(engine: Engine) -> Check:
    t0 = time.perf_counter()
    try:
        with engine.connect() as c:
            aktuell = c.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if aktuell != expected_head():
            log.warning("health_migration_veraltet", extra={"db": aktuell, "erwartet": expected_head()})
            return Check("migrations", False, _zeit(t0), "not_at_head")
        return Check("migrations", True, _zeit(t0))
    except Exception:
        log.exception("health_migration_fehler")
        return Check("migrations", False, _zeit(t0), "unknown")


def check_storage(storage: Storage) -> Check:
    t0 = time.perf_counter()
    try:
        storage.check()
        return Check("storage", True, _zeit(t0))
    except Exception:
        log.exception("health_storage_fehler")
        return Check("storage", False, _zeit(t0), "unavailable")
