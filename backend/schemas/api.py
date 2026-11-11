"""Pydantic request / response schemas for the REST API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    app: str
    database: str
    price_observations: int
    vector_chunks: int
    embedding_model: str
    llm_provider: str
    scheduler: dict[str, Any]
    time_pkt: str


class PriceRecord(BaseModel):
    product_key: str
    product_name: str
    product_type: str
    variety: str
    grade: str
    market: str
    city: str
    province: str = ""
    country: str
    region: str
    price: float
    currency: str
    original_unit: str
    normalized_price: float
    normalized_unit: str
    price_category: str
    observed_at: str
    retrieved_at: str
    observation_date: str
    age_days: int
    is_today: bool
    is_stale: bool
    freshness_label: str
    source_name: str
    source_url: str = ""
    source_document: str = ""
    provider_key: str
    verification_status: str
    data_nature: str
    is_synthetic: bool
    data_label: str
    notes: str = ""


class PriceListResponse(BaseModel):
    count: int
    items: list[PriceRecord]
    disclaimer: str


class GenericListResponse(BaseModel):
    count: int
    items: list[dict[str, Any]]
    disclaimer: str = ""


class CompareResponse(BaseModel):
    comparisons: list[dict[str, Any]]
    unmatched: list[dict[str, Any]]
    method: str
    disclaimer: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=6000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)


class ChatResponse(BaseModel):
    answer: str
    language: str
    route: str
    intents: list[str]
    entities: dict[str, Any]
    facts: list[str]
    sources: list[dict[str, Any]]
    retrieved_chunks: list[dict[str, Any]]
    used_llm: bool
    warnings: list[str]
    contains_synthetic: bool


class BriefingResponse(BaseModel):
    date: str
    newest_observation_date: str | None
    warnings: list[str]
    sections: dict[str, list[str]]
    sources: list[str]
    text: str
    contains_synthetic: bool


class RefreshRequest(BaseModel):
    force: bool = False
    rebuild_index: bool = False


class RefreshResponse(BaseModel):
    status: str
    results: list[dict[str, Any]]
    index: dict[str, Any] | None = None
