"""Geldrechnung ohne Gleitkomma. Rundung: kaufmännisch (halb weg von null), JE POSITION — dokumentiert in
docs/fachmodule.md. Ob diese Rundung den Anforderungen der Firma bzw. des Steuerberaters genügt, ist nicht geprüft."""
from __future__ import annotations

from dataclasses import dataclass


def runde_div(zaehler: int, nenner: int) -> int:
    """Ganzzahlige Division mit kaufmännischer Rundung (0,5 → weg von null). Exakt für beliebig große Ganzzahlen."""
    if nenner <= 0:
        raise ValueError("nenner muss positiv sein")
    vorzeichen = -1 if zaehler < 0 else 1
    q, r = divmod(abs(zaehler), nenner)
    if 2 * r >= nenner:
        q += 1
    return vorzeichen * q


@dataclass(frozen=True)
class Zeile:
    net_minor: int
    tax_minor: int


def zeile(quantity_milli: int, unit_price_minor: int, tax_rate_bp: int) -> Zeile:
    """Netto = Menge × Einzelpreis (gerundet auf Cent), Steuer = Netto × Satz (gerundet auf Cent)."""
    if not 0 <= tax_rate_bp <= 10_000:
        raise ValueError("tax_rate_bp außerhalb 0–10000")
    netto = runde_div(quantity_milli * unit_price_minor, 1000)
    return Zeile(netto, runde_div(netto * tax_rate_bp, 10_000))


@dataclass(frozen=True)
class Summe:
    net_minor: int
    tax_minor: int
    gross_minor: int
    tax_by_rate: dict[int, tuple[int, int]]     # Satz (bp) → (Netto, Steuer)


def summe(zeilen: list[tuple[int, Zeile]]) -> Summe:
    """``zeilen``: (Steuersatz bp, berechnete Zeile). Aufstellung je Steuersatz für die Rechnungsansicht."""
    je_satz: dict[int, tuple[int, int]] = {}
    for satz, z in zeilen:
        n, t = je_satz.get(satz, (0, 0))
        je_satz[satz] = (n + z.net_minor, t + z.tax_minor)
    netto = sum(z.net_minor for _, z in zeilen)
    steuer = sum(z.tax_minor for _, z in zeilen)
    return Summe(netto, steuer, netto + steuer, dict(sorted(je_satz.items())))
