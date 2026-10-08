"""/health = Prozess lebt (Liveness) mit Komponentenübersicht. Immer 200, solange der Prozess antwortet.
/readiness = darf Verkehr annehmen. 503, sobald Datenbank, Migrationsstand oder Speicher nicht stimmen.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ichq import __version__
from ichq.api.security import public
from ichq.api.state import AppState, get_state
from ichq.health.checks import Check, check_database, check_migrations, check_storage

router = APIRouter()


def _form(checks: list[Check]) -> dict[str, Any]:
    return {c.name: {"status": "ok" if c.ok else "fail", "ms": c.ms, **({"reason": c.reason} if c.reason else {})}
            for c in checks}


@router.api_route("/health", methods=["GET", "HEAD"])
def health(_: None = Depends(public("Liveness für Orchestrierung")),
           state: AppState = Depends(get_state)) -> JSONResponse:
    checks = [check_database(state.engines.app), check_storage(state.storage)]
    status = "ok" if all(c.ok for c in checks) else "degraded"
    return JSONResponse({"status": status, "version": __version__, "application": {"status": "ok"},
                         "checks": _form(checks)})


@router.api_route("/readiness", methods=["GET", "HEAD"])
def readiness(_: None = Depends(public("Bereitschaft für Load Balancer")),
              state: AppState = Depends(get_state)) -> JSONResponse:
    checks = [check_database(state.engines.app), check_migrations(state.engines.app),
              check_storage(state.storage)]
    bereit = all(c.ok for c in checks)
    return JSONResponse({"status": "ready" if bereit else "not_ready", "checks": _form(checks)},
                        status_code=200 if bereit else 503)
