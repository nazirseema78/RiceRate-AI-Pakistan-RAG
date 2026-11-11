"""Price unit normalisation.

PKR prices are normalised to PKR/kg and USD prices to USD/MT. The original price and unit are
always kept. Currencies are NEVER converted here: a currency conversion needs a dated, verified
exchange rate (see `convert_currency`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# kilograms represented by one unit
_UNIT_KG = {
    "kg": 1.0,
    "40kg": 40.0,   # one maund (mann), common in Punjab mandis
    "maund": 40.0,
    "100kg": 100.0,
    "mt": 1000.0,   # metric ton
    "ton": 1000.0,
}
SUPPORTED_UNITS = {"PKR/kg", "PKR/40kg", "PKR/100kg", "PKR/MT", "USD/MT", "USD/kg"}
_ALIASES = {
    "pkr/metric ton": "PKR/MT", "pkr/ton": "PKR/MT", "pkr/mt": "PKR/MT", "pkr_per_100kg": "PKR/100kg",
    "pkr/100 kg": "PKR/100kg", "pkr/40 kg": "PKR/40kg", "pkr/maund": "PKR/40kg", "pkr_per_kg": "PKR/kg",
    "usd/metric ton": "USD/MT", "usd/ton": "USD/MT", "usd/mt": "USD/MT", "pkr/kg": "PKR/kg",
    "pkr/40kg": "PKR/40kg", "pkr/100kg": "PKR/100kg", "usd/kg": "USD/kg",
}


class UnitError(ValueError):
    pass


def canonical_unit(unit: str) -> str:
    u = unit.strip()
    if u in SUPPORTED_UNITS:
        return u
    alias = _ALIASES.get(u.lower())
    if alias:
        return alias
    raise UnitError(f"Unsupported price unit: {unit!r}")


def split_unit(unit: str) -> tuple[str, str]:
    u = canonical_unit(unit)
    currency, qty = u.split("/")
    return currency, qty.lower()


def normalize_price(price: float, unit: str) -> tuple[float, str]:
    """Return (normalised_price, normalised_unit) in the SAME currency.

    PKR -> PKR/kg ; USD -> USD/MT
    """
    currency, qty = split_unit(unit)
    per_kg = price / _UNIT_KG[qty]
    if currency == "PKR":
        return round(per_kg, 4), "PKR/kg"
    if currency == "USD":
        return round(per_kg * 1000.0, 4), "USD/MT"
    raise UnitError(f"Unsupported currency in unit {unit!r}")


def convert_between_units(price: float, from_unit: str, to_unit: str) -> float:
    c1, q1 = split_unit(from_unit)
    c2, q2 = split_unit(to_unit)
    if c1 != c2:
        raise UnitError("Unit conversion cannot change currency; use convert_currency with a dated rate")
    return price / _UNIT_KG[q1] * _UNIT_KG[q2]


@dataclass(frozen=True)
class ExchangeRate:
    base: str
    quote: str
    rate: float
    rate_date: date
    source: str
    verified: bool


def convert_currency(amount: float, rate: ExchangeRate | None, from_ccy: str, to_ccy: str) -> float:
    """Convert only with an explicit, dated, verified exchange rate. Otherwise refuse."""
    if from_ccy == to_ccy:
        return amount
    if rate is None or not rate.verified or not rate.source or rate.rate <= 0:
        raise UnitError("No dated, verified exchange rate available - currency conversion refused")
    if (rate.base, rate.quote) == (from_ccy, to_ccy):
        return amount * rate.rate
    if (rate.base, rate.quote) == (to_ccy, from_ccy):
        return amount / rate.rate
    raise UnitError("Exchange rate does not match the requested currency pair")
