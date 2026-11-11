import pandas as pd
import streamlit as st

from components.api_client import safe_get
from components.ui import cards, setup, synthetic_banner

setup("Market Overview", "Latest available Lower Punjab paddy, finished rice, broken rice and Karachi prices")
inc = st.session_state.get("include_synthetic", True)
if inc:
    synthetic_banner()

data = safe_get("/api/prices/latest", {"include_synthetic": inc})
status = safe_get("/api/sources/status")
if not data:
    st.stop()
items = data["items"]

c1, c2, c3, c4 = st.columns(4)
newest = max((r["observation_date"] for r in items), default="-")
c1.metric("Price series (latest each)", f"{len(items):,}")
c2.metric("Newest observation date", newest)
c3.metric("Observed today", sum(r["is_today"] for r in items))
if status:
    ok = [s["last_success_at"] for s in status["sources"] if s["last_success_at"]]
    c4.metric("Last successful update", max(ok)[:16].replace("T", " ") if ok else "never")

with st.expander("Filters", expanded=False):
    f1, f2, f3 = st.columns(3)
    varieties = sorted({r["variety"] for r in items})
    sel_var = f1.selectbox("Variety", ["All"] + varieties)
    grades = sorted({r["grade"] for r in items if sel_var in ("All", r["variety"])})
    sel_grade = f2.selectbox("Grade", ["All"] + grades)
    cities = sorted({r["city"] for r in items if r["region"] in ("Lower Punjab", "Karachi")})
    sel_city = f3.selectbox("City", ["All"] + cities)


def keep(r):
    return ((sel_var == "All" or r["variety"] == sel_var) and (sel_grade == "All" or r["grade"] == sel_grade)
            and (sel_city == "All" or r["city"] == sel_city))


def show(rows, empty_msg):
    if rows:
        cards(rows)
    else:
        st.info(empty_msg)


items = [r for r in items if keep(r)]
lp = [r for r in items if r["region"] == "Lower Punjab"]
tabs = st.tabs(["Lower Punjab paddy", "Lower Punjab finished rice", "Karachi rice", "Broken rice", "Table"])
with tabs[0]:
    st.caption("Wholesale mandi prices for unmilled paddy (dhaan).")
    show([r for r in lp if r["product_type"] == "paddy"], "No paddy observations for this filter.")
with tabs[1]:
    st.caption("Mill-gate wholesale and government-notified retail prices for finished rice. The category is shown on each card.")
    show([r for r in lp if r["product_type"] == "rice"], "No finished rice observations for this filter.")
with tabs[2]:
    show([r for r in items if r["city"] == "Karachi" and r["product_type"] != "paddy"], "No Karachi observations for this filter.")
with tabs[3]:
    show([r for r in items if r["product_type"] == "broken_rice" and r["region"] in ("Lower Punjab", "Karachi")],
         "No broken rice observations for this filter.")
with tabs[4]:
    cols = ["product_name", "variety", "grade", "market", "city", "price", "original_unit", "normalized_price",
            "normalized_unit", "price_category", "observation_date", "freshness_label", "source_name",
            "verification_status", "data_label"]
    st.dataframe(pd.DataFrame(items)[cols] if items else pd.DataFrame(), width="stretch", hide_index=True)

if status:
    st.subheader("Source freshness")
    df = pd.DataFrame(status["sources"])
    if not df.empty:
        st.dataframe(df[["name", "data_nature", "availability_status", "last_success_at", "last_observation_at"]],
                     width="stretch", hide_index=True)
st.caption(data["disclaimer"])
