"""Validation of incoming price observations (sanity bounds, timestamps, units)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.models.price import PriceObservation
from backend.services.market_data.units import UnitError, canonical_unit, normalize_price

PKT = ZoneInfo("Asia/Karachi")

# plausible ranges on the normalised basis. Values outside are rejected, never "fixed".
BOUNDS = {
    "PKR/kg": (10.0, 3000.0),
    "USD/MT": (100.0, 5000.0),
}
ALLOWED_CURRENCIES = {"PKR", "USD"}


class ValidationResult:
    def __init__(self, ok: bool, reason: str = "", normalized_price: float | None = None, normalized_unit: str = "", unit: str = ""):
        self.ok, self.reason = ok, reason
        self.normalized_price, self.normalized_unit, self.unit = normalized_price, normalized_unit, unit

    def __bool__(self) -> bool:
        return self.ok


def to_pkt(dt: datetime) -> datetime:
    """Naive timestamps are interpreted as Pakistan Standard Time."""
    return dt.replace(tzinfo=PKT) if dt.tzinfo is None else dt.astimezone(PKT)


def validate_observation(obs: PriceObservation, now: datetime | None = None) -> ValidationResult:
    now = now or datetime.now(PKT)
    if obs.price is None or obs.price != obs.price or obs.price <= 0:  # NaN check via != itself
        return ValidationResult(False, "missing or non-positive price")
    if obs.currency not in ALLOWED_CURRENCIES:
        return ValidationResult(False, f"unsupported currency {obs.currency}")
    try:
        unit = canonical_unit(obs.unit)
    except UnitError as e:
        return ValidationResult(False, str(e))
    if not unit.startswith(obs.currency + "/"):
        return ValidationResult(False, f"unit {unit} does not match currency {obs.currency}")
    observed = to_pkt(obs.observed_at)
    if observed > now + timedelta(hours=1):
        return ValidationResult(False, "observation timestamp is in the future")
    if observed < now - timedelta(days=365 * 25):
        return ValidationResult(False, "observation timestamp is implausibly old")
    norm, norm_unit = normalize_price(obs.price, unit)
    lo, hi = BOUNDS[norm_unit]
    if not lo <= norm <= hi:
        return ValidationResult(False, f"normalised price {norm} {norm_unit} outside plausible range {lo}-{hi}")
    return ValidationResult(True, "", norm, norm_unit, unit)
