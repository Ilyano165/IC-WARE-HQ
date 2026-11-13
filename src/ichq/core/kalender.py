"""Kalenderrechnung ohne Fachwissen: Monate addieren (Monatsende wird gekappt), Zeiträume als Zahl + Einheit."""
from __future__ import annotations

import calendar
from datetime import date, timedelta

EINHEITEN = ("days", "weeks", "months")
PERIODEN = {"monthly": 1, "quarterly": 3, "yearly": 12}


def plus_monate(d: date, n: int) -> date:
    """31.01. + 1 Monat = 28./29.02.; 29.02. + 12 Monate = 28.02. — nie ein ungültiges Datum."""
    m = d.month - 1 + n
    jahr, monat = d.year + m // 12, m % 12 + 1
    return date(jahr, monat, min(d.day, calendar.monthrange(jahr, monat)[1]))


def verschiebe(d: date, wert: int, einheit: str) -> date:
    """``d`` um ``wert`` Tage/Wochen/Monate verschieben (negativ = zurück)."""
    if einheit == "days":
        return d + timedelta(days=wert)
    if einheit == "weeks":
        return d + timedelta(weeks=wert)
    if einheit == "months":
        return plus_monate(d, wert)
    raise ValueError(f"unbekannte Einheit {einheit!r}")
