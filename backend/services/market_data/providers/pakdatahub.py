"""PakDataHub wholesale (mandi) price API - re-publishes Punjab AMIS data.

Verified on 2026-11-11 from https://pakdatahub.com/docs:
  * Base URL https://api.pakdatahub.com, endpoints /v1/agri/latest and /v1/agri/prices
    (/v1/agri/commodities and /v1/agri/markets are public, no key).
  * Price endpoints require an `X-API-Key` header. A free plan exists: 500 calls/month,
    10 requests/minute, 1 year of history.
  * Rice/paddy commodity slugs (Punjab, PKR per 100 kg): paddy_basmati, paddy_irri, paddy_kainat,
    rice_basmati_385, rice_basmati_super_new, rice_basmati_super_old, rice_irri, rice_kainat_new,
    rice_kainat_old. Multan, Muzaffargarh, Bahawalpur and Rahim Yar Khan are covered.
  * `fqp` = fair-quality wholesale price. Data updates daily (evening).
  * Terms: internal (incl. commercial) use allowed on all plans; DISPLAYING the data to your own
    customers inside a product requires their Business plan or a written licence. Check before
    showing this data to third parties.

This connector stays disabled until PAKDATAHUB_API_KEY is set in .env. It was written against the
published documentation; it could not be exercised live during development because no key was configured.
To stay inside the free quota it fetches at most once per ~20 hours and at most N commodities per run.
"""
from __future__ import annotations

import logging
from datetime import datetime

from backend.config import get_settings
from backend.models.price import DataNature, PriceObservation, SourceMetadata, VerificationStatus
from backend.services.provider_settings import get_secret
from backend.services.market_data.base import (Availability, MarketDataProvider, ProviderError, ProviderResult,
                                               RateLimiter, http_get)

log = logging.getLogger(__name__)

# slug -> (product_key, name, product_type, variety, grade)
COMMODITIES = {
    "paddy_basmati": ("pdh_paddy_basmati", "Paddy Basmati (AMIS)", "paddy", "Basmati", "Fair average quality"),
    "paddy_irri": ("pdh_paddy_irri", "Paddy IRRI (AMIS)", "paddy", "IRRI", "Fair average quality"),
    "paddy_kainat": ("pdh_paddy_kainat", "Paddy Kainat (AMIS)", "paddy", "Kainat (1121)", "Fair average quality"),
    "rice_basmati_super_new": ("pdh_rice_super_basmati_new", "Rice Basmati Super New (AMIS)", "rice", "Super Basmati", "New crop, fair average quality"),
    "rice_basmati_super_old": ("pdh_rice_super_basmati_old", "Rice Basmati Super Old (AMIS)", "rice", "Super Basmati", "Old crop, fair average quality"),
    "rice_basmati_385": ("pdh_rice_basmati_385", "Rice Basmati 385 (AMIS)", "rice", "Basmati 385", "Fair average quality"),
    "rice_irri": ("pdh_rice_irri", "Rice IRRI (AMIS)", "rice", "IRRI", "Fair average quality"),
    "rice_kainat_new": ("pdh_rice_kainat_new", "Rice Kainat New (AMIS)", "rice", "Kainat (1121)", "New crop, fair average quality"),
    "rice_kainat_old": ("pdh_rice_kainat_old", "Rice Kainat Old (AMIS)", "rice", "Kainat (1121)", "Old crop, fair average quality"),
}
UNIT_MAP = {"pkr_per_100kg": "PKR/100kg", "pkr_per_kg": "PKR/kg"}
TARGET_MARKETS = {"multan", "muzafarghar", "bahawalpur", "rahimyarkhan", "bahawalnagar", "vehari", "khanewal",
                  "lodhran", "dgkhan", "sadiqabad", "lahore", "gujranwala", "sheikhupura", "hafizabad"}


def parse_pakdatahub_rows(slug: str, payload: dict) -> list[PriceObservation]:
    if not payload.get("success", False):
        raise ProviderError(f"PakDataHub error: {payload.get('error')}")
    key, name, ptype, variety, grade = COMMODITIES[slug]
    out = []
    for row in payload.get("data", []):
        price = row.get("fqp")
        unit = UNIT_MAP.get(row.get("unit", ""), None)
        if price in (None, "", 0) or unit is None or not row.get("date"):
            continue  # missing price -> skipped, never filled in
        mslug = (row.get("market_slug") or "").lower()
        if TARGET_MARKETS and mslug and mslug not in TARGET_MARKETS:
            continue
        city = row.get("market") or mslug
        out.append(PriceObservation(
            product_key=key, product_name=name, product_type=ptype, variety=variety, grade=grade,
            market=f"{city} Grain Market (AMIS)", city=city, province=row.get("province", "Punjab") or "Punjab",
            country="Pakistan", price=float(price), currency="PKR", unit=unit, price_category="wholesale",
            observed_at=datetime.fromisoformat(str(row["date"])[:10]), source_name="AMIS Punjab via PakDataHub",
            source_url="https://pakdatahub.com/docs/data-agri-prices",
            verification_status=VerificationStatus.verified_source, data_nature=DataNature.live,
            notes=f"fqp (fair-quality price); min={row.get('min')} max={row.get('max')} arrivals={row.get('quantity')}"))
    return out


class PakDataHubProvider(MarketDataProvider):
    provider_key = "pakdatahub"
    min_hours_between_runs = 20

    def __init__(self):
        self.settings = get_settings()
        self.limiter = RateLimiter(7.0)  # stay below 10 requests/minute

    @property
    def api_key(self) -> str:
        return get_secret("pakdatahub_api_key")  # Settings page first, then .env

    def get_source_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            provider_key=self.provider_key, name="AMIS Punjab via PakDataHub API", url="https://pakdatahub.com/docs/data-agri-prices",
            data_nature=DataNature.live, requires_api_key=True,
            description="Daily Punjab wholesale mandi prices for paddy and rice (PKR/100kg).",
            price_types=["wholesale"], update_frequency="daily (evening)",
            access_notes="Free plan 500 calls/month, 10 req/min. Displaying data to customers needs Business plan/licence.")

    def check_availability(self) -> Availability:
        if not self.api_key:
            return Availability(False, "not_configured", "Add the PakDataHub key on the Settings page (or PAKDATAHUB_API_KEY in .env) to enable (free plan available).")
        # no network probe here: every call counts against the 500/month free quota
        return Availability(True, "available", "API key configured (quota-limited free plan)")

    def fetch_latest_prices(self) -> ProviderResult:
        if not self.api_key:
            raise ProviderError("PAKDATAHUB_API_KEY not configured")
        res = ProviderResult()
        for slug in list(COMMODITIES)[: self.settings.pakdatahub_max_calls_per_run]:
            r = http_get(f"{self.settings.pakdatahub_base_url}/v1/agri/latest", params={"commodity": slug},
                         headers={"X-API-Key": self.api_key}, limiter=self.limiter)
            if r.status_code in (401, 402, 403, 429):
                raise ProviderError(f"PakDataHub HTTP {r.status_code}: {r.text[:200]}")
            if not r.ok:
                log.warning("PakDataHub %s HTTP %s", slug, r.status_code)
                continue
            res.observations += parse_pakdatahub_rows(slug, r.json())
        res.message = f"{len(res.observations)} wholesale observations"
        return res
