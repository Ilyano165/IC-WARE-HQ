"""Doku = Code: Die Routentabelle in docs/core-permissions.md muss jede Core-Route mit ihrer echten Marke nennen."""
from __future__ import annotations

import re
from pathlib import Path

from ichq.api.security import _markierungen, iter_api_routes
from ichq.app import create_app
from ichq.core.config import Settings
from ichq.db.engine import Engines

DOC = Path(__file__).resolve().parent.parent / "docs" / "core-permissions.md"
CORE = ("/api/v1/objects", "/api/v1/links", "/api/v1/tasks", "/api/v1/comments", "/api/v1/documents",
        "/api/v1/notifications", "/api/v1/search", "/api/v1/audit", "/api/v1/activities", "/api/v1/members")


def test_routentabelle_entspricht_dem_code(settings: Settings, engines: Engines) -> None:
    app = create_app(settings, engines=engines)
    code = set()
    for pfad, methoden, dep in iter_api_routes(app):
        if pfad.startswith(CORE):
            art, wert = _markierungen(dep)[0]
            regel = ", ".join(wert) if art == "permission" else art
            code |= {(m, pfad, regel) for m in methoden}
    doku = set()
    for m, pfad, regel in re.findall(r"^\| `([A-Z]+)` \| `([^`]+)` \| ([^|]+?) \|$", DOC.read_text(), re.M):
        doku.add((m, pfad, regel.split(" (")[0].strip()))
    assert len(code) >= 30
    assert code == doku, {"fehlt in Doku": code - doku, "nur in Doku": doku - code}
