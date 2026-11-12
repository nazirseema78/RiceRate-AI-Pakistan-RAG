"""Settings (Admin): AI model providers (free now, paid later) and data-source API keys.

Everything is saved on the backend. Keys typed here are sent once to the backend and are never shown again
(only the last 4 characters).
"""
import pandas as pd
import streamlit as st

from components.api_client import BackendError, cached_get, request
from components.ui import setup

setup("Settings (Admin)", "AI models for the chatbot, and API keys for data sources - stored on the backend only")

# ------------------------------------------------------------------ admin token
st.session_state.setdefault("admin_token", "")
with st.form("unlock"):
    tok = st.text_input("Admin token (ADMIN_TOKEN from the backend .env file)", type="password",
                        value=st.session_state["admin_token"])
    if st.form_submit_button("Unlock settings"):
        st.session_state["admin_token"] = tok
H = {"X-Admin-Token": st.session_state["admin_token"]}
if not st.session_state["admin_token"]:
    st.info("Enter the admin token to manage AI models and API keys.")
    st.stop()


def call(method: str, path: str, payload: dict | None = None, timeout: float = 60):
    try:
        return request(method, path, payload, headers=H, timeout=timeout)
    except BackendError as e:
        st.error(str(e))
        return None


def flash(msg: str, ok: bool = True) -> None:
    st.session_state["flash"] = (msg, ok)


if "flash" in st.session_state:
    msg, ok = st.session_state.pop("flash")
    (st.success if ok else st.error)(msg)

cfg = call("GET", "/api/admin/settings")
if not cfg:
    st.stop()
presets = {p["preset"]: p for p in cfg["presets"]}
TIER = {"free": "🟢 Free", "paid": "🟠 Paid"}

tab_models, tab_compare, tab_keys = st.tabs(["🤖 AI models (chatbot)", "🧪 Compare models", "🔑 Data-source API keys"])

# ================================================================== AI MODELS
with tab_models:
    st.markdown(f"**The chatbot will try, in this order:** {cfg['active_chain']}")
    st.caption("Lowest priority number is tried first. If a provider fails or times out, the next one is used. "
               "With none enabled, answers are built from the price database and documents only (no LLM). "
               "Any AI answer containing a number that is not in the sources is rejected automatically.")

    provs = cfg["llm_providers"]
    if provs:
        df = pd.DataFrame(provs)
        df["tier"] = df["tier"].map(TIER)
        df["key"] = df["api_key_masked"].replace("", "-")
        df["last test"] = df.apply(lambda r: "-" if r["last_test_ok"] is None else ("✅ ok" if r["last_test_ok"] else "❌ failed"), axis=1)
        st.dataframe(df[["priority", "enabled", "name", "tier", "model", "base_url", "key", "last test"]],
                     width="stretch", hide_index=True)
    else:
        st.info("No AI model added yet. Add a free one below (Ollama runs on your own PC with no key).")
    if cfg.get("env_llm_provider"):
        e = cfg["env_llm_provider"]
        st.caption(f"Also configured in .env (tried last): {e['name']} - {e['model']} at {e['base_url']}")

    # ---------------- edit existing
    for p in provs:
        with st.expander(f"{'✅' if p['enabled'] else '⏸️'} {p['name']} · {p['model']} · {TIER[p['tier']]}"):
            if p.get("last_test_at"):
                st.caption(f"Last test {p['last_test_at'][:16].replace('T', ' ')}: {p['last_test_message']}")
            with st.form(f"edit_{p['id']}"):
                c1, c2 = st.columns(2)
                name = c1.text_input("Name", p["name"])
                tier = c2.selectbox("Tier", ["free", "paid"], index=["free", "paid"].index(p["tier"]), format_func=TIER.get)
                base_url = st.text_input("Base URL", p["base_url"])
                model = st.text_input("Model id", p["model"])
                key = st.text_input(f"API key (stored: {p['api_key_masked'] or 'none'}) - leave empty to keep", type="password")
                remove_key = st.checkbox("Remove the stored API key")
                c3, c4 = st.columns(2)
                enabled = c3.checkbox("Enabled", p["enabled"])
                priority = c4.number_input("Priority (lower = tried first)", 0, 999, int(p["priority"]))
                notes = st.text_input("Notes", p.get("notes") or "")
                b1, b2, b3, b4 = st.columns(4)
                save = b1.form_submit_button("💾 Save")
                test = b2.form_submit_button("🔌 Test connection")
                models = b3.form_submit_button("📋 List models")
                delete = b4.form_submit_button("🗑️ Delete")
            if save:
                body = {"name": name, "tier": tier, "base_url": base_url, "model": model, "enabled": enabled,
                        "priority": int(priority), "notes": notes}
                if remove_key:
                    body["api_key"] = ""
                elif key:
                    body["api_key"] = key
                if call("PUT", f"/api/admin/llm/providers/{p['id']}", body):
                    cached_get.clear()
                    flash(f"Saved {name}")
                    st.rerun()
            if test:
                with st.spinner("Sending a one-word test message..."):
                    r = call("POST", f"/api/admin/llm/providers/{p['id']}/test", timeout=60)
                if r:
                    flash(f"{p['name']}: {r['message']} ({r['latency_ms']} ms)", r["ok"])
                    st.rerun()
            if models:
                r = call("POST", "/api/admin/llm/models", {"provider_id": p["id"], "api_key": key or None})
                if r:
                    st.write(f"{len(r['models'])} models offered by this provider (copy one into *Model id*):")
                    st.code("\n".join(r["models"]) or "(empty list)")
            if delete:
                if call("DELETE", f"/api/admin/llm/providers/{p['id']}"):
                    cached_get.clear()
                    flash(f"Deleted {p['name']}")
                    st.rerun()

    # ---------------- add new
    st.subheader("➕ Add an AI model")
    choice = st.selectbox("Start from", list(presets), format_func=lambda k: f"{TIER[presets[k]['tier']]} · {presets[k]['name']}")
    pre = presets[choice]
    st.caption(pre["notes"] + (f"  Get a key: {pre['signup_url']}" if pre.get("signup_url") else ""))
    listed = st.session_state.get(f"models_{choice}", [])
    with st.form("add_provider"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", pre["name"])
        tier = c2.selectbox("Tier", ["free", "paid"], index=["free", "paid"].index(pre["tier"]), format_func=TIER.get)
        base_url = st.text_input("Base URL", pre["base_url"])
        key = st.text_input("API key" + ("" if pre["needs_key"] else " (not needed for this one)"), type="password")
        picked = st.selectbox("Pick a model from the list", [""] + listed) if listed else ""
        model = st.text_input("...or type the model id", "" if listed else pre["model_hint"].replace("use List models", ""),
                              help="Click 'List models' first to see the exact ids this provider offers.")
        c3, c4 = st.columns(2)
        enabled = c3.checkbox("Enabled", True)
        priority = c4.number_input("Priority (lower = tried first)", 0, 999, 10 if tier == "free" else 50)
        paid_ok = st.checkbox("If Tier is Paid: I understand this provider bills me for every chatbot answer")
        b1, b2 = st.columns(2)
        list_btn = b1.form_submit_button("📋 List models")
        add_btn = b2.form_submit_button("➕ Add provider", type="primary")
    if list_btn:
        r = call("POST", "/api/admin/llm/models", {"base_url": base_url, "api_key": key or None})
        if r:
            st.session_state[f"models_{choice}"] = r["models"]
            flash(f"{len(r['models'])} models found - pick one, check the API key is still filled in, then click Add.")
            st.rerun()
    if add_btn:
        chosen = picked or model.strip()
        if tier == "paid" and not paid_ok:
            st.error("Tick the confirmation to add a paid provider.")
        elif not chosen:
            st.error("Choose or type a model id.")
        elif pre["needs_key"] and not key:
            st.error("This provider needs an API key.")
        else:
            body = {"name": name, "preset": choice, "tier": tier, "base_url": base_url, "model": chosen,
                    "api_key": key or None, "enabled": enabled, "priority": int(priority), "notes": pre["notes"][:500]}
            if call("POST", "/api/admin/llm/providers", body):
                st.session_state.pop(f"models_{choice}", None)
                cached_get.clear()
                flash(f"Added {name}. Click it above and press 'Test connection' to verify it works.")
                st.rerun()

# ================================================================== DATA-SOURCE KEYS
with tab_keys:
    st.caption("Keys saved here override the same values in .env. Leave a field empty to keep the current value.")
    rows = cfg["data_source_keys"]
    with st.form("data_keys"):
        new_vals, clear = {}, {}
        for r in rows:
            status = f"current: {r['value']} (from {r['source']})" if r["set"] else "not set"
            new_vals[r["name"]] = st.text_input(f"{r['description']} - {status}", type="password" if r["is_secret"] else "default",
                                                key=f"dk_{r['name']}")
            if r["source"] == "settings page":
                clear[r["name"]] = st.checkbox(f"Remove the saved {r['name']}", key=f"dkc_{r['name']}")
        if st.form_submit_button("💾 Save keys"):
            payload = {n: ("" if clear.get(n) else (v or None)) for n, v in new_vals.items()}
            if call("PUT", "/api/admin/data-source-keys", {"values": payload}):
                cached_get.clear()
                flash("Data-source keys saved. They are used from the next refresh.")
                st.rerun()
    st.caption("After adding the PakDataHub key, go to *Data Source Status* and run a refresh to fetch AMIS Punjab prices.")

# ================================================================== COMPARE MODELS
with tab_compare:
    st.caption("Ask the same question to several models and compare their answers side by side. Disabled models can be "
               "tested here too. Each model gets the same price facts and documents; paid models are billed per answer.")
    SAMPLES = ["Aaj Multan mein 1121 paddy ka latest available rate kya hai?",
               "Compare Multan and Karachi rice prices",
               "Karachi mein rice rates kyun change ho rahay hain?",
               "Latest available rice market report ka summary do.",
               "What is the latest Thai 5% export benchmark price?"]
    sample = st.selectbox("Sample question", ["(type my own)"] + SAMPLES)
    with st.form("compare"):
        question = st.text_area("Question", "" if sample == "(type my own)" else sample, height=80)
        labels = {p["id"]: f"{p['name']} - {p['model']} ({p['tier']})" for p in provs}
        chosen = st.multiselect("Models to compare", list(labels), default=list(labels), format_func=labels.get)
        base = st.checkbox("Also show the retrieval-only answer (no AI model) as the baseline", True)
        go = st.form_submit_button("▶️ Run comparison", type="primary")
    if not provs:
        st.info("No AI model saved yet - add one in the first tab. You can still run the retrieval-only baseline.")
    if go:
        if len(question.strip()) < 2:
            st.error("Type a question.")
        else:
            with st.spinner("Asking each model..."):
                res = call("POST", "/api/admin/llm/compare",
                           {"question": question, "provider_ids": chosen, "include_retrieval_only": base}, timeout=600)
            if res:
                st.session_state["compare_result"] = res
    res = st.session_state.get("compare_result")
    if res:
        st.markdown(f"**Question:** {res['question']}")
        st.dataframe(pd.DataFrame([{"model": r["label"], "tier": TIER.get(r["tier"], r["tier"]),
                                    "AI answer used": "yes" if r["used_llm"] else "no",
                                    "seconds": r["seconds"], "sources": r["sources"], "note": r["note"]}
                                   for r in res["results"]]), width="stretch", hide_index=True)
        cols = st.columns(min(len(res["results"]), 3) or 1)
        for i, r in enumerate(res["results"]):
            with cols[i % len(cols)]:
                st.markdown(f"#### {r['label']}")
                st.caption(f"{TIER.get(r['tier'], r['tier'])} · {r['seconds']} s · route: {r['route'] or '-'}"
                           + (f" · ⚠️ {r['note']}" if r["note"] else ""))
                st.markdown(r["answer"] or "_no answer_")
