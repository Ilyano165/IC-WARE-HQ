"""D0: Die Rechte-Tabelle der Rollenvorlagen in docs/d0-dashboard.md ist aus dem Code erzeugt und aktuell."""
from __future__ import annotations

from pathlib import Path

from ichq.authz.templates import table_markdown

DOC = Path(__file__).resolve().parent.parent / "docs" / "d0-dashboard.md"
START, ENDE = "<!-- vorlagen:start -->", "<!-- vorlagen:end -->"


def test_vorlagentabelle_ist_aktuell() -> None:
    text = DOC.read_text()
    abschnitt = text.split(START, 1)[1].split(ENDE, 1)[0].strip("\n") + "\n"
    assert abschnitt == table_markdown(), "docs/d0-dashboard.md veraltet: Tabelle aus table_markdown() übernehmen"
    assert "| `finance` |" in abschnitt and "| `objects` | read_all, share | read_all, share | — | — |" in abschnitt
