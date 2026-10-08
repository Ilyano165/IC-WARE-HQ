"""Dashboard zusammenstellen (D0, ADR-014): nur Widgets, deren Rechte der Principal EFFEKTIV hat; jedes Widget in
einem eigenen Savepoint — scheitert eines, bleiben die anderen (und die Transaktion) intakt."""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

import ichq.dashboard.loaders  # noqa: F401  — registriert die Widgets
from ichq.authz.service import Principal, decide
from ichq.core.errors import NotFound
from ichq.dashboard.registry import PLANNED, WIDGETS, Context

log = logging.getLogger("ichq.dashboard")

REIHENFOLGE = ("warnings", "my_tasks", "questions", "notifications", "documents", "team_tasks", "company",
               "activity")


def erlaubt(p: Principal, requires: tuple[str, ...]) -> bool:
    return all(decide(p, r) for r in requires)


def context(session: Session, p: Principal) -> Context:
    """„Heute" in der Zeitzone der Firma (Fälligkeit ist ein Kalendertag der Firma, nicht UTC)."""
    heute = session.execute(text("SELECT (now() AT TIME ZONE timezone)::date FROM tenants WHERE id = :t"),
                            {"t": p.tenant_id}).scalar_one()
    assert isinstance(heute, date)
    return Context(today=heute, tenant_status=p.tenant_status)


def build(session: Session, p: Principal, *, only: str | None = None) -> dict[str, Any]:
    if only is not None and only not in WIDGETS:
        raise NotFound("Widget unbekannt")
    ctx = context(session, p)
    widgets = []
    for key in REIHENFOLGE:
        w = WIDGETS[key]
        if (only is not None and key != only) or not erlaubt(p, w.requires):
            continue
        try:
            with session.begin_nested():
                daten: dict[str, Any] = asdict(w.loader(session, p, ctx))
        except Exception:   # ein defektes Widget darf das Dashboard nicht leeren
            log.exception("dashboard_widget_fehler", extra={"widget": key})
            daten = {"error": "unavailable"}
        widgets.append({"key": key, "title": w.title, "size": w.size, **daten})
    if only is not None and not widgets:
        raise NotFound("Widget unbekannt")       # fehlendes Recht sieht aus wie „gibt es nicht"
    geplant = [{"key": g.key, "title": g.title, "module": g.module} for g in PLANNED
               if only is None and erlaubt(p, g.requires)]
    return {"today": ctx.today.isoformat(), "widgets": widgets, "planned": geplant}


assert set(REIHENFOLGE) == set(WIDGETS), "Jedes registrierte Widget braucht einen Platz in REIHENFOLGE"
