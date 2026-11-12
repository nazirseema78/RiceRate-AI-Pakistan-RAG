"""Settings (Admin): AI-model fallback plan (free first, paid last), model comparison, pricing-accuracy rules and
data-source API keys. Everything is saved on the backend; keys typed here are never shown again (last 4 characters only).
"""
import pandas as pd
import streamlit as st

from components.api_client import BackendError, cached_get, request
from components.ui import setup

setup("Settings (Admin)", "AI models with automatic fallback, pricing-accuracy rules and API keys - stored on the backend only")

# ------------------------------------------------------------------ admin token
st.session_state.setdefault("admin_token", "")
with st.form("unlock"):
    tok = st.text_input("Admin token (ADMIN_TOKEN from the backend .env file)", type="password",
                        value=st.session_state["admin_token"])
    if st.form_submit_button("Unlock settings"):
        st.session_state["admin_token"] = tok
H = {"X-Admin-Token": st.session_state["admin_token"]}
if not st.session_state["admin_token"]:
    st.info("Enter the admin token to manage AI models, accuracy rules and API keys.")
    st.stop()


def call(method: str, path: str, payload: dict | None = None, timeout: float = 60):
    try:
        return request(method, path, payload, headers=H, timeout=timeout)
    except BackendError as e:
        st.error(str(e))
        return None


def flash(msg: str, ok: bool = True) -> None:
    st.session_state.setdefault("flash", []).append((msg, ok))


def done(msg: str, ok: bool = True) -> None:
    cached_get.clear()
    flash(msg, ok)
    st.rerun()


for msg, ok in st.session_state.pop("flash", []):
    (st.success if ok else st.error)(msg)

cfg = call("GET", "/api/admin/settings")
if not cfg:
    st.stop()
presets = {p["preset"]: p for p in cfg["presets"]}
provs = cfg["llm_providers"]
TIER = {"free": "🟢 Free", "paid": "🟠 Paid"}

tab_quick, tab_models, tab_compare, tab_acc, tab_keys = st.tabs(
    ["🚀 Quick setup & fallback plan", "🤖 All models", "🧪 Compare models", "🎯 Pricing accuracy", "🔑 Data-source keys"])

# ================================================================== QUICK SETUP
with tab_quick:
    st.markdown("#### How the fallback plan works")
    st.markdown(
        "1. The chatbot asks the **first ready model**. If it fails (no internet, rate limit, outage, timeout) it moves to the next.\n"
        "2. A model that just failed is **skipped for a while** (cooldown, see *Pricing accuracy*) so answers stay fast.\n"
        "3. **Free hosted models first** → **local Ollama** (works offline) → **paid models last** (off until you switch them on).\n"
        "4. If every model fails, the chatbot still answers from the price database and documents (**retrieval-only**).\n"
        "5. Whichever model answers, any price or number not found in your data is **rejected**: the AI never invents a rate.")

    st.markdown("#### Current fallback order")
    plan = pd.DataFrame(cfg["fallback_plan"])
    plan["tier"] = plan["tier"].map(TIER)
    st.dataframe(plan[["step", "name", "tier", "model", "state"]], width="stretch", hide_index=True)
    c1, c2 = st.columns(2)
    if c1.button("📥 Load the recommended model list", type="primary" if not provs else "secondary",
                 help="Adds 6 free models and 2 paid backups, all switched off until you add their key. Existing entries are kept."):
        r = call("POST", "/api/admin/llm/recommended-plan")
        if r:
            done(f"Added {len(r['added'])} models: {', '.join(r['added']) or 'all were already there'}")
    if c2.button("🔄 Clear cooldowns (retry failed models now)"):
        if call("POST", "/api/admin/llm/reset-cooldowns"):
            done("Cooldowns cleared")

    if not provs:
        st.info("Click **Load the recommended model list** to start.")
    else:
        st.markdown("#### Add one key per provider")
        st.caption("One key switches on every model of that provider. Free keys take about 2 minutes to create. "
                   "After saving, each model is tested with a one-word message.")
        by_preset: dict[str, list[dict]] = {}
        for p in provs:
            by_preset.setdefault(p.get("preset", "custom"), []).append(p)
        order = sorted(by_preset, key=lambda k: min(p["priority"] for p in by_preset[k]))
        for key in order:
            if key == "custom" or key not in presets:
                continue
            pre, items = presets[key], by_preset[key]
            has_key = any(p["api_key_set"] for p in items)
            on = sum(p["enabled"] for p in items)
            with st.container(border=True):
                a, b = st.columns([3, 2])
                a.markdown(f"**{pre['name']}** · {TIER[pre['tier']]} · models: " + ", ".join(f"`{p['model']}`" for p in items))
                a.caption(pre["notes"])
                if not pre["needs_key"]:
                    key_state = "no key needed"
                elif has_key:
                    key_state = "🔑 key saved " + next(p["api_key_masked"] for p in items if p["api_key_set"])
                else:
                    key_state = "❌ no key yet"
                b.markdown(f"{key_state} · **{on}/{len(items)} on**")
                if pre.get("signup_url"):
                    b.markdown(f"[{'Get a key' if pre['needs_key'] else 'Download'} ↗]({pre['signup_url']})")
                with st.form(f"quick_{key}"):
                    k = st.text_input(f"{pre['name']} API key", type="password", key=f"qk_{key}") if pre["needs_key"] else ""
                    if key == "ollama":
                        st.caption("Install Ollama and run `ollama pull llama3.2` first, then switch it on.")
                    ok_paid = st.checkbox("I understand this provider bills me for every answer it gives",
                                          key=f"qp_{key}") if pre["tier"] == "paid" else True
                    x1, x2 = st.columns(2)
                    save = x1.form_submit_button("💾 Save key & switch on" if pre["needs_key"] else "▶️ Switch on")
                    off = x2.form_submit_button("⏸️ Switch off" + (" & remove key" if pre["needs_key"] else ""))
                if save:
                    if pre["needs_key"] and not k:
                        st.error("Paste the API key first.")
                    elif not ok_paid:
                        st.error("Tick the billing confirmation to switch on a paid provider.")
                    else:
                        r = call("PUT", "/api/admin/llm/provider-key", {"preset": key, "api_key": k, "enable": True})
                        if r:
                            with st.spinner("Testing each model..."):
                                for p in items:
                                    t = call("POST", f"/api/admin/llm/providers/{p['id']}/test", timeout=90)
                                    if t:
                                        flash(f"{p['name']}: {t['message']} ({t['latency_ms']} ms)", t["ok"])
                            done(f"{pre['name']}: switched on {r['updated']} model(s)")
                if off:
                    if pre["needs_key"]:
                        r = call("PUT", "/api/admin/llm/provider-key", {"preset": key, "api_key": "", "enable": False})
                    else:
                        r = all(call("PUT", f"/api/admin/llm/providers/{p['id']}", {"enabled": False}) for p in items)
                    if r:
                        done(f"{pre['name']} switched off")

# ================================================================== ALL MODELS (advanced)
with tab_models:
    st.caption("Edit, reorder, test or delete single models, or add any other model. Lower priority number = tried first.")
    if provs:
        df = pd.DataFrame(provs)
        df["tier"] = df["tier"].map(TIER)
        df["key"] = df["api_key_masked"].replace("", "-")
        df["last test"] = df.apply(lambda r: "-" if r["last_test_ok"] is None else ("✅ ok" if r["last_test_ok"] else "❌ failed"), axis=1)
        st.dataframe(df[["priority", "enabled", "name", "tier", "model", "key", "last test", "base_url"]],
                     width="stretch", hide_index=True)
    if cfg.get("env_llm_provider"):
        e = cfg["env_llm_provider"]
        st.caption(f"Also configured in .env (tried last): {e['name']} - {e['model']} at {e['base_url']}")

    for p in provs:
        with st.expander(f"{'✅' if p['enabled'] else '⏸️'} {p['priority']} · {p['name']} · {p['model']} · {TIER[p['tier']]}"):
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
                c5, c6, c7 = st.columns(3)
                temp = c5.text_input("Temperature (empty = model default)",
                                     "" if p.get("temperature") is None else str(p["temperature"]),
                                     help="0-0.2 gives the most consistent, factual answers. Leave empty for Claude 5 and newer OpenAI models.")
                max_tokens = c6.number_input("Max answer length (tokens)", 16, 16000, int(p.get("max_tokens") or 900))
                tparams = ["max_tokens", "max_completion_tokens"]
                tparam = c7.selectbox("Length field name", tparams, index=tparams.index(p.get("token_param") or "max_tokens"))
                b1, b2, b3, b4 = st.columns(4)
                save = b1.form_submit_button("💾 Save")
                test = b2.form_submit_button("🔌 Test")
                models = b3.form_submit_button("📋 List models")
                delete = b4.form_submit_button("🗑️ Delete")
            if save:
                try:
                    t_val, t_ok = (None if not temp.strip() else float(temp)), True
                except ValueError:
                    t_val, t_ok = None, False
                if not t_ok:
                    st.error("Temperature must be a number like 0.1, or empty.")
                else:
                    body = {"name": name, "tier": tier, "base_url": base_url, "model": model, "enabled": enabled,
                            "priority": int(priority), "temperature": t_val, "max_tokens": int(max_tokens), "token_param": tparam}
                    if remove_key:
                        body["api_key"] = ""
                    elif key:
                        body["api_key"] = key
                    if call("PUT", f"/api/admin/llm/providers/{p['id']}", body):
                        done(f"Saved {name}")
            if test:
                with st.spinner("Sending a one-word test message..."):
                    r = call("POST", f"/api/admin/llm/providers/{p['id']}/test", timeout=90)
                if r:
                    done(f"{p['name']}: {r['message']} ({r['latency_ms']} ms)", r["ok"])
            if models:
                r = call("POST", "/api/admin/llm/models", {"provider_id": p["id"], "api_key": key or None})
                if r:
                    st.write(f"{len(r['models'])} models offered right now (copy one into *Model id*):")
                    st.code("\n".join(r["models"]) or "(empty list)")
            if delete:
                if call("DELETE", f"/api/admin/llm/providers/{p['id']}"):
                    done(f"Deleted {p['name']}")

    st.subheader("➕ Add another model")
    choice = st.selectbox("Provider", list(presets), format_func=lambda k: f"{TIER[presets[k]['tier']]} · {presets[k]['name']}")
    pre = presets[choice]
    st.caption(pre["notes"] + (f"  Get a key: {pre['signup_url']}" if pre.get("signup_url") else ""))
    listed = st.session_state.get(f"models_{choice}") or pre.get("models", [])
    with st.form("add_provider"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", pre["name"])
        tier = c2.selectbox("Tier", ["free", "paid"], index=["free", "paid"].index(pre["tier"]), format_func=TIER.get)
        base_url = st.text_input("Base URL", pre["base_url"])
        key = st.text_input("API key" + ("" if pre["needs_key"] else " (not needed)"), type="password")
        picked = st.selectbox("Model", [""] + listed, help="Checked models for this provider. 'List models' loads its live list.") if listed else ""
        model = st.text_input("...or type a model id", "")
        c3, c4 = st.columns(2)
        enabled = c3.checkbox("Enabled", True)
        priority = c4.number_input("Priority (lower = tried first)", 0, 999, 10 if tier == "free" else 90)
        paid_ok = st.checkbox("If Tier is Paid: I understand this provider bills me for every chatbot answer")
        b1, b2 = st.columns(2)
        list_btn = b1.form_submit_button("📋 List models")
        add_btn = b2.form_submit_button("➕ Add model", type="primary")
    if list_btn:
        r = call("POST", "/api/admin/llm/models", {"base_url": base_url, "api_key": key or None})
        if r:
            st.session_state[f"models_{choice}"] = r["models"]
            done(f"{len(r['models'])} models found - pick one, check the key is still filled in, then click Add.")
    if add_btn:
        chosen = model.strip() or picked
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
                done(f"Added {name}. Open it above and press 'Test' to verify it works.")

# ================================================================== COMPARE MODELS
with tab_compare:
    st.caption("Ask the same question to several models and compare the answers side by side. Switched-off models can be "
               "tried too. Every model gets the same price facts and documents. Paid models are billed per answer.")
    SAMPLES = ["Aaj Multan mein 1121 paddy ka latest available rate kya hai?",
               "Compare Multan and Karachi rice prices",
               "Karachi mein rice rates kyun change ho rahay hain?",
               "Latest available rice market report ka summary do.",
               "What is the latest Thai 5% export benchmark price?"]
    sample = st.selectbox("Sample question", ["(type my own)"] + SAMPLES)
    usable = [p for p in provs if p["api_key_set"] or p.get("preset") in ("ollama", "custom")]
    with st.form("compare"):
        question = st.text_area("Question", "" if sample == "(type my own)" else sample, height=80)
        labels = {p["id"]: f"{p['name']} - {p['model']} ({p['tier']})" for p in usable}
        chosen = st.multiselect("Models to compare (models without a key are not listed)", list(labels),
                                default=[p["id"] for p in usable if p["tier"] == "free"][:4], format_func=labels.get)
        base = st.checkbox("Also show the retrieval-only answer (no AI model) as the baseline", True)
        go = st.form_submit_button("▶️ Run comparison", type="primary")
    if not usable:
        st.info("No model has a key yet - add one in Quick setup. You can still run the retrieval-only baseline.")
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

# ================================================================== PRICING ACCURACY
with tab_acc:
    st.caption("Rules that decide which prices are accepted, when a price counts as old, how trends are labelled and "
               "which text the chatbot may use. Changes apply immediately; price limits apply to new data from the next refresh.")
    GROUPS = [("Price sanity limits (reject impossible prices)", ["min_price_pkr_per_kg", "max_price_pkr_per_kg",
                                                                  "min_price_usd_per_mt", "max_price_usd_per_mt", "max_jump_pct"]),
              ("Freshness and trends", ["stale_after_days_daily", "stale_after_days_periodic", "trend_threshold_pct"]),
              ("Chatbot evidence", ["retrieval_k", "min_retrieval_score"]),
              ("AI model fallback", ["llm_timeout_seconds", "failure_cooldown_seconds"])]
    acc = {a["name"]: a for a in cfg["accuracy"]}
    with st.form("accuracy"):
        new, reset = {}, {}
        for title, names in GROUPS:
            st.markdown(f"**{title}**")
            cols = st.columns(2)
            for i, n in enumerate(names):
                a = acc[n]
                is_int = isinstance(a["default"], int)
                cast = int if is_int else float
                with cols[i % 2]:
                    new[n] = st.number_input(f"{n}{' ✏️' if a['changed'] else ''}", min_value=cast(a["min"]),
                                             max_value=cast(a["max"]), value=cast(a["value"]),
                                             step=1 if is_int else (0.05 if a["max"] <= 1 else 0.5),
                                             help=f"{a['help']} Default: {a['default']}.", key=f"acc_{n}")
                    if a["changed"]:
                        reset[n] = st.checkbox(f"Reset {n} to {a['default']}", key=f"accr_{n}")
        if st.form_submit_button("💾 Save accuracy settings", type="primary"):
            payload = {n: (None if reset.get(n) else v) for n, v in new.items()}
            if call("PUT", "/api/admin/accuracy", {"values": payload}):
                done("Accuracy settings saved")
    st.markdown("**Recommended for real trading data:** spike filter `max_jump_pct` = 25, `min_retrieval_score` = 0.25, "
                "and PKR limits that match what you trade (for example 40-800 PKR/kg for paddy and rice). "
                "Rejected prices are listed per refresh on *Data Source Status* with the reason, so nothing is silently changed.")
    st.markdown("**Other ways to improve price accuracy**\n"
                "- Add the free **PakDataHub** key (last tab) for official AMIS Punjab wholesale mandi prices.\n"
                "- Import your own broker / buyer lists as CSV into `data/imports/` (template in `data/samples/`).\n"
                "- Turn off *Include synthetic demo data* in the sidebar to see only real sources.")

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
                done("Data-source keys saved. They are used from the next refresh.")
    st.caption("PakDataHub free key: https://pakdatahub.com - after saving, run a refresh on *Data Source Status*.")
