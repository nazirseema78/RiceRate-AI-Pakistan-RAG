"""Authorised manual CSV import.

Drop CSV files that YOU are allowed to use (e.g. prices copied from a broker WhatsApp list, a
newspaper rate list you have rights to, or a source without permitted automated access) into
data/imports/. Use data/samples/price_import_template.csv as the column template.
Rows are labelled data_nature=imported and keep the source name you provide.
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from backend.config import get_settings
from backend.models.price import DataNature, PriceObservation, SourceMetadata, VerificationStatus
from backend.services.market_data.base import Availability, MarketDataProvider, ProviderResult

log = logging.getLogger(__name__)
REQUIRED = {"product_key", "product_name", "product_type", "variety", "market", "city", "country", "price",
            "currency", "unit", "price_category", "observed_at", "source_name"}
PLACEHOLDER_SOURCES = {"", "replace with your authorised source"}


class CSVImportProvider(MarketDataProvider):
    provider_key = "csv_import"

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory or get_settings().imports_dir)

    def get_source_metadata(self) -> SourceMetadata:
        return SourceMetadata(
            provider_key=self.provider_key, name="Authorised CSV Import", url="", data_nature=DataNature.imported,
            description="Manually supplied CSV files in data/imports (for sources without permitted automated access).",
            price_types=["wholesale", "retail", "export", "broker_quotation"], update_frequency="whenever files are added",
            access_notes="Only import data you are authorised to use. Rows keep the source name supplied in the file.")

    def _files(self) -> list[Path]:
        return sorted(self.directory.glob("*.csv")) if self.directory.exists() else []

    def check_availability(self) -> Availability:
        files = self._files()
        return Availability(True, "available" if files else "not_configured",
                            f"{len(files)} CSV file(s) in {self.directory.name}/" if files else "no CSV files to import")

    def fetch_latest_prices(self) -> ProviderResult:
        res = ProviderResult()
        bad = 0
        for f in self._files():
            with f.open(encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                missing = REQUIRED - set(reader.fieldnames or [])
                if missing:
                    log.warning("CSV %s missing columns %s - skipped", f.name, sorted(missing))
                    bad += 1
                    continue
                for r in reader:
                    if r["source_name"].strip().lower() in PLACEHOLDER_SOURCES:
                        bad += 1
                        continue
                    try:
                        status = r.get("verification_status") or "unverified"
                        res.observations.append(PriceObservation(
                            product_key=r["product_key"], product_name=r["product_name"], product_type=r["product_type"],
                            variety=r["variety"], grade=r.get("grade", ""), market=r["market"], city=r["city"],
                            province=r.get("province", ""), country=r["country"], price=float(r["price"]),
                            currency=r["currency"], unit=r["unit"], price_category=r["price_category"],
                            observed_at=datetime.fromisoformat(r["observed_at"]), source_name=r["source_name"],
                            source_url=r.get("source_url", ""), source_document=f.name,
                            verification_status=VerificationStatus(status), data_nature=DataNature.imported))
                    except (ValueError, KeyError) as e:
                        bad += 1
                        log.warning("CSV %s row rejected: %s", f.name, e)
        res.message = f"{len(res.observations)} rows parsed, {bad} rows/files skipped"
        return res
