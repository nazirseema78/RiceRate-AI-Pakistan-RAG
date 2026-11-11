import pandas as pd
import streamlit as st

from components.api_client import safe_get
from components.ui import direction_chip, setup, synthetic_banner

setup("Market News & Trends", "7 / 15 / 30-day price changes, evidence-based direction labels and the daily briefing")
inc = st.session_state.get("include_synthetic", True)
if inc:
    synthetic_banner()

st.subheader("Daily rice market briefing")
b = safe_get("/api/market/briefing", {"include_synthetic": inc})
if b:
    for w in b["warnings"]:
        st.warning(w)
    with st.container(border=True):
        titles = {"lower_punjab": "Lower Punjab", "karachi": "Karachi", "international": "International",
                  "price_direction": "Recent price direction (observed, not a forecast)", "news": "Important news"}
        for k, t in titles.items():
            st.markdown(f"**{t}**")
            st.markdown("\n".join(f"- {x}" for x in b["sections"][k]))
        st.caption("Sources: " + "; ".join(b["sources"]))
    st.download_button("Download briefing (.txt)", b["text"], file_name=f"rice_briefing_{b['date']}.txt")

st.subheader("Market direction indicators")
st.caption("Rising / Falling = change beyond ±1.5% versus the window start; Stable = within ±1.5%; Mixed = markets disagree; "
           "Insufficient Data = no comparable earlier observation. Labels describe the past and are not predictions.")
w = st.radio("Window", [7, 15, 30], horizontal=True, format_func=lambda d: f"{d} days")
d = safe_get("/api/prices/direction", {"window": w, "include_synthetic": inc})
if d and d["items"]:
    cols = st.columns(3)
    for i, item in enumerate(d["items"]):
        with cols[i % 3]:
            st.markdown(f"<div class='rr-card' style='min-height:90px'><div class='rr-title'>{item['product_name']}</div>"
                        f"{direction_chip(item['direction'])}<div class='rr-sub'>{item['series_count']} series: "
                        f"{item['rising']} up, {item['falling']} down, {item['stable']} stable, {item['insufficient']} n/a</div></div>",
                        unsafe_allow_html=True)

st.subheader("Price changes by market")
ch = safe_get("/api/prices/changes", {"include_synthetic": inc})
if ch and ch["items"]:
    df = pd.DataFrame(ch["items"])
    region = st.selectbox("Region", ["All"] + sorted(df["region"].unique()))
    if region != "All":
        df = df[df["region"] == region]
    cols = ["product_name", "grade", "city", "price_category", "latest_price", "unit", "latest_date",
            "change_7d_pct", "direction_7d", "change_15d_pct", "direction_15d", "change_30d_pct", "direction_30d", "source_name"]
    st.dataframe(df[cols], width="stretch", hide_index=True)

st.subheader("Latest rice market news")
news = safe_get("/api/news/latest", {"limit": 30, "include_synthetic": inc})
if news:
    for n in news["items"]:
        with st.container(border=True):
            st.markdown(f"**{n['title']}**  \n<small>{n['region']} · {n['category']} · {n['published_at'][:10]} · "
                        f"{n['source_name']}</small>", unsafe_allow_html=True)
            st.write(n["summary"])
