"""Sources that were investigated but have no permitted/working automated access in Phase 1.

They appear on the Data Source Status page for transparency and never return prices.
Use the CSV import (data/imports) for data you are authorised to copy from them.
"""
from __future__ import annotations

from backend.models.price import DataNature, SourceMetadata
from backend.services.market_data.base import Availability, MarketDataProvider, ProviderResult

# Findings recorded on 2026-11-11 (see docs/DATA_SOURCES.md)
DOCUMENTED = {
    "amis_pk": ("AMIS Punjab (amis.pk)", "https://www.amis.pk/",
                "Did not respond (connection timeout) during verification. Its Punjab mandi data is available through the PakDataHub connector."),
    "pfsis": ("Pakistan Food Security Information System", "https://pfsis.fsp.gov.pk/",
              "Did not respond (connection timeout) during verification. No API documentation found."),
    "par_rice": ("Pakistan Agriculture Research - rice page", "https://www.par.com.pk/commodities/rice",
                 "JavaScript-only page with copy/right-click disabled and no published API or data licence. "
                 "Not scraped; use authorised CSV import."),
}


class DocumentedOnlyProvider(MarketDataProvider):
    def __init__(self, key: str):
        self.provider_key = key
        self.name, self.url, self.reason = DOCUMENTED[key]

    def get_source_metadata(self) -> SourceMetadata:
        return SourceMetadata(provider_key=self.provider_key, name=self.name, url=self.url, data_nature=DataNature.live,
                              description="Investigated source - no automated connector in Phase 1.", access_notes=self.reason)

    def check_availability(self) -> Availability:
        return Availability(False, "disabled", self.reason)

    def fetch_latest_prices(self) -> ProviderResult:
        return ProviderResult(message="no automated access - not collected")
