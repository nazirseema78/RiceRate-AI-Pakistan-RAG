"""Daily rice market briefing built ONLY from stored observations and news (no invented numbers)."""
from __future__ import annotations

from backend.services.analytics.prices import (latest_news, latest_prices, market_direction_summary, price_changes,
                                               today_pkt)

KEY_DOMESTIC = ["paddy_1121_basmati", "paddy_super_basmati", "paddy_irri6", "rice_1121_sella", "rice_irri6_15",
                "broken_irri6_100", "rice_basmati_new_notified", "pdh_paddy_basmati", "pdh_paddy_irri"]


def _fmt(r: dict) -> str:
    return (f"{r['product_name']} ({r['grade']}) in {r['city']}: {r['price']:,.0f} {r['original_unit']} "
            f"[{r['price_category']}, observed {r['observation_date']}, {r['data_label']}, source: {r['source_name']}]")


def build_briefing(include_synthetic: bool = True) -> dict:
    ref = today_pkt()
    latest = latest_prices(include_synthetic=include_synthetic)
    lp = [r for r in latest if r["region"] == "Lower Punjab" and r["product_key"] in KEY_DOMESTIC]
    kc = [r for r in latest if r["city"] == "Karachi" and r["price_category"] != "broker_quotation"]
    intl = [r for r in latest if r["region"] == "International"]
    multan_first = sorted(lp, key=lambda r: (r["city"] != "Multan", r["city"], r["product_name"]))
    changes = [c for c in price_changes(windows=(7,)) if include_synthetic or not c["is_synthetic"]]
    directions = [d for d in market_direction_summary(7) if include_synthetic or not d["is_synthetic"]]
    news = latest_news(limit=5, include_synthetic=include_synthetic)

    newest = max((r["observation_date"] for r in latest), default=None)
    warnings = []
    if not latest:
        warnings.append("No price observations are stored yet. No briefing figures can be given.")
    if newest and newest < ref.isoformat():
        warnings.append(f"No price observation dated today ({ref.isoformat()}). The newest available observation is from "
                        f"{newest}; figures below are the latest available, NOT today's rates.")
    stale = sorted({f"{r['city']} - {r['product_name']}" for r in lp + kc if r["is_stale"]})
    if stale:
        warnings.append(f"{len(stale)} domestic series are stale (older than 2 days), e.g. {', '.join(stale[:3])}.")
    if any(r["is_synthetic"] for r in latest):
        warnings.append("This briefing includes SYNTHETIC DEMONSTRATION DATA. Synthetic figures are fictional and must not be used for trading.")

    def moves(region_filter):
        sel = [c for c in changes if region_filter(c) and c["change_7d_pct"] is not None]
        sel.sort(key=lambda c: abs(c["change_7d_pct"]), reverse=True)
        return [f"{c['product_name']} in {c['city']}: {c['change_7d_pct']:+.2f}% over 7 days "
                f"({c['direction_7d']}, latest {c['latest_price']:,.0f} {c['unit']} on {c['latest_date']}"
                f"{', SYNTHETIC' if c['is_synthetic'] else ''})" for c in sel[:4]]

    sections = {
        "lower_punjab": [_fmt(r) for r in multan_first[:8]] or ["No Lower Punjab observations available."],
        "karachi": [_fmt(r) for r in kc[:6]] or ["No Karachi observations available."],
        "international": [_fmt(r) for r in sorted(intl, key=lambda r: r["observation_date"], reverse=True)[:6]]
                         or ["No international observations available."],
        "price_direction": moves(lambda c: c["region"] in ("Lower Punjab", "Karachi")) + moves(lambda c: c["region"] == "International")
                           or ["Insufficient data to describe recent price direction."],
        "direction_labels": [f"{d['product_name']}: {d['direction']} (7-day, {d['series_count']} market series)" for d in directions],
        "news": [f"{n['published_at'][:10]} - {n['title']} ({n['source_name']})" for n in news] or ["No news items stored."],
    }
    sources = sorted({r["source_name"] for r in latest} | {n["source_name"] for n in news})
    text = ["RiceRate AI Pakistan - Daily Rice Market Briefing", f"Prepared: {ref.isoformat()} (PKT)", ""]
    if warnings:
        text += ["DATA FRESHNESS WARNINGS:"] + [f"! {w}" for w in warnings] + [""]
    titles = {"lower_punjab": "Lower Punjab (latest available)", "karachi": "Karachi (latest available)",
              "international": "International", "price_direction": "Recent price direction (observed, not a forecast)",
              "direction_labels": "Market direction indicators", "news": "Important rice news"}
    for k, t in titles.items():
        text += [t + ":"] + [f"- {x}" for x in sections[k]] + [""]
    text += ["This briefing reports observed data only. It does not predict future prices.",
             "Sources: " + "; ".join(sources)]
    return {"date": ref.isoformat(), "newest_observation_date": newest, "warnings": warnings, "sections": sections,
            "sources": sources, "text": "\n".join(text), "contains_synthetic": any(r["is_synthetic"] for r in latest)}
