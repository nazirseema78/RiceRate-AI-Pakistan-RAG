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
