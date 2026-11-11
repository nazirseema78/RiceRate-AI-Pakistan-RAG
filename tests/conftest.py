"""Test configuration: isolated temp database + vector store, offline hash embeddings, no network providers."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="ricerate_test_"))
os.environ.update({
    "DATABASE_PATH": str(_TMP / "test.db"),
    "CHROMA_PATH": str(_TMP / "chroma"),
    "SCHEDULER_LOCK_PATH": str(_TMP / "scheduler.lock"),
    "IMPORTS_DIR": str(_TMP / "imports"),
    "EMBEDDING_BACKEND": "hash",
    "ENABLED_PROVIDERS": "synthetic_demo,csv_import",
    "SCHEDULER_ENABLED": "false",
    "ADMIN_TOKEN": "test-admin-token",
    "REFRESH_MIN_INTERVAL_SECONDS": "120",
    "LLM_PROVIDER": "none",
    "PAKDATAHUB_API_KEY": "",
})

from backend.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session")
def seeded():
    """Load the synthetic dataset and build the vector index once per test session."""
    from backend.database.db import init_db
    from backend.services.market_data.ingestion import run_provider
    from backend.services.market_data.providers.synthetic import SyntheticDemoProvider
    from backend.services.rag.vectorstore import build_index

    synthetic = ROOT / "data" / "synthetic" / "synthetic_market_prices.csv"
    if not synthetic.exists():
        pytest.skip("synthetic data missing - run scripts/generate_synthetic_data.py")
    init_db()
    result = run_provider(SyntheticDemoProvider(), trigger="test")
    index = build_index()
    return {"ingestion": result, "index": index}


@pytest.fixture(scope="session")
def client(seeded):
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        yield c
