"""Admin-managed provider settings: AI model (LLM) providers and data-source API keys.

* Stored on the BACKEND only, in ``storage/provider_settings.json`` (git-ignored, like ``.env``).
* API keys are write-only: every function that returns data to the API masks them.
* Values in this file take precedence over ``.env``; ``.env`` remains a fallback.

LLM providers are tried in ``priority`` order (lowest number first). If one fails or times out the next one is used,
and if none works the chatbot falls back to its retrieval-only answer.
"""
from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.config import get_settings

PKT = ZoneInfo("Asia/Karachi")
_lock = threading.RLock()

# ---------------------------------------------------------------------------------------------------------------
# Catalogue of ready-made templates. Every entry speaks the OpenAI-compatible chat API (POST {base_url}/chat/completions).
# `model_hint` is only a starting suggestion: model names change often, so use "List models" in the Settings page
# (GET {base_url}/models) to pick one the provider currently offers, and "Test" to verify the connection.
# Free-tier limits and terms are set by each provider and can change - check them before relying on a service.
# ---------------------------------------------------------------------------------------------------------------
PRESETS: list[dict] = [
    {"preset": "ollama", "name": "Ollama (local, on this PC)", "tier": "free", "base_url": "http://localhost:11434/v1",
     "model_hint": "llama3.2", "needs_key": False, "signup_url": "https://ollama.com/download",
     "notes": "Runs on your own computer, no key, no cost. Install Ollama, then run: ollama pull llama3.2"},
    {"preset": "groq", "name": "Groq", "tier": "free", "base_url": "https://api.groq.com/openai/v1",
     "model_hint": "llama-3.1-8b-instant", "needs_key": True, "signup_url": "https://console.groq.com/keys",
     "notes": "Hosted, free tier with rate limits set by Groq."},
    {"preset": "openrouter_free", "name": "OpenRouter (free models)", "tier": "free", "base_url": "https://openrouter.ai/api/v1",
     "model_hint": "choose a model ending in :free", "needs_key": True, "signup_url": "https://openrouter.ai/keys",
     "notes": "Gateway to many models. Model ids ending in ':free' cost nothing (rate-limited); others are paid."},
    {"preset": "gemini", "name": "Google Gemini (AI Studio)", "tier": "free",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model_hint": "use List models",
     "needs_key": True, "signup_url": "https://aistudio.google.com/apikey",
     "notes": "OpenAI-compatible endpoint with a free tier; Google's terms for the free tier apply."},
    {"preset": "openai", "name": "OpenAI", "tier": "paid", "base_url": "https://api.openai.com/v1",
     "model_hint": "use List models", "needs_key": True, "signup_url": "https://platform.openai.com/api-keys",
     "notes": "Paid, billed per token by OpenAI."},
    {"preset": "anthropic", "name": "Anthropic Claude", "tier": "paid", "base_url": "https://api.anthropic.com/v1",
     "model_hint": "use List models", "needs_key": True, "signup_url": "https://console.anthropic.com/settings/keys",
     "notes": "Paid, billed per token. Uses Anthropic's OpenAI-SDK compatibility endpoint."},
    {"preset": "custom", "name": "Custom OpenAI-compatible endpoint", "tier": "free", "base_url": "",
     "model_hint": "", "needs_key": False, "signup_url": "",
     "notes": "Any other server that implements /v1/chat/completions (LM Studio, vLLM, a company gateway...)."},
]

# data-source secrets that can be managed from the Settings page (name -> description)
DATA_SOURCE_KEYS: dict[str, str] = {
    "pakdatahub_api_key": "PakDataHub API key - enables AMIS Punjab wholesale mandi prices (free plan available)",
    "commercial_provider_name": "Phase 2 paid market-data provider: display name",
    "commercial_provider_base_url": "Phase 2 paid market-data provider: API base URL",
    "commercial_provider_api_key": "Phase 2 paid market-data provider: API key",
}
SECRET_FIELDS = {"pakdatahub_api_key", "commercial_provider_api_key"}

URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.IGNORECASE)


def now_iso() -> str:
    return datetime.now(PKT).replace(microsecond=0).isoformat()


def mask(secret: str | None) -> str:
    if not secret:
        return ""
    return "••••" + secret[-4:] if len(secret) > 8 else "••••"


def _path() -> Path:
    return Path(get_settings().provider_settings_path)


def _empty() -> dict:
    return {"version": 1, "llm_providers": [], "data_source_keys": {}}


def load() -> dict:
    with _lock:
        p = _path()
        if not p.exists():
            return _empty()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return _empty()
        data.setdefault("llm_providers", [])
        data.setdefault("data_source_keys", {})
        return data


def save(data: dict) -> None:
    with _lock:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)  # atomic: a crash never leaves a half-written file


# ------------------------------------------------------------------ LLM providers
class SettingsError(ValueError):
    pass


def _validate(p: dict) -> None:
    if not p.get("name", "").strip():
        raise SettingsError("name is required")
    if not URL_RE.match(p.get("base_url", "")):
        raise SettingsError("base_url must start with http:// or https://")
    if not p.get("model", "").strip():
        raise SettingsError("model is required (use 'List models' to see what the provider offers)")
    if p.get("tier") not in ("free", "paid"):
        raise SettingsError("tier must be 'free' or 'paid'")


def public_provider(p: dict) -> dict:
    """Provider as shown to the frontend: the key is replaced by a mask."""
    out = {k: v for k, v in p.items() if k != "api_key"}
    out["api_key_set"] = bool(p.get("api_key"))
    out["api_key_masked"] = mask(p.get("api_key"))
    return out


def list_llm_providers(include_secrets: bool = False) -> list[dict]:
    items = sorted(load()["llm_providers"], key=lambda x: (x.get("priority", 100), x.get("name", "")))
    return items if include_secrets else [public_provider(p) for p in items]


def get_llm_provider(pid: str, include_secrets: bool = False) -> dict:
    for p in load()["llm_providers"]:
        if p["id"] == pid:
            return p if include_secrets else public_provider(p)
    raise KeyError(pid)


def add_llm_provider(values: dict) -> dict:
    with _lock:
        data = load()
        p = {"id": uuid.uuid4().hex[:12], "name": values.get("name", "").strip(), "preset": values.get("preset", "custom"),
             "tier": values.get("tier", "free"), "base_url": values.get("base_url", "").strip().rstrip("/"),
             "model": values.get("model", "").strip(), "api_key": (values.get("api_key") or "").strip(),
             "enabled": bool(values.get("enabled", True)), "priority": int(values.get("priority", 10)),
             "notes": (values.get("notes") or "")[:500], "created_at": now_iso(), "updated_at": now_iso(),
             "last_test_at": None, "last_test_ok": None, "last_test_message": ""}
        _validate(p)
        data["llm_providers"].append(p)
        save(data)
        return public_provider(p)


def update_llm_provider(pid: str, values: dict) -> dict:
    """Partial update. ``api_key`` omitted or None = keep the stored key; "" = remove it."""
    with _lock:
        data = load()
        for p in data["llm_providers"]:
            if p["id"] != pid:
                continue
            for field in ("name", "tier", "base_url", "model", "notes"):
                if values.get(field) is not None:
                    p[field] = str(values[field]).strip()
            p["base_url"] = p["base_url"].rstrip("/")
            if values.get("enabled") is not None:
                p["enabled"] = bool(values["enabled"])
            if values.get("priority") is not None:
                p["priority"] = int(values["priority"])
            if values.get("api_key") is not None:
                p["api_key"] = values["api_key"].strip()
            for field in ("last_test_at", "last_test_ok", "last_test_message"):
                if field in values:
                    p[field] = values[field]
            p["updated_at"] = now_iso()
            _validate(p)
            save(data)
            return public_provider(p)
    raise KeyError(pid)


def delete_llm_provider(pid: str) -> None:
    with _lock:
        data = load()
        before = len(data["llm_providers"])
        data["llm_providers"] = [p for p in data["llm_providers"] if p["id"] != pid]
        if len(data["llm_providers"]) == before:
            raise KeyError(pid)
        save(data)


def env_llm_provider() -> dict | None:
    """The single provider configured the old way in .env (LLM_PROVIDER=openai_compatible), if any."""
    s = get_settings()
    if s.llm_provider != "openai_compatible":
        return None
    return {"id": "env", "name": "From .env (LLM_BASE_URL)", "preset": "custom", "tier": "free", "base_url": s.llm_base_url,
            "model": s.llm_model, "api_key": s.llm_api_key, "enabled": True, "priority": 1000, "notes": "configured in .env"}


def active_llm_chain() -> list[dict]:
    """Enabled providers in the order the chatbot will try them (secrets included - backend use only)."""
    chain = [p for p in list_llm_providers(include_secrets=True) if p.get("enabled")]
    env = env_llm_provider()
    if env:
        chain.append(env)
    return chain


# ------------------------------------------------------------------ data-source keys
def get_secret(name: str) -> str:
    """Settings-page value first, then the .env / environment value."""
    val = load()["data_source_keys"].get(name)
    if val:
        return val
    return str(getattr(get_settings(), name, "") or "")


def data_source_keys_status() -> list[dict]:
    stored = load()["data_source_keys"]
    out = []
    for name, desc in DATA_SOURCE_KEYS.items():
        val = get_secret(name)
        source = "settings page" if stored.get(name) else (".env" if val else "")
        shown = mask(val) if name in SECRET_FIELDS else val
        out.append({"name": name, "description": desc, "is_secret": name in SECRET_FIELDS, "set": bool(val),
                    "value": shown, "source": source})
    return out


def set_data_source_keys(values: dict[str, str | None]) -> list[dict]:
    """``None`` = leave unchanged, ``""`` = remove the stored value (the .env value, if any, applies again)."""
    with _lock:
        data = load()
        for name, val in values.items():
            if name not in DATA_SOURCE_KEYS:
                raise SettingsError(f"unknown setting: {name}")
            if val is None:
                continue
            val = val.strip()
            if name.endswith("_base_url") and val and not URL_RE.match(val):
                raise SettingsError(f"{name} must start with http:// or https://")
            if val:
                data["data_source_keys"][name] = val
            else:
                data["data_source_keys"].pop(name, None)
        save(data)
    return data_source_keys_status()
