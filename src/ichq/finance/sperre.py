"""Periodensperre im Service: abgeschlossene Monate vor dem Schreiben prüfen und verständlich ablehnen (409).
Die verbindliche Sperre sind die Trigger aus Migration 0015 — das hier ist die erste Linie für klare Fehlermeldungen."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ichq.core.errors import Conflict
from ichq.finance.models_closing import MonthClose


def geschlossen(session: Session, d: date | None) -> bool:
    if d is None:
        return False
    with session.no_autoflush:          # sonst schriebe die Abfrage den halb geänderten Datensatz (Trigger → 500)
        return session.scalar(select(MonthClose.id).where(MonthClose.period == d.replace(day=1),
                                                          MonthClose.reopened_at.is_(None))) is not None


def pruefe(session: Session, *daten: date | None) -> None:
    for d in daten:
        if geschlossen(session, d):
            assert d is not None
            raise Conflict(f"Monat {d:%Y-%m} ist abgeschlossen — Änderung erst nach Wiedereröffnen")
