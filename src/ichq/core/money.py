"""Geld als ganze kleinste Einheit (Cent) plus Währung — nie Gleitkomma (M0, Abschnitt 16)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

_WAEHRUNG = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.minor, int) or isinstance(self.minor, bool):
            raise TypeError("minor muss int sein")
        if not _WAEHRUNG.match(self.currency):
            raise ValueError("currency muss ein ISO-4217-Code sein (z. B. EUR)")

    @classmethod
    def from_decimal(cls, betrag: Decimal | str, currency: str) -> Money:
        if isinstance(betrag, float):
            raise TypeError("float ist für Geld nicht erlaubt")
        d = Decimal(str(betrag)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return cls(int(d * 100), currency)

    def __add__(self, other: Money) -> Money:
        if other.currency != self.currency:
            raise ValueError("Währungen verschieden")
        return Money(self.minor + other.minor, self.currency)

    def as_decimal(self) -> Decimal:
        return Decimal(self.minor) / 100
