from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from ichq.core.config import Settings
from ichq.db.engine import Engines
from ichq.storage import Storage


@dataclass(frozen=True)
class AppState:
    settings: Settings
    engines: Engines
    storage: Storage
    mail_enabled: bool = False   # SMTP eingerichtet (oder Test-Zustellweg) — sonst 503 für Reset/Einladung


def get_state(request: Request) -> AppState:
    state: AppState = request.app.state.ichq
    return state
