from datetime import date, datetime, timedelta

import pytest

from backend.models.price import PriceObservation
from backend.services.market_data.units import (ExchangeRate, UnitError, canonical_unit, convert_between_units,
                                                convert_currency, normalize_price)
from backend.services.market_data.validation import PKT, validate_observation


def obs(**kw):
    base = dict(product_key="paddy_1121_basmati", product_name="1121 Basmati Paddy", product_type="paddy",
                variety="1121 Basmati", grade="Std", market="Multan Grain Market", city="Multan", country="Pakistan",
                price=4600, currency="PKR", unit="PKR/40kg", price_category="wholesale",
                observed_at=datetime(2026, 11, 10, 10), source_name="test", verification_status="synthetic_demo",
                data_nature="synthetic")
    base.update(kw)
    return PriceObservation(**base)


@pytest.mark.parametrize("price,unit,expected,nunit", [
    (4600, "PKR/40kg", 115.0, "PKR/kg"),
    (11500, "PKR/100kg", 115.0, "PKR/kg"),
    (115000, "PKR/MT", 115.0, "PKR/kg"),
    (115, "PKR/kg", 115.0, "PKR/kg"),
    (420, "USD/MT", 420.0, "USD/MT"),
    (0.42, "USD/kg", 420.0, "USD/MT"),
])
def test_unit_normalisation(price, unit, expected, nunit):
    assert normalize_price(price, unit) == (pytest.approx(expected), nunit)


def test_unit_aliases_and_rejection():
    assert canonical_unit("pkr_per_100kg") == "PKR/100kg"
    assert canonical_unit("PKR/metric ton") == "PKR/MT"
    with pytest.raises(UnitError):
        canonical_unit("PKR/bag")


def test_convert_between_units_same_currency_only():
    assert convert_between_units(115, "PKR/kg", "PKR/40kg") == pytest.approx(4600)
    with pytest.raises(UnitError):
        convert_between_units(420, "USD/MT", "PKR/MT")


def test_currency_conversion_requires_verified_dated_rate():
    with pytest.raises(UnitError):
        convert_currency(420, None, "USD", "PKR")
    unverified = ExchangeRate("USD", "PKR", 280.0, date(2026, 11, 10), "manual", verified=False)
    with pytest.raises(UnitError):
        convert_currency(420, unverified, "USD", "PKR")
    ok = ExchangeRate("USD", "PKR", 280.0, date(2026, 11, 10), "State Bank of Pakistan", verified=True)
    assert convert_currency(420, ok, "USD", "PKR") == pytest.approx(117600)


def test_valid_observation_passes():
    v = validate_observation(obs())
    assert v.ok and v.normalized_price == pytest.approx(115) and v.normalized_unit == "PKR/kg"


@pytest.mark.parametrize("kw,reason", [
    ({"price": 0}, "non-positive"),
    ({"price": -5}, "non-positive"),
    ({"price": float("nan")}, "non-positive"),
    ({"unit": "PKR/bag"}, "Unsupported"),
    ({"currency": "EUR", "unit": "USD/MT"}, "unsupported currency"),
    ({"currency": "USD", "unit": "PKR/kg"}, "does not match"),
    ({"price": 9_999_999}, "outside plausible range"),
])
def test_invalid_observations_rejected(kw, reason):
    v = validate_observation(obs(**kw))
    assert not v.ok and reason in v.reason


def test_future_timestamp_rejected():
    future = datetime.now(PKT) + timedelta(days=2)
    v = validate_observation(obs(observed_at=future))
    assert not v.ok and "future" in v.reason
