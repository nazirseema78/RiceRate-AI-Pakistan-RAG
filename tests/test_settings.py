"""Admin settings: AI-model providers (free/paid, fallback order) and data-source keys. No network: requests is mocked."""
from __future__ import annotations

import json

import pytest

from backend.config import get_settings
from backend.services import provider_settings as ps
from backend.services.rag import llm

ADMIN = {"X-Admin-Token": "test-admin-token"}
SECRET = "sk-test-SECRET-value-1234"


@pytest.fixture(autouse=True)
def clean_store():
    path = get_settings().provider_settings_path
    path.unlink(missing_ok=True)
    yield
    path.unlink(missing_ok=True)


class FakeResp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code, self._payload, self.text = status, payload, text or json.dumps(payload)
        self.ok = status < 400

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _add(client, **over):
    body = {"name": "Groq", "preset": "groq", "tier": "free", "base_url": "https://api.groq.com/openai/v1",
            "model": "test-model", "api_key": SECRET, "priority": 10, **over}
    r = client.post("/api/admin/llm/providers", json=body, headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_admin_settings_require_token(client):
    assert client.get("/api/admin/settings").status_code == 401
    assert client.get("/api/admin/settings", headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert client.post("/api/admin/llm/providers", json={}).status_code in (401, 422)
    r = client.get("/api/admin/settings", headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert {"ollama", "groq", "openai", "anthropic", "custom"} <= {p["preset"] for p in body["presets"]}
    assert {p["tier"] for p in body["presets"]} == {"free", "paid"}


def test_api_key_is_never_returned(client):
    created = _add(client)
    assert created["api_key_set"] is True and created["api_key_masked"].endswith("1234")
    for r in (client.get("/api/admin/settings", headers=ADMIN), client.get("/api/llm/status"), client.get("/api/health")):
        assert SECRET not in r.text
    # but it is stored on the backend for use
    assert ps.get_llm_provider(created["id"], include_secrets=True)["api_key"] == SECRET


def test_update_keeps_or_removes_key(client):
    pid = _add(client)["id"]
    r = client.put(f"/api/admin/llm/providers/{pid}", json={"model": "other-model", "priority": 3}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["model"] == "other-model" and r.json()["api_key_set"] is True
    r = client.put(f"/api/admin/llm/providers/{pid}", json={"api_key": ""}, headers=ADMIN)
    assert r.json()["api_key_set"] is False
    assert client.put("/api/admin/llm/providers/nope", json={"priority": 1}, headers=ADMIN).status_code == 404


def test_validation_rejects_bad_values(client):
    bad_url = client.post("/api/admin/llm/providers", headers=ADMIN, json={
        "name": "x", "tier": "free", "base_url": "file:///etc/passwd", "model": "m"})
    assert bad_url.status_code == 422
    bad_tier = client.post("/api/admin/llm/providers", headers=ADMIN, json={
        "name": "x", "tier": "expensive", "base_url": "https://example.org/v1", "model": "m"})
    assert bad_tier.status_code == 422


def test_delete(client):
    pid = _add(client)["id"]
    assert client.delete(f"/api/admin/llm/providers/{pid}", headers=ADMIN).status_code == 200
    assert client.delete(f"/api/admin/llm/providers/{pid}", headers=ADMIN).status_code == 404
    assert ps.list_llm_providers() == []


def test_chain_order_and_disabled_providers(client):
    _add(client, name="Paid backup", tier="paid", priority=50)
    _add(client, name="Free first", priority=5)
    _add(client, name="Switched off", priority=1, enabled=False)
    names = [p["name"] for p in ps.active_llm_chain()]
    assert names == ["Free first", "Paid backup"]
    assert client.get("/api/llm/status").json()["enabled"] is True


def test_fallback_to_next_provider(client, monkeypatch):
    _add(client, name="Broken", base_url="https://broken.example/v1", priority=1)
    _add(client, name="Working", base_url="https://working.example/v1", priority=2)
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        if "broken" in url:
            return FakeResp(503, text="unavailable")
        return FakeResp(200, {"choices": [{"message": {"content": "answer text"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    text, used = llm.generate("q", "facts", "ctx", "en")
    assert text == "answer text" and used.startswith("Working")
    assert calls[0].startswith("https://broken.example")


def test_all_providers_fail_returns_none(client, monkeypatch):
    _add(client)
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(401, text=f"bad key {SECRET}"))
    assert llm.generate("q", "f", "c", "en") == (None, None)


def test_test_endpoint_redacts_key(client, monkeypatch):
    pid = _add(client)["id"]
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(401, text=f"invalid key {SECRET}"))
    r = client.post(f"/api/admin/llm/providers/{pid}/test", headers=ADMIN).json()
    assert r["ok"] is False and SECRET not in r["message"]
    assert ps.get_llm_provider(pid)["last_test_ok"] is False


def test_list_models(client, monkeypatch):
    pid = _add(client)["id"]
    monkeypatch.setattr(llm.requests, "get",
                        lambda url, **kw: FakeResp(200, {"data": [{"id": "model-b"}, {"id": "model-a"}]}))
    r = client.post("/api/admin/llm/models", json={"provider_id": pid}, headers=ADMIN)
    assert r.json()["models"] == ["model-a", "model-b"]
    r = client.post("/api/admin/llm/models", json={"base_url": "https://x.example/v1"}, headers=ADMIN)
    assert r.status_code == 200


def test_chat_works_without_any_llm(client):
    r = client.post("/api/chat", json={"question": "Multan 1121 paddy latest rate"}).json()
    assert r["used_llm"] is False and r["llm_provider_used"] is None


def test_data_source_keys(client):
    r = client.put("/api/admin/data-source-keys", headers=ADMIN, json={"values": {"pakdatahub_api_key": SECRET}})
    assert r.status_code == 200 and SECRET not in r.text
    assert ps.get_secret("pakdatahub_api_key") == SECRET
    from backend.services.market_data.providers.pakdatahub import PakDataHubProvider

    assert PakDataHubProvider().check_availability().available is True
    client.put("/api/admin/data-source-keys", headers=ADMIN, json={"values": {"pakdatahub_api_key": ""}})
    assert PakDataHubProvider().check_availability().available is False
    bad = client.put("/api/admin/data-source-keys", headers=ADMIN, json={"values": {"unknown_key": "x"}})
    assert bad.status_code == 422


def test_compare_models(client, monkeypatch):
    good = _add(client, name="Good", base_url="https://good.example/v1", enabled=False)["id"]
    bad = _add(client, name="Bad", base_url="https://bad.example/v1")["id"]

    def fake_post(url, **kw):
        if "bad" in url:
            return FakeResp(500, text="boom")
        return FakeResp(200, {"choices": [{"message": {"content": "Model answer without numbers."}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    r = client.post("/api/admin/llm/compare", headers=ADMIN, json={"question": "Multan 1121 paddy latest rate",
                                                                   "provider_ids": [good, bad]})
    assert r.status_code == 200
    res = {x["label"].split(" - ")[0]: x for x in r.json()["results"]}
    assert res["Retrieval only (no AI model)"]["used_llm"] is False
    assert res["Good"]["used_llm"] is True and res["Good"]["answer"].startswith("Model answer")  # disabled models can be compared
    assert res["Bad"]["used_llm"] is False and "failed" in res["Bad"]["note"]
    assert client.post("/api/admin/llm/compare", json={"question": "x y"}).status_code == 401


# ------------------------------------------------------------------ recommended fallback plan
def test_recommended_plan_free_first_paid_last_all_off(client):
    r = client.post("/api/admin/llm/recommended-plan", headers=ADMIN).json()
    provs = r["providers"]
    assert len(provs) == len(ps.RECOMMENDED_PLAN) and all(not p["enabled"] for p in provs)
    tiers = [p["tier"] for p in provs]  # sorted by priority
    assert tiers.index("paid") > max(i for i, t in enumerate(tiers) if t == "free")
    again = client.post("/api/admin/llm/recommended-plan", headers=ADMIN).json()
    assert again["added"] == []  # never duplicates


def test_one_key_enables_all_models_of_that_provider(client):
    client.post("/api/admin/llm/recommended-plan", headers=ADMIN)
    r = client.put("/api/admin/llm/provider-key", headers=ADMIN, json={"preset": "groq", "api_key": SECRET})
    assert r.status_code == 200 and r.json()["updated"] == 2 and SECRET not in r.text
    names = [p["name"] for p in ps.active_llm_chain()]
    assert names == ["Groq GPT-OSS 120B", "Groq Qwen 3.8 27B"]
    status = client.get("/api/llm/status").json()["fallback_plan"]
    assert status[-1]["name"].startswith("Retrieval-only")


def test_cooldown_skips_failed_model(client, monkeypatch):
    llm.reset_cooldowns()
    _add(client, name="Flaky", base_url="https://flaky.example/v1", priority=1)
    _add(client, name="Steady", base_url="https://steady.example/v1", priority=2)
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        if "flaky" in url:
            return FakeResp(429, text="rate limited")
        return FakeResp(200, {"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    assert llm.generate("q", "f", "c", "en")[1].startswith("Steady")
    calls.clear()
    assert llm.generate("q", "f", "c", "en")[1].startswith("Steady")
    assert not any("flaky" in c for c in calls)  # skipped during cooldown
    llm.reset_cooldowns()


def test_request_options_follow_the_preset(client, monkeypatch):
    sent = {}
    monkeypatch.setattr(llm.requests, "post",
                        lambda url, json=None, **kw: sent.setdefault(url, json) and FakeResp(200, {"choices": [{"message": {"content": "x"}}]})
                        or FakeResp(200, {"choices": [{"message": {"content": "x"}}]}))
    claude = ps.get_llm_provider(_add(client, preset="anthropic", tier="paid", base_url="https://api.anthropic.com/v1",
                                      model="claude-haiku-5-5")["id"], include_secrets=True)
    gpt = ps.get_llm_provider(_add(client, preset="openai", tier="paid", base_url="https://api.openai.com/v1",
                                   model="gpt-6-luna")["id"], include_secrets=True)
    llm.chat_completion(claude, [{"role": "user", "content": "hi"}])
    llm.chat_completion(gpt, [{"role": "user", "content": "hi"}])
    body_c = sent["https://api.anthropic.com/v1/chat/completions"]
    body_o = sent["https://api.openai.com/v1/chat/completions"]
    assert "temperature" not in body_c and "temperature" not in body_o
    assert "max_completion_tokens" in body_o and "max_tokens" not in body_o
    groq = ps.get_llm_provider(_add(client)["id"], include_secrets=True)
    assert groq["temperature"] == 0.1


# ------------------------------------------------------------------ pricing accuracy
def test_accuracy_settings_validate_and_apply(client):
    from backend.services.analytics import prices as pa

    assert pa.direction_label(2.0) == "Rising"
    r = client.put("/api/admin/accuracy", headers=ADMIN, json={"values": {"trend_threshold_pct": 3}})
    assert r.status_code == 200
    assert pa.direction_label(2.0) == "Stable"
    bad = client.put("/api/admin/accuracy", headers=ADMIN, json={"values": {"trend_threshold_pct": 999}})
    assert bad.status_code == 422
    crossed = client.put("/api/admin/accuracy", headers=ADMIN, json={"values": {"min_price_pkr_per_kg": 5000, "max_price_pkr_per_kg": 4000}})
    assert crossed.status_code == 422
    client.put("/api/admin/accuracy", headers=ADMIN, json={"values": {"trend_threshold_pct": None}})
    assert pa.direction_label(2.0) == "Rising"
    assert client.get("/api/admin/accuracy").status_code == 401


def test_price_bounds_and_spike_filter(client):
    from datetime import datetime, timedelta

    from backend.database.db import get_conn
    from backend.models.price import PriceObservation
    from backend.services.market_data.ingestion import store_observations
    from backend.services.market_data.validation import validate_observation

    base = dict(product_key="spike_test_rice", product_name="Spike test rice", product_type="rice", market="Test Mandi",
                city="Multan", country="Pakistan", province="Punjab", price_category="wholesale", currency="PKR",
                unit="PKR/kg", source_name="test", data_nature="synthetic", verification_status="synthetic_demo", variety="Test")
    t0 = datetime.now() - timedelta(days=3)
    obs = lambda price, d: PriceObservation(**base, price=price, observed_at=t0 + timedelta(days=d))  # noqa: E731
    ps.set_accuracy({"max_price_pkr_per_kg": 250})
    assert not validate_observation(obs(300, 0))
    ps.set_accuracy({"max_price_pkr_per_kg": None, "max_jump_pct": 25})
    with get_conn() as conn:
        sid = conn.execute("SELECT id FROM price_sources LIMIT 1").fetchone()["id"]
        stats = store_observations(conn, sid, [obs(200, 0), obs(210, 1), obs(400, 2)])
    assert stats["inserted"] == 2 and stats["rejected"] == 1
    assert any("suspicious jump" in k for k in stats["reasons"])
    ps.set_accuracy({"max_jump_pct": None})


# ------------------------------------------------------------------ answer pipeline
def _ok(text):
    return FakeResp(200, {"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})


def test_empty_answer_falls_through_to_next_model(client, monkeypatch):
    llm.reset_cooldowns()
    _add(client, name="Thinker", base_url="https://thinker.example/v1", priority=1)
    _add(client, name="Answerer", base_url="https://answerer.example/v1", priority=2)
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(
        200, {"choices": [{"message": {"content": None}, "finish_reason": "length"}]}) if "thinker" in url else _ok("fine"))
    r = llm.generate_detailed("q", "f", "c", "en")
    assert r["text"] == "fine" and r["model"].startswith("Answerer")
    assert r["attempts"][0]["ok"] is False and "empty answer" in r["attempts"][0]["detail"]
    llm.reset_cooldowns()


def test_rate_limit_is_retried_once(client, monkeypatch):
    llm.reset_cooldowns()
    _add(client, name="Busy", base_url="https://busy.example/v1")
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        return FakeResp(429, text="slow down") if len(calls) == 1 else _ok("after retry")

    monkeypatch.setattr(llm.requests, "post", fake_post)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    assert llm.generate("q", "f", "c", "en")[0] == "after retry" and len(calls) == 2


def test_chat_uses_llm_and_reports_model_and_attempts(client, monkeypatch):
    llm.reset_cooldowns()
    _add(client, name="Down", base_url="https://down.example/v1", priority=1)
    _add(client, name="Up", base_url="https://up.example/v1", model="good-model", priority=2)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(503, text="overloaded") if "down" in url
                        else _ok("Multan mein latest available rate neeche facts mein hai."))
    r = client.post("/api/chat", json={"question": "Aaj Multan mein 1121 paddy ka latest available rate kya hai?"}).json()
    assert r["used_llm"] is True and r["llm_provider_used"] == "Up (good-model)"
    assert [a["ok"] for a in r["llm_attempts"]] == [False, True]
    assert "no LLM configured" not in r["answer"]
    llm.reset_cooldowns()


def test_llm_answer_with_invented_price_is_rejected(client, monkeypatch):
    llm.reset_cooldowns()
    _add(client)
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: _ok("Multan 1121 paddy rate is 9,999 PKR/40kg today."))
    r = client.post("/api/chat", json={"question": "Multan 1121 paddy latest rate"}).json()
    assert r["used_llm"] is False and "9,999" not in r["answer"] and any("discarded" in w for w in r["warnings"])


def test_all_models_failing_says_so(client, monkeypatch):
    llm.reset_cooldowns()
    _add(client)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: FakeResp(503, text="down"))
    r = client.post("/api/chat", json={"question": "Multan 1121 paddy latest rate"}).json()
    assert r["used_llm"] is False and "every configured AI model failed" in r["answer"]
    llm.reset_cooldowns()


def test_followup_question_inherits_context(client):
    hist = [{"role": "user", "content": "Aaj Multan mein 1121 paddy ka latest available rate kya hai?"},
            {"role": "assistant", "content": "..."}]
    r = client.post("/api/chat", json={"question": "aur Bahawalpur mein?", "history": hist}).json()
    assert r["route"] == "structured" and r["entities"]["product_type"] == "paddy"
    assert r["entities"]["cities"] == ["Bahawalpur"] and r["followup_of"]
    assert any("Bahawalpur" in f for f in r["facts"])
    alone = client.post("/api/chat", json={"question": "aur Bahawalpur mein?"}).json()
    assert alone["followup_of"] is None


def test_history_notes_are_not_sent_back_to_the_model():
    text = "Rate is 4,790 PKR/40kg.\n\n> Note: yeh SYNTHETIC DEMO DATA hai\n_(Retrieval-only answer)_"
    assert llm._clean_history(text) == "Rate is 4,790 PKR/40kg."


def test_reply_language_follows_the_users_script():
    assert "Roman Urdu" in llm.reply_language("Multan mein rate kya hai?", "ur")
    assert "Urdu script" in llm.reply_language("ملتان میں ریٹ کیا ہے؟", "ur")
    assert llm.reply_language("What is the rate?", "en") == "English"


def test_new_topic_is_not_treated_as_followup(client):
    hist = [{"role": "user", "content": "Pichlay 7 din mein 1121 rice ka rate barha hai ya kam hua?"}]
    r = client.post("/api/chat", json={"question": "Why are rice prices changing in Karachi?", "history": hist}).json()
    assert r["followup_of"] is None
    r2 = client.post("/api/chat", json={"question": "what about Bahawalpur?", "history": hist}).json()
    assert r2["followup_of"] and r2["entities"]["variety"] == "1121"


def test_numbers_from_the_question_are_allowed(client, monkeypatch):
    llm.reset_cooldowns()
    _add(client)
    monkeypatch.setattr(llm.requests, "post", lambda url, **kw: _ok("No price for 386 broken rice in Lahore is in the data, so it is not available."))
    r = client.post("/api/chat", json={"question": "What is the price of 386 broken rice in Lahore today?"}).json()
    assert r["used_llm"] is True and "not available" in r["answer"]
    llm.reset_cooldowns()
