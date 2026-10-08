from __future__ import annotations

import time
from decimal import Decimal

import pytest

from ichq.core.ids import uuid7
from ichq.core.money import Money


def test_uuid7_version_und_variante() -> None:
    u = uuid7()
    assert u.version == 7 and u.variant == "specified in RFC 4122"


def test_uuid7_zeitlich_sortiert_und_eindeutig() -> None:
    a = uuid7()
    time.sleep(0.002)
    b = uuid7()
    assert a < b
    assert len({uuid7() for _ in range(5000)}) == 5000


def test_money_rechnet_exakt() -> None:
    summe = Money.from_decimal("0.10", "EUR")
    for _ in range(9):
        summe = summe + Money.from_decimal("0.10", "EUR")
    assert summe == Money(100, "EUR") and summe.as_decimal() == Decimal("1")


def test_money_rundet_kaufmaennisch() -> None:
    assert Money.from_decimal("2.345", "EUR").minor == 235


def test_money_verbietet_float_und_mischwaehrung() -> None:
    with pytest.raises(TypeError):
        Money.from_decimal(0.1, "EUR")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(1.5, "EUR")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Money(1, "EUR") + Money(1, "USD")
    with pytest.raises(ValueError):
        Money(1, "eur")
