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


# Kommt mit den Fachmodulen (Produktvision 4.2). Bis dahin: keine Werte, keine Platzhalter-Zahlen.
PLANNED: tuple[Planned, ...] = (
    Planned("liquidity", "Liquidität", "S6 Zahlungen & Liquidität", ("finance.read",)),
    Planned("open_invoices", "Offene Rechnungen", "S5 Rechnungen & E-Rechnung", ("invoices.read",)),
    Planned("overdue_payments", "Überfällige Zahlungen", "S6 Zahlungen & Liquidität", ("finance.read",)),
    Planned("missing_receipts", "Fehlende Belege", "S1 Belegeingang", ("finance.read",)),
    Planned("tax_deadlines", "Steuerfristen", "S8 Steuertermine & Fristen", ("finance.read",)),
    Planned("month_close", "Monatsabschluss", "S7 Steuerberater-Arbeitsplatz", ("finance.export",)),
    Planned("datev_export", "DATEV-/Exportstatus", "S7 Steuerberater-Arbeitsplatz", ("finance.export",)),
    Planned("projects", "Projekte", "Projektmodul", ("projects.read",)),
    Planned("project_profitability", "Projektprofitabilität", "Projektmodul + S6", ("projects.read", "finance.read")),
    Planned("contracts", "Verträge", "Vertragsmodul", ("contracts.read",)),
    Planned("travel", "Reisen", "S3 Reisen & Reisekosten", ("travel.read",)),
    Planned("trips", "Fahrten", "S2 Fahrtenbuch", ("vehicles.read",)),
    Planned("crm", "Kunden & Anfragen", "CRM", ("customers.read",)),
)
assert all(is_known(r) for p in PLANNED for r in p.requires)
