"""Connector tests use recorded/mock payloads - no network access."""
from datetime import datetime

import pytest

from backend.database.db import get_conn
from backend.models.price import PriceObservation
from backend.services.market_data.base import Availability, MarketDataProvider, ProviderError, ProviderResult
from backend.services.market_data.ingestion import run_provider
from backend.services.market_data.providers.commercial import CommercialProviderTemplate
from backend.services.market_data.providers.csv_import import CSVImportProvider
from backend.services.market_data.providers.fscpd_punjab import parse_fscpd_html
from backend.services.market_data.providers.pakdatahub import PakDataHubProvider, parse_pakdatahub_rows

FSCPD_HTML = """<html><body><p>Date 10-11-2026</p><h3>Notified Rates 10-11-2026</h3>
<table id="dataTable"><thead><tr><th>Sr#</th><th>Division</th><th>District</th><th>Atta Bag (20Kg)</th>
<th>Rice Basmati New (Kg)</th><th>Sugar(kg)</th></tr></thead><tbody>
<tr><td>1</td><td>Multan</td><td>Multan</td><td>1810</td><td>342</td><td>135</td></tr>
<tr><td>2</td><td>Bahawalpur</td><td>Rahim Yar Khan</td><td>1810</td><td>280</td><td>135</td></tr>
<tr><td>3</td><td>Faisalabad</td><td>Faisalabad</td><td>1810</td><td>0</td><td>135</td></tr>
</tbody></table></body></html>"""


def test_fscpd_parser_reads_rice_column_and_skips_zero():
    obs = parse_fscpd_html(FSCPD_HTML)
    assert [(o.city, o.price) for o in obs] == [("Multan", 342.0), ("Rahim Yar Khan", 280.0)]
    o = obs[0]
    assert o.price_category.value == "retail" and o.unit == "PKR/kg" and o.data_nature.value == "live"
    assert o.observed_at == datetime(2026, 11, 10) and o.source_url.startswith("https://fscpdpunjab.gop.pk")


def test_fscpd_parser_fails_loudly_on_format_change():
    with pytest.raises(ProviderError):
        parse_fscpd_html("<html><body>Notified Rates 10-11-2026<table><tr><th>Other</th></tr></table></body></html>")


def test_pakdatahub_parser_and_missing_prices():
    payload = {"success": True, "count": 3, "data": [
        {"date": "2026-11-10", "market": "Multan", "market_slug": "multan", "fqp": 9800, "unit": "pkr_per_100kg",
         "province": "Punjab", "min": 9500, "max": 10000, "quantity": 120},
        {"date": "2026-11-10", "market": "Bahawalpur", "market_slug": "bahawalpur", "fqp": None, "unit": "pkr_per_100kg"},
        {"date": "2026-11-10", "market": "Gujrat", "market_slug": "gujrat", "fqp": 9000, "unit": "pkr_per_100kg"},
    ]}
    obs = parse_pakdatahub_rows("paddy_basmati", payload)
    assert len(obs) == 1 and obs[0].city == "Multan" and obs[0].unit == "PKR/100kg" and obs[0].price == 9800
    with pytest.raises(ProviderError):
        parse_pakdatahub_rows("paddy_basmati", {"success": False, "error": {"code": "unauthorized"}})


def test_pakdatahub_disabled_without_key():
    a = PakDataHubProvider().check_availability()
    assert not a.available and a.status == "not_configured"


def test_commercial_provider_is_disabled_placeholder():
    p = CommercialProviderTemplate()
    assert not p.check_availability().available
    with pytest.raises(ProviderError):
        p.fetch_latest_prices()


class FailingProvider(MarketDataProvider):
    provider_key = "failing_test"

    def get_source_metadata(self):
        from backend.models.price import SourceMetadata
        return SourceMetadata(provider_key=self.provider_key, name="Failing test source", data_nature="live")

    def check_availability(self):
        return Availability(True, "available")

    def fetch_latest_prices(self):
        raise ProviderError("simulated timeout")


def test_failed_provider_stores_no_prices_and_logs_error(seeded):
    with get_conn() as conn:
        before = conn.execute("SELECT COUNT(*) n FROM market_prices").fetchone()["n"]
    res = run_provider(FailingProvider(), trigger="test")
    assert res["status"] == "failed" and res["inserted"] == 0
    with get_conn() as conn:
        after = conn.execute("SELECT COUNT(*) n FROM market_prices").fetchone()["n"]
        src = conn.execute("SELECT last_error, last_success_at FROM price_sources WHERE provider_key='failing_test'").fetchone()
        run = conn.execute("SELECT status FROM ingestion_runs WHERE provider_key='failing_test' ORDER BY id DESC").fetchone()
    assert before == after
    assert "simulated timeout" in src["last_error"] and src["last_success_at"] is None
    assert run["status"] == "failed"


class StaticProvider(MarketDataProvider):
    provider_key = "static_test"

    def __init__(self, observations):
        self.observations = observations

    def get_source_metadata(self):
        from backend.models.price import SourceMetadata
        return SourceMetadata(provider_key=self.provider_key, name="Static test source", data_nature="live")

    def check_availability(self):
        return Availability(True, "available")

    def fetch_latest_prices(self):
        return ProviderResult(observations=self.observations)


def _obs(price, day=9):
    return PriceObservation(product_key="test_rice", product_name="Test Rice", product_type="rice", variety="Test",
                            grade="G", market="Test Market", city="Testabad", country="Pakistan", price=price,
                            currency="PKR", unit="PKR/kg", price_category="wholesale",
                            observed_at=datetime(2026, 11, day, 10), source_name="Static test source",
                            verification_status="verified_source", data_nature="live")


def test_duplicates_detected_and_invalid_rejected(seeded):
    p = StaticProvider([_obs(200), _obs(200), _obs(-1)])
    r1 = run_provider(p, trigger="test")
    assert r1["inserted"] == 1 and r1["duplicates"] == 1 and r1["rejected"] == 1
    r2 = run_provider(p, trigger="test")
    assert r2["inserted"] == 0 and r2["duplicates"] == 2


def test_csv_import_skips_placeholder_rows(tmp_path):
    f = tmp_path / "prices.csv"
    f.write_text("product_key,product_name,product_type,variety,grade,market,city,province,country,price,currency,unit,"
                 "price_category,observed_at,source_name\n"
                 "x_rice,X Rice,rice,X,G,M,Multan,Punjab,Pakistan,250,PKR,PKR/kg,wholesale,2026-11-10T10:00:00,REPLACE WITH YOUR AUTHORISED SOURCE\n"
                 "x_rice,X Rice,rice,X,G,M,Multan,Punjab,Pakistan,250,PKR,PKR/kg,wholesale,2026-11-10T10:00:00,Broker list (authorised)\n",
                 encoding="utf-8")
    res = CSVImportProvider(tmp_path).fetch_latest_prices()
    assert len(res.observations) == 1
    o = res.observations[0]
    assert o.data_nature.value == "imported" and o.verification_status.value == "unverified" and o.source_document == "prices.csv"
