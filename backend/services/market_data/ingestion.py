"""Ingestion: fetch -> validate -> normalise -> de-duplicate -> store -> log run -> update freshness."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.database.db import get_conn, get_or_create
from backend.models.price import PriceObservation
from backend.services.market_data.base import MarketDataProvider, ProviderError
from backend.services.market_data.registry import all_known_providers, enabled_providers
from backend.services.market_data.units import UnitError, normalize_price
from backend.services.market_data.validation import to_pkt, validate_observation

log = logging.getLogger(__name__)
PKT = ZoneInfo("Asia/Karachi")
LOWER_PUNJAB = {"Multan", "Muzaffargarh", "Bahawalpur", "Rahim Yar Khan", "Lodhran", "Khanewal", "Vehari",
                "Bahawalnagar", "D.G Khan", "DG Khan", "Dera Ghazi Khan", "Layyah", "Rajanpur", "MuzafarGhar"}


def now_pkt() -> datetime:
    return datetime.now(PKT).replace(microsecond=0)


def region_for(city: str, country: str) -> str:
    if country != "Pakistan":
        return "International"
    if city == "Karachi":
        return "Karachi"
    return "Lower Punjab" if city in LOWER_PUNJAB else "Pakistan (other)"


def dedup_hash(o: PriceObservation, observed_iso: str) -> str:
    raw = "|".join([o.product_key, o.market, o.city, o.country, o.price_category.value, observed_iso,
                    f"{o.price:.4f}", o.unit, o.source_name])
    return hashlib.sha256(raw.encode()).hexdigest()


def register_source(conn, provider: MarketDataProvider) -> int:
    md = provider.get_source_metadata()
    sid = get_or_create(conn, "price_sources", {"provider_key": md.provider_key},
                        {"name": md.name, "url": md.url, "data_nature": md.data_nature.value,
                         "description": md.description, "requires_api_key": int(md.requires_api_key)})
    conn.execute("UPDATE price_sources SET name=?, url=?, data_nature=?, description=?, requires_api_key=? WHERE id=?",
                 (md.name, md.url, md.data_nature.value, md.description, int(md.requires_api_key), sid))
    return sid


def store_observations(conn, source_id: int, observations: list[PriceObservation]) -> dict:
    stats = {"fetched": len(observations), "inserted": 0, "duplicates": 0, "rejected": 0, "reasons": {}}
    retrieved = now_pkt().isoformat()
    latest_obs: str | None = None
    for o in sorted(observations, key=lambda x: to_pkt(x.observed_at)):
        v = validate_observation(o)
        if not v:
            stats["rejected"] += 1
            stats["reasons"][v.reason] = stats["reasons"].get(v.reason, 0) + 1
            continue
        observed_iso = to_pkt(o.observed_at).replace(microsecond=0).isoformat()
        h = dedup_hash(o, observed_iso)
        if conn.execute("SELECT 1 FROM market_prices WHERE dedup_hash = ?", (h,)).fetchone():
            stats["duplicates"] += 1
            continue
        pid = get_or_create(conn, "products", {"product_key": o.product_key},
                            {"name": o.product_name, "product_type": o.product_type.value, "variety": o.variety, "grade": o.grade})
        mid = get_or_create(conn, "markets", {"name": o.market, "city": o.city, "country": o.country},
                            {"province": o.province, "region": region_for(o.city, o.country)})
        cur = conn.execute(
            """INSERT OR IGNORE INTO market_prices (product_id, market_id, source_id, price, currency, original_unit,
                   normalized_price, normalized_unit, price_category, observed_at, retrieved_at, source_name, source_url,
                   source_document, verification_status, data_nature, is_synthetic, notes, dedup_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, mid, source_id, o.price, o.currency, v.unit, v.normalized_price, v.normalized_unit,
             o.price_category.value, observed_iso, retrieved, o.source_name, o.source_url, o.source_document,
             o.verification_status.value, o.data_nature.value, int(o.is_synthetic), o.notes, h))
        if cur.rowcount == 0:  # another worker inserted the same observation concurrently
            stats["duplicates"] += 1
            continue
        conn.execute(
            """INSERT INTO historical_prices (product_id, market_id, source_id, price_category, price_date, price, currency,
                   original_unit, normalized_price, normalized_unit, is_synthetic)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT (product_id, market_id, source_id, price_category, price_date) DO UPDATE SET
                   price=excluded.price, normalized_price=excluded.normalized_price, original_unit=excluded.original_unit""",
            (pid, mid, source_id, o.price_category.value, observed_iso[:10], o.price, o.currency, v.unit,
             v.normalized_price, v.normalized_unit, int(o.is_synthetic)))
        stats["inserted"] += 1
        latest_obs = max(latest_obs or observed_iso, observed_iso)
    stats["latest_observation"] = latest_obs
    return stats


def store_quotations(conn, quotations: list[dict]) -> int:
    n = 0
    for q in quotations:
        try:
            norm, norm_unit = normalize_price(float(q["price"]), q["unit"])
        except (UnitError, ValueError, KeyError):
            continue
        if float(q["price"]) <= 0:
            continue
        pid = get_or_create(conn, "products", {"product_key": q["product_key"]},
                            {"name": q["product_name"], "product_type": q.get("product_type", "rice"),
                             "variety": q.get("variety", ""), "grade": q.get("grade", "")})
        mid = get_or_create(conn, "markets", {"name": "Karachi Buyer Quotations", "city": q.get("city", "Karachi"), "country": "Pakistan"},
                            {"province": "Sindh", "region": "Karachi"})
        cur = conn.execute(
            """INSERT OR IGNORE INTO broker_quotations (quotation_ref, product_id, market_id, buyer, price, currency, unit,
                   normalized_price, normalized_unit, quantity_mt, delivery_terms, quoted_at, valid_until, source_name,
                   source_document, verification_status, is_synthetic) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (q["quotation_id"], pid, mid, q["buyer"], float(q["price"]), q["currency"], q["unit"], norm, norm_unit,
             q.get("quantity_mt"), q.get("delivery_terms", ""), to_pkt(datetime.fromisoformat(q["quoted_at"])).isoformat(),
             q["valid_until"], q["source_name"], q.get("source_document", ""), q["verification_status"], int(q["is_synthetic"])))
        n += cur.rowcount
    return n


def store_news(conn, news: list[dict]) -> int:
    n = 0
    for a in news:
        cur = conn.execute(
            """INSERT OR IGNORE INTO news_articles (article_ref, title, summary, region, category, published_at, source_name,
                   url, source_document, is_synthetic) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (a["article_id"], a["title"], a["summary"], a["region"], a["category"],
             to_pkt(datetime.fromisoformat(a["published_at"])).isoformat(), a["source_name"], a.get("url", ""),
             a.get("source_document", ""), int(bool(a.get("is_synthetic")))))
        n += cur.rowcount
    return n


def _recent_success(conn, provider: MarketDataProvider) -> bool:
    hours = getattr(provider, "min_hours_between_runs", 0)
    if not hours:
        return False
    r = conn.execute("SELECT last_success_at FROM price_sources WHERE provider_key = ?", (provider.provider_key,)).fetchone()
    if not r or not r["last_success_at"]:
        return False
    return datetime.fromisoformat(r["last_success_at"]) > now_pkt() - timedelta(hours=hours)


def run_provider(provider: MarketDataProvider, trigger: str = "manual", force: bool = False) -> dict:
    started = now_pkt().isoformat()
    with get_conn() as conn:
        sid = register_source(conn, provider)
        conn.execute("UPDATE price_sources SET enabled = 1 WHERE id = ?", (sid,))
        if not force and _recent_success(conn, provider):
            return {"provider": provider.provider_key, "status": "skipped", "message": "fetched recently (quota/politeness window)"}
        avail = provider.check_availability()
        conn.execute("UPDATE price_sources SET last_attempted_at=?, availability_status=? WHERE id=?",
                     (started, avail.status, sid))
        run_id = conn.execute("INSERT INTO ingestion_runs (provider_key, trigger, started_at, status) VALUES (?,?,?,?)",
                              (provider.provider_key, trigger, started, "running")).lastrowid
    if not avail.available:
        result = {"provider": provider.provider_key, "status": avail.status, "message": avail.detail,
                  "fetched": 0, "inserted": 0, "duplicates": 0, "rejected": 0}
        _finish(run_id, sid, result, success=False, error=avail.detail)
        return result
    try:
        res = provider.fetch_latest_prices()
    except (ProviderError, Exception) as e:  # a failing connector must never produce fabricated prices
        log.exception("provider %s failed", provider.provider_key)
        result = {"provider": provider.provider_key, "status": "failed", "message": str(e)[:500],
                  "fetched": 0, "inserted": 0, "duplicates": 0, "rejected": 0}
        _finish(run_id, sid, result, success=False, error=str(e)[:500])
        return result
    with get_conn() as conn:
        stats = store_observations(conn, sid, res.observations)
        q = store_quotations(conn, res.quotations)
        n = store_news(conn, res.news)
    reasons = "; ".join(f"{k} x{v}" for k, v in stats["reasons"].items())
    result = {"provider": provider.provider_key, "status": "success",
              "message": f"{res.message}. quotations+{q}, news+{n}" + (f". rejected: {reasons}" if reasons else ""),
              **{k: stats[k] for k in ("fetched", "inserted", "duplicates", "rejected")},
              "latest_observation": stats["latest_observation"]}
    _finish(run_id, sid, result, success=True)
    return result


def _finish(run_id: int, source_id: int, result: dict, success: bool, error: str = "") -> None:
    fin = now_pkt().isoformat()
    with get_conn() as conn:
        conn.execute("""UPDATE ingestion_runs SET finished_at=?, status=?, fetched=?, inserted=?, duplicates=?, rejected=?,
                        message=? WHERE id=?""",
                     (fin, result["status"], result.get("fetched", 0), result.get("inserted", 0),
                      result.get("duplicates", 0), result.get("rejected", 0), result.get("message", "")[:1000], run_id))
        if success:
            conn.execute("""UPDATE price_sources SET last_success_at=?, availability_status='available', last_error=NULL,
                            last_observation_at = COALESCE(
                              (SELECT MAX(observed_at) FROM market_prices WHERE source_id = ?), last_observation_at)
                            WHERE id=?""", (fin, source_id, source_id))
        else:
            conn.execute("UPDATE price_sources SET last_error=? WHERE id=?", (error[:500], source_id))


def run_all(trigger: str = "scheduled", force: bool = False) -> list[dict]:
    results = [run_provider(p, trigger, force) for p in enabled_providers()]
    # make sure disabled/documented sources are visible on the status page
    with get_conn() as conn:
        enabled_keys = {r["provider"] for r in results}
        for p in all_known_providers():
            if p.provider_key in enabled_keys:
                continue
            sid = register_source(conn, p)
            a = p.check_availability() if p.provider_key not in ("fscpd_punjab", "worldbank_pinksheet") else None
            conn.execute("UPDATE price_sources SET enabled = 0, availability_status = ?, last_error = ? WHERE id = ?",
                         (a.status if a else "disabled", (a.detail if a else "disabled in ENABLED_PROVIDERS"), sid))
    return results
