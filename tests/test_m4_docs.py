"""M4: Die Tabelle „Geschützte Endpunkte" in docs/authorization.md ist aus dem Code erzeugt und aktuell."""
from __future__ import annotations

import os
from pathlib import Path

from ichq.api.routes_doc import ENDE, START, render
from ichq.app import create_app
from ichq.core.config import Settings
from ichq.db.engine import Engines

DOC = Path(__file__).resolve().parent.parent / "docs" / "authorization.md"


def _abschnitt(text: str) -> str:
    return text.split(START, 1)[1].split(ENDE, 1)[0].strip("\n") + "\n"


def test_routentabelle_ist_aktuell(settings: Settings, engines: Engines) -> None:
    erzeugt = render(create_app(settings, engines=engines))
    if os.environ.get("ICHQ_UPDATE_DOCS") == "1":            # bewusst nur von Hand: Tabelle neu schreiben
        alt = DOC.read_text()
        DOC.write_text(alt.split(START)[0] + START + "\n" + erzeugt + ENDE + alt.split(ENDE, 1)[1])
    assert _abschnitt(DOC.read_text()) == erzeugt, "docs/authorization.md veraltet: ichq routes-doc ausführen"
    zeilen = erzeugt.count("\n| `")
    assert zeilen >= 70, zeilen                                       # die Tabelle enthält wirklich alle Routen
    assert "| `/api/v1/roles/{role}` | PATCH | permission | `roles.update` |" in erzeugt
    assert "| `/health` | GET | public |" in erzeugt
