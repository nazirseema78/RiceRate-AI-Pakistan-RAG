"""FastAPI application entry point.

Run from the project root:
    uvicorn backend.main:app --reload --port 8000
API docs: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.config import get_settings
from backend.database.db import get_conn, init_db

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ricerate")


def bootstrap(build_vectors: bool = True) -> None:
    """Create tables, seed demo data on first start and make sure the vector index exists."""
    from backend.services.market_data.ingestion import run_all
    from backend.services.rag.vectorstore import ensure_index

    init_db()
    with get_conn() as conn:
        empty = conn.execute("SELECT COUNT(*) AS n FROM ingestion_runs").fetchone()["n"] == 0
    if empty:
        log.info("First start: running initial source check")
        run_all(trigger="startup")
    if build_vectors:
        try:
            ensure_index()
        except Exception:
            log.exception("Vector index build failed - chatbot document retrieval unavailable until fixed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from backend.scheduler.scheduler import start_scheduler, stop_scheduler

    init_db()
    # heavy work (first source check, embedding model download) runs in the background so the API starts quickly
    threading.Thread(target=bootstrap, daemon=True, name="bootstrap").start()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="RiceRate AI Pakistan API", version="1.0.0", lifespan=lifespan,
              description="Rice price intelligence for Lower Punjab, Karachi and international markets. "
                          "Free-first: synthetic demo data + verified free sources. Synthetic data is always labelled.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-Admin-Token"])
app.include_router(router)


@app.get("/")
def root():
    return {"app": settings.app_name, "docs": "/docs", "health": "/api/health"}
