from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

MONEY_PLACES = Decimal('0.01')
PRICE_PLACES = Decimal('0.000001')
SHARES_PLACES = Decimal('0.000001')
PCT_PLACES = Decimal('0.0001')


def to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, ''):
        raise ValueError('cannot convert empty value to Decimal')
    return Decimal(str(value))


def quantize(value: Any, *, places: Decimal) -> Decimal:
    return to_decimal(value).quantize(places, rounding=ROUND_HALF_UP)


def money(value: Any) -> Decimal:
    return quantize(value, places=MONEY_PLACES)


def price(value: Any) -> Decimal:
    return quantize(value, places=PRICE_PLACES)


def shares(value: Any) -> Decimal:
    return quantize(value, places=SHARES_PLACES)


def pct(value: Any) -> Decimal:
    return quantize(value, places=PCT_PLACES)


def to_float(value: Decimal) -> float:
    return float(value)
