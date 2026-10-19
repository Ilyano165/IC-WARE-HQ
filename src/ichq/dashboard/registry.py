"""Widget-Registry des Dashboards (D0, ADR-014).

Ein Widget nennt die Rechte, die es braucht (``requires`` — ALLE müssen effektiv vorhanden sein, geprüft im Server
mit ``decide``), und einen Loader, der seine Daten über dieselben Filter/Sichtbarkeitsregeln wie die Listen holt.
Geplante Module (``PLANNED``) haben KEINEN Loader und liefern nie Werte — nur Titel und Modul, und auch das nur,
wenn die Rechte vorhanden sind. Ein neues Fachmodul registriert sein Widget hier und entfernt den Planeintrag.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from ichq.authz.registry import is_known


@dataclass(frozen=True)
class Context:
    today: date               # „heute" in der Zeitzone der Firma
    tenant_status: str


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    value: int
    filter: dict[str, Any] = field(default_factory=dict)   # Filter der verlinkten Liste → dieselbe Zahl
    tone: str = "neutral"                                  # neutral | warn | danger
    linked: bool = True    # False: es gibt keine Liste mit genau diesem Filter ⇒ Zahl ohne Link (Regel „Zahl = Liste")


@dataclass(frozen=True)
class Item:
    id: str | None
    type: str | None
    title: str
    detail: str = ""
    date: str | None = None
    tone: str = "neutral"
    list: str | None = None                                # Hinweise ohne Einzelobjekt: Liste + Filter dahinter
    filter: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Data:
    list: str | None                       # Liste hinter den Zahlen: tasks | documents | questions | …
    metrics: tuple[Metric, ...] = ()
    items: tuple[Item, ...] = ()
    empty: str = "Keine Daten vorhanden."


Loader = Callable[[Any, Any, Context], Data]


@dataclass(frozen=True)
class Widget:
    key: str
    title: str
    requires: tuple[str, ...]
    loader: Loader
    size: str = "m"            # s | m | l — nur Layout


@dataclass(frozen=True)
class Planned:
    key: str
    title: str
    module: str
    requires: tuple[str, ...]


WIDGETS: dict[str, Widget] = {}


def register(key: str, title: str, requires: tuple[str, ...], size: str = "m") -> Callable[[Loader], Loader]:
    unbekannt = [r for r in requires if not is_known(r)]
    if unbekannt or key in WIDGETS:
        raise ValueError(f"Widget {key}: unbekannte Rechte {unbekannt} oder doppelt")

    def deko(fn: Loader) -> Loader:
        WIDGETS[key] = Widget(key, title, requires, fn, size)
        return fn
    return deko


# Noch nicht gebaute Module: keine Werte, keine Platzhalter-Zahlen (Fachmodule: dashboard/fach.py).
PLANNED: tuple[Planned, ...] = (
    # Nicht gebaut: das DATEV-Format (Export gibt es nur im internen CSV-Format, docs/export-format.md).
    Planned("datev_export", "DATEV-Export", "nicht gebaut — internes CSV unter Abschluss & Export",
            ("finance.export",)),
)
assert all(is_known(r) for p in PLANNED for r in p.requires)
