from datetime import date

from backend.services.analytics import prices as pa


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["price_observations"] > 0 and body["vector_chunks"] > 0


def test_products_and_markets(client):
    assert client.get("/api/products").json()["count"] >= 10
    cities = {m["city"] for m in client.get("/api/markets").json()["items"]}
    assert {"Multan", "Muzaffargarh", "Bahawalpur", "Rahim Yar Khan", "Karachi"} <= cities


def test_latest_prices_have_source_timestamp_and_label(client):
    r = client.get("/api/prices/latest", params={"city": "Multan", "product_type": "paddy"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert items
    for it in items:
        assert it["source_name"] and it["observed_at"] and it["retrieved_at"]
        assert it["is_synthetic"] is True and it["data_label"] == "SYNTHETIC DEMO DATA"
        assert it["verification_status"] == "synthetic_demo"


def test_latest_is_never_labelled_today_when_old(seeded):
    # synthetic data ends on 2026-11-10; viewed on 2026-11-12 it must be 2 days old, not "today"
    items = pa.latest_prices(city="Multan", product_key="paddy_1121_basmati", ref=date(2026, 11, 12))
    assert items and all(not i["is_today"] and i["age_days"] == 2 for i in items)
    assert "not today's rate" in items[0]["freshness_label"]


def test_missing_latest_day_keeps_original_timestamp(seeded):
    # Rahim Yar Khan paddy is deliberately not reported on the last synthetic day
    items = pa.latest_prices(city="Rahim Yar Khan", product_type="paddy")
    assert items and all(i["observation_date"] < "2026-11-10" for i in items)


def test_exclude_synthetic_filter(client):
    items = client.get("/api/prices/latest", params={"include_synthetic": "false"}).json()["items"]
    assert all(not i["is_synthetic"] for i in items)


def test_input_validation(client):
    assert client.get("/api/prices/latest", params={"product_type": "gold"}).status_code == 422
    assert client.get("/api/prices/history", params={"days": 99999}).status_code == 422
    assert client.post("/api/chat", json={"question": ""}).status_code == 422


def test_sql_injection_is_inert(client):
    r = client.get("/api/prices/latest", params={"city": "Multan' OR '1'='1"})
    assert r.status_code == 200 and r.json()["count"] == 0


def test_history_query(client):
    items = client.get("/api/prices/history", params={"product_key": "rice_1121_sella", "city": "Karachi", "days": 30}).json()["items"]
    dates = [i["price_date"] for i in items]
    assert len(items) >= 20 and dates == sorted(dates)
    assert all(i["original_unit"] == "PKR/kg" for i in items)


def test_compare_only_equivalent_products(client):
    body = client.get("/api/prices/compare").json()
    assert body["comparisons"]
    for c in body["comparisons"]:
        assert c["city"] != "Karachi" and c["normalized_unit"] == "PKR/kg"
        if c["valid"]:
            assert round(c["karachi_normalized"] - c["city_normalized"], 2) == c["difference"]
            assert abs(c["difference_pct"] - c["difference"] / c["city_normalized"] * 100) < 0.01
    # paddy has no Karachi equivalent -> must be listed as unmatched, never compared
    assert all(c["product_type"] != "paddy" for c in body["comparisons"])
    assert any("Paddy" in u["product_name"] for u in body["unmatched"])


def test_changes_and_direction_labels(client):
    items = client.get("/api/prices/changes").json()["items"]
    sella = next(i for i in items if i["product_key"] == "rice_1121_sella" and i["city"] == "Karachi")
    assert sella["direction_7d"] in {"Rising", "Falling", "Stable"}
    labels = {d["direction"] for d in client.get("/api/prices/direction").json()["items"]}
    assert labels <= {"Rising", "Falling", "Stable", "Mixed", "Insufficient Data"}


def test_direction_helpers():
    assert pa.direction_label(None) == "Insufficient Data"
    assert pa.direction_label(2.0) == "Rising" and pa.direction_label(-2.0) == "Falling" and pa.direction_label(0.5) == "Stable"
    assert pa.aggregate_direction(["Rising", "Falling"]) == "Mixed"
    assert pa.aggregate_direction(["Insufficient Data"]) == "Insufficient Data"


def test_quotations_validity(client):
    items = client.get("/api/karachi/quotations").json()["items"]
    assert items and all(i["status"] in ("Valid", "Expired") for i in items)
    valid = client.get("/api/karachi/quotations", params={"valid_only": "true"}).json()["items"]
    assert all(i["is_valid"] for i in valid)


def test_international_and_news(client):
    intl = client.get("/api/international/prices").json()
    assert intl["items"] and all(i["price_category"] == "export" and i["currency"] == "USD" for i in intl["items"])
    assert "not equivalent" in intl["disclaimer"]
    assert client.get("/api/news/latest", params={"region": "International"}).json()["count"] > 0


def test_briefing_has_warnings_and_no_forecast(client):
    b = client.get("/api/market/briefing").json()
    assert b["contains_synthetic"] and any("SYNTHETIC" in w for w in b["warnings"])
    assert "does not predict" in b["text"]
    assert all(word not in b["text"].lower() for word in ("will definitely", "guaranteed"))


def test_sources_status(client):
    body = client.get("/api/sources/status").json()
    assert any(s["provider_key"] == "synthetic_demo" for s in body["sources"])
    assert body["recent_runs"]


def test_admin_refresh_requires_token_and_is_rate_limited(client):
    assert client.post("/api/admin/refresh").status_code == 401
    assert client.post("/api/admin/refresh", headers={"X-Admin-Token": "wrong"}).status_code == 401
    ok = client.post("/api/admin/refresh", headers={"X-Admin-Token": "test-admin-token"}, json={})
    assert ok.status_code == 200, ok.text
    again = client.post("/api/admin/refresh", headers={"X-Admin-Token": "test-admin-token"}, json={})
    assert again.status_code == 429
