"""Admin-managed provider settings: AI model (LLM) providers and data-source API keys.

* Stored on the BACKEND only, in ``storage/provider_settings.json`` (git-ignored, like ``.env``).
* API keys are write-only: every function that returns data to the API masks them.
* Values in this file take precedence over ``.env``; ``.env`` remains a fallback.

LLM providers are tried in ``priority`` order (lowest number first). If one fails or times out the next one is used,
and if none works the chatbot falls back to its retrieval-only answer.
"""
from __future__ import annotations

import copy
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
# Base URLs and model ids were checked on 2026-11-12 against each provider's own documentation or live /models list:
#   Groq docs (console.groq.com/docs/models), Google AI Studio docs (OpenAI compatibility + pricing pages),
#   OpenRouter GET /api/v1/models, Anthropic OpenAI-SDK compatibility page, OpenAI models page.
# Model names change often: use "List models" on the Settings page to see what a provider offers today, and "Test".
# Free-tier limits and terms are set by each provider and can change - check them before relying on a service.
#
# temperature: None = do not send it (Claude 5 and OpenAI's newer models reject custom values).
# token_param: the request field for the answer length limit (OpenAI's newer models need max_completion_tokens).
# ---------------------------------------------------------------------------------------------------------------
PRESETS: list[dict] = [
    {"preset": "groq", "name": "Groq", "tier": "free", "base_url": "https://api.groq.com/openai/v1",
     "model_hint": "openai/gpt-oss-120b", "models": ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b",
                                                     "llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
     "needs_key": True, "signup_url": "https://console.groq.com/keys", "temperature": 0.1, "max_tokens": 2500,
     "token_param": "max_tokens", "notes": "Hosted, very fast, free tier with rate limits set by Groq. Models offered differ "
                                           "per account - use List models (Llama models were not offered to this account)."},
    {"preset": "gemini", "name": "Google Gemini (AI Studio)", "tier": "free",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model_hint": "gemini-3.8-flash",
     "models": ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"],
     "needs_key": True, "signup_url": "https://aistudio.google.com/apikey", "temperature": 0.1, "max_tokens": 2500,
     "token_param": "max_tokens", "notes": "Free tier listed by Google for these Flash models; Google's free-tier terms apply "
                                           "(check whether free-tier prompts may be used to improve Google products)."},
    {"preset": "openrouter_free", "name": "OpenRouter (free models)", "tier": "free", "base_url": "https://openrouter.ai/api/v1",
     "model_hint": "google/gemma-4-31b-it:free", "models": ["google/gemma-4-31b-it:free", "google/gemma-4-26b-a4b-it:free",
                                                            "nvidia/nemotron-3.5-super-vl:free", "openrouter/free"],
     "needs_key": True, "signup_url": "https://openrouter.ai/keys", "temperature": 0.1, "max_tokens": 2500,
     "token_param": "max_tokens", "notes": "Model ids ending in ':free' cost nothing (rate-limited); 'openrouter/free' picks any "
                                           "free model. Other OpenRouter models are paid."},
    {"preset": "ollama", "name": "Ollama (local, on this PC)", "tier": "free", "base_url": "http://localhost:11434/v1",
     "model_hint": "llama3.2", "models": ["llama3.2"], "needs_key": False, "signup_url": "https://ollama.com/download",
     "temperature": 0.1, "max_tokens": 900, "token_param": "max_tokens",
     "notes": "Runs on your own computer: no key, no cost, works offline. Install Ollama, then run: ollama pull llama3.2"},
    {"preset": "anthropic", "name": "Anthropic Claude", "tier": "paid", "base_url": "https://api.anthropic.com/v1",
     "model_hint": "claude-haiku-5-5", "models": ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
     "needs_key": True, "signup_url": "https://platform.claude.com/settings/keys", "temperature": None, "max_tokens": 2500,
     "token_param": "max_tokens", "notes": "Paid, billed per token. Uses Anthropic's OpenAI-SDK compatibility endpoint. "
                                           "Claude 5 models think by default, so the length limit is higher."},
    {"preset": "openai", "name": "OpenAI", "tier": "paid", "base_url": "https://api.openai.com/v1",
     "model_hint": "gpt-6-luna", "models": ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"], "needs_key": True,
     "signup_url": "https://platform.openai.com/api-keys", "temperature": None, "max_tokens": 2500,
     "token_param": "max_completion_tokens", "notes": "Paid, billed per token by OpenAI. gpt-6-luna is the lowest-priced model."},
    {"preset": "custom", "name": "Custom OpenAI-compatible endpoint", "tier": "free", "base_url": "",
     "model_hint": "", "models": [], "needs_key": False, "signup_url": "", "temperature": 0.1, "max_tokens": 900,
     "token_param": "max_tokens",
     "notes": "Any other server that implements /v1/chat/completions (LM Studio, vLLM, a company gateway...)."},
]
PRESET_BY_KEY = {p["preset"]: p for p in PRESETS}

# Recommended fallback plan: the strongest free hosted model first, a second free provider next, then more free
# models, then the local model (works without internet), and paid models LAST and switched off until you choose.
# After every model, the chatbot's final fallback is always the retrieval-only answer (no AI model needed).
RECOMMENDED_PLAN: list[tuple[str, str, int, str]] = [
    ("openrouter_free", "openrouter/free", 10, "OpenRouter auto free model"),
    ("openrouter_free", "google/gemma-4-31b-it:free", 20, "OpenRouter Gemma 4 31B (free)"),
    ("groq", "openai/gpt-oss-120b", 30, "Groq GPT-OSS 120B"),
    ("gemini", "gemini-3.8-flash", 40, "Gemini 3.8 Flash"),
    ("groq", "qwen/qwen3.8-27b", 50, "Groq Qwen 3.8 27B"),
    ("gemini", "gemini-3.5-flash", 55, "Gemini 3.5 Flash (backup)"),
    ("ollama", "llama3.2", 60, "Ollama Llama 3.2 (local, offline)"),
    ("anthropic", "claude-haiku-5-5", 90, "Claude Haiku 5.5 (paid backup)"),
    ("openai", "gpt-6-luna", 95, "OpenAI GPT-6 Luna (paid backup)"),
]

# Pricing-accuracy settings (Settings page -> Pricing accuracy). Defaults reproduce the original behaviour.
ACCURACY_FIELDS: dict[str, dict] = {
    "min_price_pkr_per_kg": {"default": 10.0, "min": 0.0, "max": 1000.0,
                             "help": "Reject PKR prices below this (per kg, after unit conversion)."},
    "max_price_pkr_per_kg": {"default": 3000.0, "min": 50.0, "max": 20000.0, "help": "Reject PKR prices above this (per kg)."},
    "min_price_usd_per_mt": {"default": 100.0, "min": 0.0, "max": 2000.0, "help": "Reject export/benchmark prices below this (USD/MT)."},
    "max_price_usd_per_mt": {"default": 5000.0, "min": 200.0, "max": 20000.0, "help": "Reject export/benchmark prices above this (USD/MT)."},
    "max_jump_pct": {"default": 0.0, "min": 0.0, "max": 500.0,
                     "help": "Spike filter: reject a new price that differs from the previous price of the SAME product, market, "
                             "category and source by more than this %. 0 = off. 25 is a sensible value for daily data."},
    "trend_threshold_pct": {"default": 1.5, "min": 0.1, "max": 20.0, "help": "Change needed to call a market Rising / Falling."},
    "stale_after_days_daily": {"default": 2, "min": 0, "max": 60, "help": "Daily prices older than this many days are marked stale."},
    "stale_after_days_periodic": {"default": 45, "min": 1, "max": 400,
                                  "help": "Monthly / periodic benchmarks older than this many days are marked stale."},
    "retrieval_k": {"default": 5, "min": 1, "max": 20, "help": "Document chunks given to the chatbot per question."},
    "min_retrieval_score": {"default": 0.0, "min": 0.0, "max": 0.95,
                            "help": "Ignore document chunks less similar than this (0-1). 0 = keep all. Try 0.25 to cut off-topic text."},
    "llm_timeout_seconds": {"default": 60.0, "min": 5.0, "max": 300.0,
                            "help": "How long to wait for one AI model before trying the next one."},
    "failure_cooldown_seconds": {"default": 120, "min": 0, "max": 3600,
                                 "help": "After a model fails (rate limit, outage), skip it for this many seconds and go straight to the next."},
}

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
    return {"version": 1, "llm_providers": [], "data_source_keys": {}, "accuracy": {}}


_cache: dict = {"key": None, "data": None}


def _read() -> dict:
    """Parsed file, cached until the file changes (the prices code reads settings for every row)."""
    p = _path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
    except OSError:
        return _empty()
    if _cache["key"] != key:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = _empty()
        data.setdefault("llm_providers", [])
        data.setdefault("data_source_keys", {})
        data.setdefault("accuracy", {})
        _cache.update(key=key, data=data)
    return _cache["data"]


def load() -> dict:
    """A private copy of the settings, safe to modify and pass to save()."""
    with _lock:
        return copy.deepcopy(_read())


def save(data: dict) -> None:
    with _lock:
        p = _path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)  # atomic: a crash never leaves a half-written file
        _cache["key"] = None


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
    if p.get("token_param", "max_tokens") not in ("max_tokens", "max_completion_tokens"):
        raise SettingsError("token_param must be max_tokens or max_completion_tokens")
    t = p.get("temperature")
    if t is not None and not 0 <= float(t) <= 2:
        raise SettingsError("temperature must be between 0 and 2, or empty")


def _tuning(values: dict) -> dict:
    """Per-provider request options, defaulting to the preset's values."""
    pre = PRESET_BY_KEY.get(values.get("preset") or "custom", PRESET_BY_KEY["custom"])
    temp = values["temperature"] if "temperature" in values else pre["temperature"]
    return {"temperature": None if temp is None else float(temp),
            "max_tokens": int(values.get("max_tokens") or pre["max_tokens"]),
            "token_param": values.get("token_param") or pre["token_param"]}


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
             **_tuning(values),
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
            if "temperature" in values:
                p["temperature"] = None if values["temperature"] is None else float(values["temperature"])
            if values.get("max_tokens") is not None:
                p["max_tokens"] = int(values["max_tokens"])
            if values.get("token_param") is not None:
                p["token_param"] = values["token_param"]
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
            "model": s.llm_model, "api_key": s.llm_api_key, "enabled": True, "priority": 1000, "notes": "configured in .env",
            "temperature": 0.1, "max_tokens": 900, "token_param": "max_tokens"}


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


# ------------------------------------------------------------------ recommended fallback plan
def install_recommended_plan() -> dict:
    """Add the recommended providers that are not saved yet. All start DISABLED; each one is switched on when you add
    its key (Ollama: once installed). Existing entries are never changed."""
    with _lock:
        data = load()
        have = {(p.get("preset"), p.get("model")) for p in data["llm_providers"]}
        saved_keys = {p.get("preset"): p.get("api_key") for p in data["llm_providers"] if p.get("api_key")}
        added = []
        for preset, model, priority, name in RECOMMENDED_PLAN:
            if (preset, model) in have:
                continue
            pre = PRESET_BY_KEY[preset]
            p = {"id": uuid.uuid4().hex[:12], "name": name, "preset": preset, "tier": pre["tier"], "base_url": pre["base_url"],
                 "model": model, "api_key": saved_keys.get(preset, ""),
                 "enabled": bool(saved_keys.get(preset)) and pre["tier"] == "free", "priority": priority, "notes": pre["notes"][:500],
                 "created_at": now_iso(), "updated_at": now_iso(), "last_test_at": None, "last_test_ok": None,
                 "last_test_message": "", **_tuning({"preset": preset})}
            data["llm_providers"].append(p)
            added.append(name)
        save(data)
    return {"added": added, "providers": list_llm_providers()}


def set_key_for_preset(preset: str, api_key: str, enable: bool = True) -> list[str]:
    """One key per provider account: save it on every saved model of that provider and switch them on."""
    if preset not in PRESET_BY_KEY or preset == "custom":
        raise SettingsError(f"unknown provider: {preset}")
    with _lock:
        data = load()
        changed = []
        for p in data["llm_providers"]:
            if p.get("preset") == preset:
                p["api_key"] = api_key.strip()
                if enable and (api_key.strip() or not PRESET_BY_KEY[preset]["needs_key"]):
                    p["enabled"] = True
                if not api_key.strip() and PRESET_BY_KEY[preset]["needs_key"]:
                    p["enabled"] = False
                p["updated_at"] = now_iso()
                changed.append(p["id"])
        if not changed:
            raise SettingsError("no saved model uses this provider - load the recommended plan or add one first")
        save(data)
    return changed


# ------------------------------------------------------------------ pricing-accuracy settings
def get_accuracy() -> dict:
    stored = _read().get("accuracy", {})
    return {name: type(f["default"])(stored.get(name, f["default"])) for name, f in ACCURACY_FIELDS.items()}


def accuracy_value(name: str):
    return get_accuracy()[name]


def accuracy_status() -> list[dict]:
    cur = get_accuracy()
    return [{"name": n, "value": cur[n], "default": f["default"], "min": f["min"], "max": f["max"], "help": f["help"],
             "changed": cur[n] != f["default"]} for n, f in ACCURACY_FIELDS.items()]


def set_accuracy(values: dict) -> list[dict]:
    """``None`` = reset that setting to its default."""
    with _lock:
        data = load()
        acc = data.setdefault("accuracy", {})
        for name, v in values.items():
            f = ACCURACY_FIELDS.get(name)
            if not f:
                raise SettingsError(f"unknown accuracy setting: {name}")
            if v is None:
                acc.pop(name, None)
                continue
            try:
                v = type(f["default"])(v)
            except (TypeError, ValueError) as e:
                raise SettingsError(f"{name}: not a number") from e
            if not f["min"] <= v <= f["max"]:
                raise SettingsError(f"{name} must be between {f['min']} and {f['max']}")
            acc[name] = v
        merged = {**{n: f["default"] for n, f in ACCURACY_FIELDS.items()}, **acc}
        if merged["min_price_pkr_per_kg"] >= merged["max_price_pkr_per_kg"]:
            raise SettingsError("min_price_pkr_per_kg must be below max_price_pkr_per_kg")
        if merged["min_price_usd_per_mt"] >= merged["max_price_usd_per_mt"]:
            raise SettingsError("min_price_usd_per_mt must be below max_price_usd_per_mt")
        save(data)
    return accuracy_status()


def needs_key(p: dict) -> bool:
    """True if this provider's template requires an API key (a model without one is skipped in the fallback plan)."""
    return PRESET_BY_KEY.get(p.get("preset") or "custom", PRESET_BY_KEY["custom"])["needs_key"]
