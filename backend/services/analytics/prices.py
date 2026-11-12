"""Structured (SQL) price analytics. Exact numbers always come from here, never from an LLM."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from backend.database.db import get_conn, rows
from backend.services.news.service import latest_news  # noqa: F401  (re-exported)

PKT = ZoneInfo("Asia/Karachi")
LOWER_PUNJAB_COMPARE = ["Multan", "Muzaffargarh", "Bahawalpur", "Rahim Yar Khan"]
THRESHOLD_PCT = 1.5  # default; the live value comes from Settings -> Pricing accuracy


def _acc(name: str):
    from backend.services.provider_settings import accuracy_value

    return accuracy_value(name)

_BASE = """
SELECT mp.id, mp.price, mp.currency, mp.original_unit, mp.normalized_price, mp.normalized_unit, mp.price_category,
       mp.observed_at, mp.retrieved_at, mp.source_name, mp.source_url, mp.source_document, mp.verification_status,
       mp.data_nature, mp.is_synthetic, mp.notes,
       p.product_key, p.name AS product_name, p.product_type, p.variety, p.grade,
       m.name AS market, m.city, m.province, m.country, m.region, s.provider_key
FROM market_prices mp
JOIN products p ON p.id = mp.product_id
JOIN markets m ON m.id = mp.market_id
JOIN price_sources s ON s.id = mp.source_id
"""


def today_pkt() -> date:
    return datetime.now(PKT).date()


def _filters(f: dict, prefix: str = "mp", nature_col: str = "mp.data_nature") -> tuple[str, list]:
    """Build a parameterised WHERE fragment. `prefix` is the alias of the price table (mp or hp)."""
    clauses, params = [], []
    mapping = {"city": "m.city", "product_type": "p.product_type", "variety": "p.variety", "grade": "p.grade",
               "price_category": f"{prefix}.price_category", "region": "m.region", "country": "m.country",
               "provider_key": "s.provider_key", "product_key": "p.product_key", "data_nature": nature_col}
    for k, col in mapping.items():
        v = f.get(k)
        if v:
            clauses.append(f"LOWER({col}) = LOWER(?)")
            params.append(v)
    if f.get("include_synthetic") is False:
        clauses.append(f"{prefix}.is_synthetic = 0")
    if f.get("only_synthetic"):
        clauses.append(f"{prefix}.is_synthetic = 1")
    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def freshness(observed_at: str, data_nature: str, ref: date | None = None) -> dict:
    ref = ref or today_pkt()
    d = datetime.fromisoformat(observed_at).date()
    age = (ref - d).days
    stale_after = _acc("stale_after_days_periodic") if data_nature == "historical" else _acc("stale_after_days_daily")
    if age <= 0:
        label = "Observed today"
    elif age == 1:
        label = "1 day old (not today's rate)"
    else:
        label = f"{age} days old (not today's rate)"
    return {"observation_date": d.isoformat(), "age_days": age, "is_today": age <= 0,
            "is_stale": age > stale_after, "freshness_label": label}


def _decorate(r: dict, ref: date | None = None) -> dict:
    r["is_synthetic"] = bool(r["is_synthetic"])
    r["data_label"] = "SYNTHETIC DEMO DATA" if r["is_synthetic"] else r["data_nature"].upper()
    r.update(freshness(r["observed_at"], r["data_nature"], ref))
    return r


def latest_prices(as_of: date | None = None, ref: date | None = None, **f) -> list[dict]:
    where, params = _filters(f)
    cutoff = (as_of or date(9999, 1, 1)).isoformat() + "T23:59:59+05:00"
    sql = _BASE + f"""
    WHERE mp.id IN (
        SELECT id FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY product_id, market_id, source_id, price_category
                                          ORDER BY observed_at DESC, id DESC) AS rn
            FROM market_prices WHERE observed_at <= ?) WHERE rn = 1) {where}
    ORDER BY m.region, m.city, p.product_type, p.name"""
    with get_conn() as conn:
        return [_decorate(r, ref) for r in rows(conn, sql, [cutoff, *params])]


def price_history(days: int = 30, end: date | None = None, **f) -> list[dict]:
    where, params = _filters(f, prefix="hp", nature_col="s.data_nature")
    with get_conn() as conn:
        last = conn.execute("SELECT MAX(price_date) AS d FROM historical_prices").fetchone()["d"]
        if not last:
            return []
        end = end or date.fromisoformat(last)
        start = end - timedelta(days=days)
        sql = f"""
        SELECT hp.price_date, hp.price, hp.currency, hp.original_unit, hp.normalized_price, hp.normalized_unit,
               hp.price_category, hp.is_synthetic, p.product_key, p.name AS product_name, p.product_type, p.variety, p.grade,
               m.name AS market, m.city, m.region, m.country, s.provider_key, s.name AS source_name
        FROM historical_prices hp JOIN products p ON p.id = hp.product_id JOIN markets m ON m.id = hp.market_id
        JOIN price_sources s ON s.id = hp.source_id
        WHERE hp.price_date BETWEEN ? AND ? {where} ORDER BY p.name, m.city, hp.price_date"""
        out = rows(conn, sql, [start.isoformat(), end.isoformat(), *params])
    for r in out:
        r["is_synthetic"] = bool(r["is_synthetic"])
    return out


def compare_markets(cities: list[str] | None = None, as_of: date | None = None, max_gap_days: int = 3, **f) -> dict:
    cities = cities or LOWER_PUNJAB_COMPARE
    f = {k: v for k, v in f.items() if k != "city"}
    latest = latest_prices(as_of=as_of, **f)
    karachi = {}
    for r in latest:
        if r["city"] == "Karachi" and r["price_category"] != "broker_quotation":
            karachi[(r["product_key"], r["price_category"], r["normalized_unit"], r["is_synthetic"])] = r
    comparisons, unmatched = [], []
    for r in latest:
        if r["city"] not in cities:
            continue
        key = (r["product_key"], r["price_category"], r["normalized_unit"], r["is_synthetic"])
        k = karachi.get(key)
        if not k:
            unmatched.append({"city": r["city"], "product_name": r["product_name"], "grade": r["grade"],
                              "reason": "No equivalent Karachi observation (same product, grade, price category and unit basis)"})
            continue
        gap = abs((date.fromisoformat(k["observation_date"]) - date.fromisoformat(r["observation_date"])).days)
        diff = round(k["normalized_price"] - r["normalized_price"], 2)
        pct = round(diff / r["normalized_price"] * 100, 2)
        valid = gap <= max_gap_days
        comparisons.append({
            "product_key": r["product_key"], "product_name": r["product_name"], "product_type": r["product_type"],
            "variety": r["variety"], "grade": r["grade"], "price_category": r["price_category"],
            "city": r["city"], "city_price": r["price"], "city_unit": r["original_unit"],
            "city_normalized": r["normalized_price"], "city_date": r["observation_date"],
            "karachi_price": k["price"], "karachi_unit": k["original_unit"], "karachi_normalized": k["normalized_price"],
            "karachi_date": k["observation_date"], "normalized_unit": r["normalized_unit"],
            "difference": diff if valid else None, "difference_pct": pct if valid else None,
            "date_gap_days": gap, "valid": valid,
            "note": ("Same observation date" if gap == 0 else f"Observation dates differ by {gap} day(s)") if valid
                    else f"Not compared: observation dates differ by {gap} days (> {max_gap_days})",
            "is_synthetic": r["is_synthetic"], "sources": sorted({r["source_name"], k["source_name"]}),
        })
    return {"comparisons": comparisons, "unmatched": unmatched,
            "method": "Karachi price minus Lower Punjab price on the normalised basis (PKR/kg). Only identical product, grade, "
                      "price category and data type are compared; currencies are never mixed."}


def direction_label(pct: float | None) -> str:
    if pct is None:
        return "Insufficient Data"
    threshold = _acc("trend_threshold_pct")
    if pct > threshold:
        return "Rising"
    if pct < -threshold:
        return "Falling"
    return "Stable"


def aggregate_direction(labels: list[str]) -> str:
    known = [l for l in labels if l != "Insufficient Data"]
    if not known:
        return "Insufficient Data"
    up, down, flat = known.count("Rising"), known.count("Falling"), known.count("Stable")
    if up and down:
        return "Mixed"
    if up and up >= flat:
        return "Rising"
    if down and down >= flat:
        return "Falling"
    if up or down:
        return "Mixed"
    return "Stable"


def price_changes(windows: tuple[int, ...] = (7, 15, 30), **f) -> list[dict]:
    """Per-series change over each window using end-of-day history."""
    hist = price_history(days=max(windows) * 2 + 5, **f)
    series: dict[tuple, list[dict]] = {}
    for h in hist:
        series.setdefault((h["product_key"], h["city"], h["market"], h["price_category"], h["provider_key"]), []).append(h)
    out = []
    for (_pk, city, market, cat, prov), pts in series.items():
        pts.sort(key=lambda x: x["price_date"])
        last = pts[-1]
        ld = date.fromisoformat(last["price_date"])
        rec = {"product_key": last["product_key"], "product_name": last["product_name"], "product_type": last["product_type"],
               "variety": last["variety"], "grade": last["grade"], "city": city, "market": market, "region": last["region"],
               "price_category": cat, "latest_price": last["price"], "unit": last["original_unit"],
               "latest_date": last["price_date"], "source_name": last["source_name"], "is_synthetic": last["is_synthetic"]}
        for w in windows:
            base = [p for p in pts if ld - timedelta(days=2 * w) <= date.fromisoformat(p["price_date"]) <= ld - timedelta(days=w)]
            if not base:
                rec[f"change_{w}d"], rec[f"change_{w}d_pct"], rec[f"direction_{w}d"] = None, None, "Insufficient Data"
                rec[f"base_{w}d_date"] = None
                continue
            b = base[-1]
            chg = round(last["normalized_price"] - b["normalized_price"], 4)
            pct = round(chg / b["normalized_price"] * 100, 2)
            rec[f"change_{w}d"] = round(last["price"] - b["price"], 2) if b["original_unit"] == last["original_unit"] else None
            rec[f"change_{w}d_pct"] = pct
            rec[f"direction_{w}d"] = direction_label(pct)
            rec[f"base_{w}d_date"] = b["price_date"]
        out.append(rec)
    return out


def market_direction_summary(window: int = 7, **f) -> list[dict]:
    changes = price_changes(windows=(window,), **f)
    groups: dict[str, list[dict]] = {}
    for c in changes:
        groups.setdefault(c["product_name"], []).append(c)
    out = []
    for name, cs in sorted(groups.items()):
        labels = [c[f"direction_{window}d"] for c in cs]
        out.append({"product_name": name, "window_days": window, "direction": aggregate_direction(labels),
                    "series_count": len(cs), "rising": labels.count("Rising"), "falling": labels.count("Falling"),
                    "stable": labels.count("Stable"), "insufficient": labels.count("Insufficient Data"),
                    "is_synthetic": all(c["is_synthetic"] for c in cs)})
    return out


def broker_quotations(valid_only: bool = False, ref: date | None = None, include_synthetic: bool = True,
                      product_type: str | None = None, limit: int = 100) -> list[dict]:
    ref = ref or today_pkt()
    clauses, params = [], []
    if valid_only:
        clauses.append("bq.valid_until >= ?")
        params.append(ref.isoformat())
    if not include_synthetic:
        clauses.append("bq.is_synthetic = 0")
    if product_type:
        clauses.append("p.product_type = ?")
        params.append(product_type)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""SELECT bq.quotation_ref, bq.buyer, bq.price, bq.currency, bq.unit, bq.normalized_price, bq.normalized_unit,
                     bq.quantity_mt, bq.delivery_terms, bq.quoted_at, bq.valid_until, bq.source_name, bq.source_document,
                     bq.verification_status, bq.is_synthetic, p.name AS product_name, p.product_type, p.variety, p.grade,
                     m.city
              FROM broker_quotations bq JOIN products p ON p.id = bq.product_id JOIN markets m ON m.id = bq.market_id
              {where} ORDER BY bq.quoted_at DESC LIMIT ?"""
    with get_conn() as conn:
        out = rows(conn, sql, [*params, limit])
    for r in out:
        r["is_synthetic"] = bool(r["is_synthetic"])
        r["is_valid"] = r["valid_until"] >= ref.isoformat()
        r["status"] = "Valid" if r["is_valid"] else "Expired"
    return out


def list_products() -> list[dict]:
    with get_conn() as conn:
        return rows(conn, "SELECT product_key, name, product_type, variety, grade FROM products ORDER BY product_type, name")


def list_markets() -> list[dict]:
    with get_conn() as conn:
        return rows(conn, "SELECT name, city, province, country, region FROM markets ORDER BY region, city")


def sources_status() -> dict:
    with get_conn() as conn:
        srcs = rows(conn, """SELECT s.*, (SELECT COUNT(*) FROM market_prices mp WHERE mp.source_id = s.id) AS observation_count
                             FROM price_sources s ORDER BY s.enabled DESC, s.name""")
        runs = rows(conn, "SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT 30")
    for s in srcs:
        s["enabled"] = bool(s["enabled"])
        s["requires_api_key"] = bool(s["requires_api_key"])
    return {"sources": srcs, "recent_runs": runs}
