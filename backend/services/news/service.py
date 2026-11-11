"""Rice market news and commentary (stored in news_articles; synthetic items are labelled)."""
from __future__ import annotations

from backend.database.db import get_conn, rows


def latest_news(region: str | None = None, limit: int = 20, include_synthetic: bool = True) -> list[dict]:
    clauses, params = [], []
    if region:
        clauses.append("LOWER(region) = LOWER(?)")
        params.append(region)
    if not include_synthetic:
        clauses.append("is_synthetic = 0")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with get_conn() as conn:
        out = rows(conn, f"SELECT * FROM news_articles {where} ORDER BY published_at DESC LIMIT ?", [*params, limit])
    for r in out:
        r["is_synthetic"] = bool(r["is_synthetic"])
    return out
