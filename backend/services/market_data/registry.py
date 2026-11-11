"""Configuration-based provider selection."""
from __future__ import annotations

from backend.config import get_settings
from backend.services.market_data.base import MarketDataProvider
from backend.services.market_data.providers.commercial import CommercialProviderTemplate
from backend.services.market_data.providers.csv_import import CSVImportProvider
from backend.services.market_data.providers.documented_only import DOCUMENTED, DocumentedOnlyProvider
from backend.services.market_data.providers.fscpd_punjab import FSCPDPunjabProvider
from backend.services.market_data.providers.pakdatahub import PakDataHubProvider
from backend.services.market_data.providers.synthetic import SyntheticDemoProvider
from backend.services.market_data.providers.worldbank_pinksheet import WorldBankPinkSheetProvider

FACTORIES = {
    "synthetic_demo": SyntheticDemoProvider,
    "csv_import": CSVImportProvider,
    "fscpd_punjab": FSCPDPunjabProvider,
    "pakdatahub": PakDataHubProvider,
    "worldbank_pinksheet": WorldBankPinkSheetProvider,
    "commercial": CommercialProviderTemplate,
}


def enabled_providers() -> list[MarketDataProvider]:
    return [FACTORIES[k]() for k in get_settings().enabled_provider_list if k in FACTORIES]


def all_known_providers() -> list[MarketDataProvider]:
    """Enabled providers first, then disabled/documented ones (for the status page)."""
    enabled = enabled_providers()
    keys = {p.provider_key for p in enabled}
    rest: list[MarketDataProvider] = [f() for k, f in FACTORIES.items() if k not in keys]
    rest += [DocumentedOnlyProvider(k) for k in DOCUMENTED]
    return enabled + rest
