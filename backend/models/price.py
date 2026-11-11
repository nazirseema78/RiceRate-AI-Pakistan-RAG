"""Domain models shared by connectors, ingestion and analytics."""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ProductType(str, Enum):
    paddy = "paddy"
    rice = "rice"
    broken_rice = "broken_rice"


class PriceCategory(str, Enum):
    wholesale = "wholesale"
    retail = "retail"
    export = "export"
    broker_quotation = "broker_quotation"


class DataNature(str, Enum):
    synthetic = "synthetic"      # fictional demonstration data
    live = "live"                # retrieved from a verified source during this deployment
    historical = "historical"    # verified historical/periodic publication (e.g. monthly averages)
    imported = "imported"        # authorised manual CSV import


class VerificationStatus(str, Enum):
    synthetic_demo = "synthetic_demo"
    verified_source = "verified_source"      # published by an official / documented source
    unverified = "unverified"                # imported, not independently verified
    broker_reported = "broker_reported"


class PriceObservation(BaseModel):
    """One price observation as returned by a MarketDataProvider (before validation/normalisation)."""

    product_key: str = Field(min_length=2, max_length=80)
    product_name: str
    product_type: ProductType
    variety: str
    grade: str = ""
    market: str
    city: str
    province: str = ""
    country: str = "Pakistan"
    price: float
    currency: str
    unit: str
    price_category: PriceCategory
    observed_at: datetime
    source_name: str
    source_url: str = ""
    source_document: str = ""
    verification_status: VerificationStatus
    data_nature: DataNature
    notes: str = ""

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @property
    def is_synthetic(self) -> bool:
        return self.data_nature == DataNature.synthetic


class SourceMetadata(BaseModel):
    provider_key: str
    name: str
    url: str = ""
    data_nature: DataNature
    description: str = ""
    requires_api_key: bool = False
    price_types: list[str] = []
    update_frequency: str = ""
    access_notes: str = ""
