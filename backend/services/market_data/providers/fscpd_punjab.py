"""Punjab Food, Commodity Prices & Consumer Protection Department (FS&CPD) - notified daily rates.

Verified on 2026-11-11:
  * https://fscpdpunjab.gop.pk/Commodities/Prices/ is publicly reachable and publishes a daily
    "Notified Rates" HTML table (41 districts). The only rice item is "Rice Basmati New (Kg)".
  * robots.txt allows all paths for generic user agents (Content-Signal: search=yes, ai-train=no,
    use=reference). This connector only reads the public table a few times a day with a clear
    User-Agent; it does not train models on the content.
  * No API is published. Price type is published only as "Notified Rates" (government notified
    consumer rates), so they are stored as category=retail and never compared with wholesale.
  * A value of 0 in the table means "not reported" and is skipped - never stored as a price.
"""
from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from backend.models.price import DataNature, PriceObservation, SourceMetadata, VerificationStatus
from backend.services.market_data.base import (Availability, MarketDataProvider, ProviderError, ProviderResult,
                                               RateLimiter, http_get)

URL = "https://fscpdpunjab.gop.pk/Commodities/Prices/"
RICE_COLUMN = re.compile(r"rice\s*basmati\s*new", re.I)
DATE_RE = re.compile(r"Notified Rates\s*(\d{2})-(\d{2})-(\d{4})", re.I)


def parse_fscpd_html(html: str) -> list[PriceObservation]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    m = DATE_RE.search(text) or re.search(r"Date\s*(\d{2})-(\d{2})-(\d{4})", text)
    if not m:
        raise ProviderError("FS&CPD page format changed: notified-rate date not found")
    dd, mm, yyyy = (int(x) for x in m.groups())
    observed = datetime(yyyy, mm, dd, 0, 0)
    table = soup.find("table", id="dataTable") or soup.find("table")
    if table is None:
        raise ProviderError("FS&CPD page format changed: price table not found")
    headers = [th.get_text(" ", strip=True) for th in table.find_all("th")]
    try:
        col = next(i for i, h in enumerate(headers) if RICE_COLUMN.search(h))
        div_col, dist_col = headers.index("Division"), headers.index("District")
    except (StopIteration, ValueError) as e:
        raise ProviderError("FS&CPD page format changed: rice column not found") from e
    out: list[PriceObservation] = []
    for tr in table.find("tbody").find_all("tr") if table.find("tbody") else []:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) <= col:
            continue
        try:
            price = float(cells[col].replace(",", ""))
        except ValueError:
            continue
        if price <= 0:
            continue  # 0 = not reported
        district = cells[dist_col]
        out.append(PriceObservation(
            product_key="rice_basmati_new_notified", product_name="Rice Basmati New (notified retail rate)",
            product_type="rice", variety="Basmati (new crop)", grade="Not specified by source",
            market=f"{district} District (notified rate)", city=district, province="Punjab", country="Pakistan",
            price=price, currency="PKR", unit="PKR/kg", price_category="retail", observed_at=observed,
            source_name="Punjab FS&CPD - Notified Rates", source_url=URL,
            verification_status=VerificationStatus.verified_source, data_nature=DataNature.live,
            notes=f"Division: {cells[div_col]}. Government notified rate (date only, no time published)."))
    return out


class FSCPDPunjabProvider(MarketDataProvider):
    provider_key = "fscpd_punjab"

    def __init__(self):
        self.limiter = RateLimiter(5.0)

    def get_source_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            provider_key=self.provider_key, name="Punjab FS&CPD - Notified Rates", url=URL, data_nature=DataNature.live,
            description="Daily government notified rates by district. Rice item: 'Rice Basmati New' (PKR/kg).",
            price_types=["retail (notified)"], update_frequency="daily (date only)",
            access_notes="Public HTML page, no API, robots.txt allows access. Read politely; no CAPTCHA/auth bypass.")

    def check_availability(self) -> Availability:
        try:
            r = http_get(URL, limiter=self.limiter)
            return Availability(r.ok, "available" if r.ok else "unavailable", f"HTTP {r.status_code}")
        except ProviderError as e:
            return Availability(False, "unavailable", str(e))

    def fetch_latest_prices(self) -> ProviderResult:
        r = http_get(URL, limiter=self.limiter)
        if not r.ok:
            raise ProviderError(f"HTTP {r.status_code}")
        obs = parse_fscpd_html(r.text)
        return ProviderResult(observations=obs, message=f"{len(obs)} district rates parsed")
