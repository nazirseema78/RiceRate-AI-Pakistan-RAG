"""REST API endpoints."""
from __future__ import annotations

import logging
import secrets
import threading
import time
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from backend.config import get_settings
from backend.database.db import get_conn
from backend.schemas.api import (BriefingResponse, ChatRequest, ChatResponse, CompareModelsRequest, CompareResponse,
                                 AccuracyUpdate, DataSourceKeysUpdate, ProviderKeyUpdate,
                                 GenericListResponse, HealthResponse, LLMProviderCreate, LLMProviderUpdate, ModelListRequest,
                                 PriceListResponse, RefreshRequest, RefreshResponse)
from backend.services import provider_settings as ps
from backend.services.analytics import prices as pa
from backend.services.analytics.briefing import build_briefing
from backend.services.rag import llm, vectorstore
from backend.services.rag.chatbot import answer_question

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
PKT = ZoneInfo("Asia/Karachi")
DISCLAIMER = ("Prices are the latest AVAILABLE observations with their original dates - not necessarily today's rates. "
              "Rows labelled SYNTHETIC DEMO DATA are fictional.")
def ProductType():
    return Query(None, pattern="^(paddy|rice|broken_rice)$")
def Category():
    return Query(None, pattern="^(wholesale|retail|export|broker_quotation)$")
def Text():
    return Query(None, max_length=80)
_refresh_lock = threading.Lock()
_last_refresh = 0.0


@router.get("/health", response_model=HealthResponse)
def health():
    from backend.scheduler.scheduler import scheduler_info

    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) AS n FROM market_prices").fetchone()["n"]
    return HealthResponse(status="ok", app=get_settings().app_name, database="ok", price_observations=n,
                          vector_chunks=vectorstore.index_count(), embedding_model=vectorstore.embedding_name(),
                          llm_provider=llm.chain_summary(), scheduler=scheduler_info(),
                          time_pkt=datetime.now(PKT).isoformat(timespec="seconds"))


@router.get("/products", response_model=GenericListResponse)
def products():
    items = pa.list_products()
    return GenericListResponse(count=len(items), items=items)


@router.get("/markets", response_model=GenericListResponse)
def markets():
    items = pa.list_markets()
    return GenericListResponse(count=len(items), items=items)


@router.get("/prices/latest", response_model=PriceListResponse)
def prices_latest(city: str | None = Text(), product_type: str | None = ProductType(), variety: str | None = Text(),
                  grade: str | None = Text(), price_category: str | None = Category(), region: str | None = Text(),
                  provider_key: str | None = Text(), as_of: date | None = None, include_synthetic: bool = True):
    items = pa.latest_prices(as_of=as_of, city=city, product_type=product_type, variety=variety, grade=grade,
                             price_category=price_category, region=region, provider_key=provider_key,
                             include_synthetic=include_synthetic)
    return PriceListResponse(count=len(items), items=items, disclaimer=DISCLAIMER)


@router.get("/prices/history", response_model=GenericListResponse)
def prices_history(product_key: str | None = Text(), city: str | None = Text(), product_type: str | None = ProductType(),
                   variety: str | None = Text(), price_category: str | None = Category(), region: str | None = Text(),
                   days: int = Query(30, ge=1, le=730), include_synthetic: bool = True):
    items = pa.price_history(days=days, product_key=product_key, city=city, product_type=product_type, variety=variety,
                             price_category=price_category, region=region, include_synthetic=include_synthetic)
    return GenericListResponse(count=len(items), items=items, disclaimer=DISCLAIMER)


@router.get("/prices/compare", response_model=CompareResponse)
def prices_compare(cities: str | None = Query(None, max_length=200), product_type: str | None = ProductType(),
                   variety: str | None = Text(), grade: str | None = Text(), price_category: str | None = Category(),
                   as_of: date | None = None, include_synthetic: bool = True):
    city_list = [c.strip() for c in cities.split(",") if c.strip()] if cities else None
    res = pa.compare_markets(cities=city_list, as_of=as_of, product_type=product_type, variety=variety, grade=grade,
                             price_category=price_category, include_synthetic=include_synthetic)
    return CompareResponse(**res, disclaimer=DISCLAIMER)


@router.get("/prices/changes", response_model=GenericListResponse)
def prices_changes(region: str | None = Text(), product_type: str | None = ProductType(), include_synthetic: bool = True):
    items = pa.price_changes(region=region, product_type=product_type, include_synthetic=include_synthetic)
    summary = pa.market_direction_summary(7, region=region, product_type=product_type, include_synthetic=include_synthetic)
    return GenericListResponse(count=len(items), items=items, disclaimer=f"Direction summary (7d): {summary}")


@router.get("/prices/direction", response_model=GenericListResponse)
def prices_direction(window: int = Query(7, ge=1, le=90), region: str | None = Text(), include_synthetic: bool = True):
    items = pa.market_direction_summary(window, region=region, include_synthetic=include_synthetic)
    return GenericListResponse(count=len(items), items=items,
                               disclaimer="Labels describe observed past changes (+/-1.5% threshold). They are not forecasts.")


@router.get("/karachi/quotations", response_model=GenericListResponse)
def karachi_quotations(valid_only: bool = False, product_type: str | None = ProductType(), include_synthetic: bool = True,
                       limit: int = Query(50, ge=1, le=500)):
    items = pa.broker_quotations(valid_only=valid_only, product_type=product_type, include_synthetic=include_synthetic, limit=limit)
    return GenericListResponse(count=len(items), items=items,
                               disclaimer="Buyer quotations are offers valid only until their 'valid_until' date.")


@router.get("/international/prices", response_model=PriceListResponse)
def international_prices(country: str | None = Text(), include_synthetic: bool = True):
    items = pa.latest_prices(region="International", country=country, include_synthetic=include_synthetic)
    return PriceListResponse(count=len(items), items=items,
                             disclaimer="International prices are export (FOB) quotations or monthly benchmark averages in USD/MT. "
                                        "They are not equivalent to Pakistani domestic wholesale prices. " + DISCLAIMER)


@router.get("/news/latest", response_model=GenericListResponse)
def news_latest(region: str | None = Text(), limit: int = Query(20, ge=1, le=100), include_synthetic: bool = True):
    items = pa.latest_news(region=region, limit=limit, include_synthetic=include_synthetic)
    return GenericListResponse(count=len(items), items=items)


@router.get("/market/briefing", response_model=BriefingResponse)
def market_briefing(include_synthetic: bool = True):
    return build_briefing(include_synthetic=include_synthetic)


@router.get("/sources/status")
def sources_status():
    from backend.scheduler.scheduler import scheduler_info

    data = pa.sources_status()
    data["scheduler"] = scheduler_info()
    data["refresh_min_interval_seconds"] = get_settings().refresh_min_interval_seconds
    return data


@router.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        return answer_question(req.question, [m.model_dump() for m in req.history])
    except Exception as e:
        log.exception("chat failed")
        raise HTTPException(status_code=500, detail="Chatbot error - see backend logs") from e


def require_admin(x_admin_token: str | None = Header(None)) -> None:
    token = get_settings().admin_token
    if not token:
        raise HTTPException(status_code=503, detail="Admin endpoints disabled: set ADMIN_TOKEN in .env")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, token):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token")


@router.post("/admin/refresh", response_model=RefreshResponse, dependencies=[Depends(require_admin)])
def admin_refresh(req: RefreshRequest | None = None):
    global _last_refresh
    req = req or RefreshRequest()
    wait = get_settings().refresh_min_interval_seconds - (time.monotonic() - _last_refresh)
    if _last_refresh and wait > 0:
        raise HTTPException(status_code=429, detail=f"Refresh rate limit: try again in {int(wait)} seconds")
    if not _refresh_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="A refresh is already running")
    try:
        _last_refresh = time.monotonic()
        from backend.scheduler.scheduler import run_scheduled_check

        results = run_scheduled_check(trigger="manual", force=req.force)
        idx = vectorstore.build_index(rebuild=req.rebuild_index)
        return RefreshResponse(status="completed", results=results, index=idx)
    finally:
        _refresh_lock.release()


@router.get("/llm/status")
def llm_status():
    """Public, key-free view of which AI models the chatbot will try, in order."""
    chain = ps.active_llm_chain()
    return {"enabled": bool(chain), "summary": llm.chain_summary(), "fallback_plan": llm.chain_status()}


# ------------------------------------------------------------------ admin: AI model providers + data-source keys
def _not_found(pid: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"No AI model provider with id {pid!r}")


@router.get("/admin/settings", dependencies=[Depends(require_admin)])
def admin_settings():
    env = ps.env_llm_provider()
    return {"llm_providers": ps.list_llm_providers(), "presets": ps.PRESETS,
            "env_llm_provider": ps.public_provider(env) if env else None,
            "active_chain": llm.chain_summary(), "fallback_plan": llm.chain_status(),
            "recommended_plan": [{"preset": a, "model": b, "priority": c, "name": d} for a, b, c, d in ps.RECOMMENDED_PLAN],
            "accuracy": ps.accuracy_status(), "data_source_keys": ps.data_source_keys_status(),
            "storage": "storage/provider_settings.json on the backend (git-ignored). Keys are never sent back to the browser."}


@router.post("/admin/llm/providers", dependencies=[Depends(require_admin)])
def admin_add_llm_provider(req: LLMProviderCreate):
    try:
        return ps.add_llm_provider(req.model_dump(exclude_unset=True))
    except ps.SettingsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.put("/admin/llm/providers/{pid}", dependencies=[Depends(require_admin)])
def admin_update_llm_provider(pid: str, req: LLMProviderUpdate):
    try:
        return ps.update_llm_provider(pid, req.model_dump(exclude_unset=True))
    except KeyError as e:
        raise _not_found(pid) from e
    except ps.SettingsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.delete("/admin/llm/providers/{pid}", dependencies=[Depends(require_admin)])
def admin_delete_llm_provider(pid: str):
    try:
        ps.delete_llm_provider(pid)
    except KeyError as e:
        raise _not_found(pid) from e
    return {"deleted": pid}


@router.post("/admin/llm/providers/{pid}/test", dependencies=[Depends(require_admin)])
def admin_test_llm_provider(pid: str):
    try:
        provider = ps.get_llm_provider(pid, include_secrets=True)
    except KeyError as e:
        raise _not_found(pid) from e
    result = llm.test_provider(provider)
    ps.update_llm_provider(pid, {"last_test_at": ps.now_iso(), "last_test_ok": result["ok"],
                                 "last_test_message": result["message"][:300]})
    return result


@router.post("/admin/llm/models", dependencies=[Depends(require_admin)])
def admin_list_models(req: ModelListRequest):
    if req.provider_id:
        try:
            provider = ps.get_llm_provider(req.provider_id, include_secrets=True)
        except KeyError as e:
            raise _not_found(req.provider_id) from e
        if req.api_key:  # unsaved key typed in the edit form
            provider = {**provider, "api_key": req.api_key}
    else:
        if not req.base_url or not ps.URL_RE.match(req.base_url):
            raise HTTPException(status_code=422, detail="base_url must start with http:// or https://")
        provider = {"base_url": req.base_url, "api_key": req.api_key or ""}
    try:
        return {"models": llm.list_models(provider)}
    except llm.LLMError as e:
        raise HTTPException(status_code=502, detail=f"Provider did not return a model list: {e}") from e


@router.put("/admin/data-source-keys", dependencies=[Depends(require_admin)])
def admin_set_data_source_keys(req: DataSourceKeysUpdate):
    try:
        return {"data_source_keys": ps.set_data_source_keys(req.values)}
    except ps.SettingsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/admin/llm/compare", dependencies=[Depends(require_admin)])
def admin_compare_models(req: CompareModelsRequest):
    """Ask the same question to each chosen model (enabled or not) and return the answers side by side."""
    saved = ps.list_llm_providers(include_secrets=True)
    chosen = saved if req.provider_ids is None else [p for p in saved if p["id"] in set(req.provider_ids)]
    runs = ([("Retrieval only (no AI model)", "free", [])] if req.include_retrieval_only else []) +            [(f"{p['name']} - {p['model']}", p["tier"], [p]) for p in chosen]
    results = []
    for label, tier, providers in runs:
        started = time.monotonic()
        try:
            a = answer_question(req.question, providers=providers)
            failed_llm = bool(providers) and not a["used_llm"]
            results.append({"label": label, "tier": tier, "ok": True, "answer": a["answer"], "used_llm": a["used_llm"],
                            "note": ("model failed or its answer was rejected - showing the retrieval-only answer"
                                     if failed_llm else ""),
                            "warnings": a["warnings"], "route": a["route"], "sources": len(a["sources"]),
                            "seconds": round(time.monotonic() - started, 1)})
        except Exception as e:  # one model's failure must not hide the others' results
            log.exception("compare run failed for %s", label)
            results.append({"label": label, "tier": tier, "ok": False, "answer": "", "used_llm": False,
                            "note": f"error: {e.__class__.__name__}", "warnings": [], "route": "", "sources": 0,
                            "seconds": round(time.monotonic() - started, 1)})
    return {"question": req.question, "results": results}


@router.post("/admin/llm/recommended-plan", dependencies=[Depends(require_admin)])
def admin_install_recommended_plan():
    """Add the recommended free -> local -> paid fallback list (all switched off until their key is added)."""
    return ps.install_recommended_plan()


@router.put("/admin/llm/provider-key", dependencies=[Depends(require_admin)])
def admin_set_provider_key(req: ProviderKeyUpdate):
    try:
        ids = ps.set_key_for_preset(req.preset, req.api_key, req.enable)
    except ps.SettingsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    llm.reset_cooldowns()
    return {"updated": len(ids), "providers": ps.list_llm_providers()}


@router.post("/admin/llm/reset-cooldowns", dependencies=[Depends(require_admin)])
def admin_reset_cooldowns():
    llm.reset_cooldowns()
    return {"fallback_plan": llm.chain_status()}


@router.get("/admin/accuracy", dependencies=[Depends(require_admin)])
def admin_get_accuracy():
    return {"accuracy": ps.accuracy_status()}


@router.put("/admin/accuracy", dependencies=[Depends(require_admin)])
def admin_set_accuracy(req: AccuracyUpdate):
    try:
        return {"accuracy": ps.set_accuracy(req.values)}
    except ps.SettingsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
