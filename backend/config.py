"""Environment-based configuration (values come from .env or the process environment)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "RiceRate AI Pakistan"
    environment: str = "development"
    log_level: str = "INFO"
    timezone: str = "Asia/Karachi"

    # storage
    database_path: Path = PROJECT_ROOT / "storage" / "ricerate.db"
    chroma_path: Path = PROJECT_ROOT / "storage" / "chroma_db"
    chroma_collection: str = "rice_market_documents"
    documents_dir: Path = PROJECT_ROOT / "data" / "documents"
    synthetic_dir: Path = PROJECT_ROOT / "data" / "synthetic"
    imports_dir: Path = PROJECT_ROOT / "data" / "imports"
    # AI-model providers + data-source keys added on the Settings page (git-ignored, backend only)
    provider_settings_path: Path = PROJECT_ROOT / "storage" / "provider_settings.json"

    # API / security
    cors_origins: str = "http://localhost:8501,http://127.0.0.1:8501"
    admin_token: str = ""  # empty = admin endpoints disabled
    refresh_min_interval_seconds: int = 120

    # providers (comma separated names, see backend/services/market_data/registry.py)
    enabled_providers: str = "synthetic_demo,csv_import,fscpd_punjab,worldbank_pinksheet,pakdatahub"
    load_synthetic_demo_data: bool = True
    pakdatahub_api_key: str = ""
    pakdatahub_base_url: str = "https://api.pakdatahub.com"
    pakdatahub_max_calls_per_run: int = 9
    worldbank_pinksheet_url: str = ("https://thedocs.worldbank.org/en/doc/74e8be41ceb20fa0da750cda2f6b9e4e-0050012026/"
                                    "related/CMO-Historical-Data-Monthly.xlsx")
    commercial_provider_name: str = ""
    commercial_provider_base_url: str = ""
    commercial_provider_api_key: str = ""
    http_timeout_seconds: float = 20.0
    http_max_retries: int = 2
    http_user_agent: str = "RiceRateAI-Pakistan/1.0 (educational price-intelligence project)"

    # scheduler
    scheduler_enabled: bool = True
    scheduler_hours: str = "9,12,15,18"  # Pakistan Standard Time
    scheduler_lock_path: Path = PROJECT_ROOT / "storage" / "scheduler.lock"

    # RAG
    embedding_backend: str = "sentence_transformers"  # sentence_transformers | hash (offline/test)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    chunk_size: int = 700
    chunk_overlap: int = 120
    retrieval_k: int = 5

    # optional LLM (any OpenAI-compatible endpoint, e.g. a local Ollama server). Empty = retrieval-only answers.
    llm_provider: str = "none"  # none | openai_compatible
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_model: str = "llama3.2"
    llm_timeout_seconds: float = 60.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def enabled_provider_list(self) -> list[str]:
        return [p.strip() for p in self.enabled_providers.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
