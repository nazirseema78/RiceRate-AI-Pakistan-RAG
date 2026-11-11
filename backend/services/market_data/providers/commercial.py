"""Phase 2 template for a commercial (paid) market data provider.

No paid provider is implemented or claimed in Phase 1. To add one later:
  1. Subclass `CommercialProviderTemplate` (or MarketDataProvider) in a new module.
  2. Map the vendor's documented response fields to `PriceObservation` in `_parse`.
  3. Register it in registry.py and enable it with ENABLED_PROVIDERS + COMMERCIAL_PROVIDER_* variables.
Credentials are read on the backend only (Settings page store or .env) and never sent to the frontend.
"""
from __future__ import annotations

from backend.config import get_settings
from backend.models.price import DataNature, SourceMetadata
from backend.services.provider_settings import get_secret
from backend.services.market_data.base import Availability, MarketDataProvider, ProviderError, ProviderResult


class CommercialProviderTemplate(MarketDataProvider):
    provider_key = "commercial"

    def __init__(self):
        self.settings = get_settings()

    def get_source_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            provider_key=self.provider_key, name=get_secret("commercial_provider_name") or "Commercial provider (not configured)",
            url=get_secret("commercial_provider_base_url"), data_nature=DataNature.live, requires_api_key=True,
            description="Placeholder for a future paid data feed. Disabled in Phase 1.")

    def check_availability(self) -> Availability:
        if not (get_secret("commercial_provider_base_url") and get_secret("commercial_provider_api_key")):
            return Availability(False, "not_configured", "Phase 2: add the commercial provider settings on the Settings page and implement _parse().")
        return Availability(False, "disabled", "Template only - implement a vendor-specific subclass first.")

    def fetch_latest_prices(self) -> ProviderResult:
        raise ProviderError("Commercial provider template is not implemented (Phase 2).")
