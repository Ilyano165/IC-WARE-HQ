"""Doku = Code: core-permissions.md, m3-mandanten.md und authorization.md nennen zusammen JEDE /api/v1-Route
(außer /auth) mit echter Marke."""
from __future__ import annotations

import re
from pathlib import Path

from ichq.api.security import _markierungen, iter_api_routes
from ichq.app import create_app
from ichq.core.config import Settings
from ichq.db.engine import Engines

DOCS = [Path(__file__).resolve().parent.parent / "docs" / n
        for n in ("core-permissions.md", "m3-mandanten.md", "authorization.md", "d0-dashboard.md")]


def test_routentabelle_entspricht_dem_code(settings: Settings, engines: Engines) -> None:
    app = create_app(settings, engines=engines)
    code = set()
    for pfad, methoden, dep in iter_api_routes(app):
        if pfad.startswith("/api/v1/") and not pfad.startswith("/api/v1/auth/"):
            art, wert = _markierungen(dep)[0]
            regel = ", ".join(wert) if art == "permission" else art
            code |= {(m, pfad, regel) for m in methoden}
    doku = set()
    for doc in DOCS:
        for m, pfad, regel in re.findall(r"^\| `([A-Z]+)` \| `([^`]+)` \| ([^|]+?) \|$", doc.read_text(), re.M):
            doku.add((m, pfad, regel.split(" (")[0].strip()))
    assert len(code) >= 40
    assert code == doku, {"fehlt in Doku": code - doku, "nur in Doku": doku - code}
