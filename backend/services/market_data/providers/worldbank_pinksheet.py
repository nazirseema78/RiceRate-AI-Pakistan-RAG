"""World Bank Commodity Price Data ("Pink Sheet") - monthly international rice benchmark prices.

Verified on 2026-11-11:
  * https://www.worldbank.org/en/research/commodity-markets links a free "Monthly prices" Excel file
    (CMO-Historical-Data-Monthly.xlsx) with rice series in USD per metric ton (e.g. "Rice, Thai 5%").
  * World Bank datasets are published under its data terms of use (Creative Commons Attribution);
    attribution: "Source: World Bank Commodity Price Data (The Pink Sheet)".
  * These are MONTHLY AVERAGE export benchmark prices, published once a month. They are stored as
    data_nature=historical, category=export, and must never be read as today's Pakistani rates.
The download URL changes when the World Bank publishes a new edition, so it is configurable
(WORLDBANK_PINKSHEET_URL). If the file cannot be downloaded the connector fails without storing anything.
"""
from __future__ import annotations

import io
import re
from datetime import datetime

from backend.models.price import DataNature, PriceObservation, SourceMetadata, VerificationStatus
from backend.services.market_data.base import (Availability, MarketDataProvider, ProviderError, ProviderResult,
                                               RateLimiter, http_get)

DEFAULT_URL = ("https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/related/"
               "CMO-Historical-Data-Monthly.xlsx")
PAGE_URL = "https://www.worldbank.org/en/research/commodity-markets"
MONTH_RE = re.compile(r"^(\d{4})M(\d{2})$")
MONTHS_TO_KEEP = 24

# header text (lower, stripped) -> (product_key, name, variety, grade, country)
SERIES = {
    "rice, thai 5%": ("wb_rice_thai_5", "Rice, Thai 5% (World Bank monthly avg)", "Thai White", "5% Broken", "Thailand"),
    "rice, thai 25%": ("wb_rice_thai_25", "Rice, Thai 25% (World Bank monthly avg)", "Thai White", "25% Broken", "Thailand"),
    "rice, thai a.1": ("wb_rice_thai_a1", "Rice, Thai A.1 (World Bank monthly avg)", "Thai White", "A.1 Super (100% broken)", "Thailand"),
    "rice, viet namese 5%": ("wb_rice_vn_5", "Rice, Vietnamese 5% (World Bank monthly avg)", "Vietnam White", "5% Broken", "Vietnam"),
}


def _url() -> str:
    from backend.config import get_settings

    return get_settings().worldbank_pinksheet_url or DEFAULT_URL


def parse_pinksheet(content: bytes, months: int = MONTHS_TO_KEEP) -> list[PriceObservation]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    if "Monthly Prices" not in wb.sheetnames:
        raise ProviderError("Pink Sheet format changed: 'Monthly Prices' sheet missing")
    ws = wb["Monthly Prices"]
    all_rows = list(ws.iter_rows(values_only=True))
    header_idx = next((i for i, r in enumerate(all_rows[:20])
                       if any(isinstance(c, str) and c.strip().lower().startswith("rice") for c in r)), None)
    if header_idx is None:
        raise ProviderError("Pink Sheet format changed: rice columns not found")
    header = [str(c).strip().lower() if c is not None else "" for c in all_rows[header_idx]]
    units = [str(c).strip() if c is not None else "" for c in all_rows[header_idx + 1]]
    cols = {i: SERIES[h] for i, h in enumerate(header) if h in SERIES}
    data = [r for r in all_rows[header_idx + 1:] if r and isinstance(r[0], str) and MONTH_RE.match(r[0].strip())]
    out: list[PriceObservation] = []
    for r in data[-months:]:
        y, m = (int(x) for x in MONTH_RE.match(r[0].strip()).groups())
        for i, (key, name, variety, grade, country) in cols.items():
            v = r[i]
            if not isinstance(v, (int, float)) or v <= 0:
                continue  # '…' or blank = not available
            if units[i] and "$/mt" not in units[i].replace(" ", "").lower():
                continue
            out.append(PriceObservation(
                product_key=key, product_name=name, product_type="broken_rice" if "100%" in grade else "rice",
                variety=variety, grade=grade, market=f"{country} export benchmark", city=country, country=country,
                price=float(v), currency="USD", unit="USD/MT", price_category="export",
                observed_at=datetime(y, m, 1), source_name="World Bank Commodity Price Data (Pink Sheet)",
                source_url=PAGE_URL, verification_status=VerificationStatus.verified_source,
                data_nature=DataNature.historical,
                notes=f"Monthly average for {y}-{m:02d} (dated to the 1st of the month). Not a daily quotation."))
    return out


class WorldBankPinkSheetProvider(MarketDataProvider):
    provider_key = "worldbank_pinksheet"
    min_hours_between_runs = 24

    def __init__(self):
        self.limiter = RateLimiter(5.0)

    def get_source_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            provider_key=self.provider_key, name="World Bank Pink Sheet (monthly)", url=PAGE_URL,
            data_nature=DataNature.historical,
            description="Monthly average international rice export benchmarks (Thai 5%, 25%, A.1; Vietnamese 5%) in USD/MT.",
            price_types=["export benchmark (monthly average)"], update_frequency="monthly",
            access_notes="Free download, CC BY 4.0 with attribution. Not real-time.")

    def check_availability(self) -> Availability:
        try:
            r = http_get(PAGE_URL, limiter=self.limiter)
            return Availability(r.ok, "available" if r.ok else "unavailable", f"HTTP {r.status_code}")
        except ProviderError as e:
            return Availability(False, "unavailable", str(e))

    def fetch_latest_prices(self) -> ProviderResult:
        r = http_get(_url(), limiter=self.limiter)
        if not r.ok or not r.content.startswith(b"PK"):
            raise ProviderError(f"Pink Sheet download failed (HTTP {r.status_code}); update WORLDBANK_PINKSHEET_URL")
        obs = parse_pinksheet(r.content)
        return ProviderResult(observations=obs, message=f"{len(obs)} monthly benchmark observations")

    def fetch_historical_prices(self, start=None, end=None) -> ProviderResult:
        return self.fetch_latest_prices()  # the workbook is itself a historical series
