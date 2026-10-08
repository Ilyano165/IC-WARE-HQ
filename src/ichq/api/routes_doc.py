"""Tabelle „Geschützte Endpunkte" — aus dem Code erzeugt, nie von Hand (M4-Vorgabe).

``ichq routes-doc`` gibt sie aus; ``docs/authorization.md`` enthält sie zwischen den Markierungen
``<!-- routen:start -->`` und ``<!-- routen:end -->``, ein Test vergleicht beides.
"""
from __future__ import annotations

from fastapi import FastAPI

from ichq.api.security import _markierungen, iter_api_routes

START, ENDE = "<!-- routen:start -->", "<!-- routen:end -->"
_MARKEN = {"mfa_challenge": "2FA-Zwischenschritt", "any_session": "jede Sitzung", "signed_in": "angemeldet",
           "authenticated": "angemeldet + Firma"}


def _regel(art: str, wert: object) -> str:
    if art == "permission":
        return " + ".join(f"`{p}`" for p in wert)  # type: ignore[attr-defined]
    if art == "public":
        return f"öffentlich — {wert}"
    return _MARKEN[art]


def render(app: FastAPI) -> str:
    zeilen = []
    for pfad, methoden, dep in iter_api_routes(app):
        art, wert = _markierungen(dep)[0]
        zeilen += [(pfad, m, art, _regel(art, wert)) for m in sorted(methoden - {"HEAD"})]
    kopf = ["| Pfad | Methode | Marke | Regel |", "| --- | --- | --- | --- |"]
    return "\n".join(kopf + [f"| `{p}` | {m} | {a} | {r} |" for p, m, a, r in sorted(zeilen)]) + "\n"
