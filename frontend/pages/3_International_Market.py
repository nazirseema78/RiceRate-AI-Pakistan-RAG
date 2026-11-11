import pandas as pd
import plotly.express as px
import streamlit as st

from components.api_client import safe_get
from components.ui import cards, setup, synthetic_banner

setup("International Rice Market", "Export quotations, monthly benchmarks and market commentary - Pakistan, India, Thailand, Vietnam")
inc = st.session_state.get("include_synthetic", True)
if inc:
    synthetic_banner()
st.warning("International prices are **export (FOB) quotations or monthly benchmark averages in USD per metric ton**. "
           "They are not directly equivalent to Pakistani domestic wholesale prices (different specification, bagging, "
           "freight, exporter margin and currency).")

data = safe_get("/api/international/prices", {"include_synthetic": inc})
if data:
    items = data["items"]
    countries = ["All"] + sorted({r["country"] for r in items})
    sel = st.radio("Origin", countries, horizontal=True)
    items = [r for r in items if sel in ("All", r["country"])]
    quotes = [r for r in items if r["data_nature"] != "historical"]
    bench = [r for r in items if r["data_nature"] == "historical"]
    t1, t2, t3 = st.tabs(["Export quotations (price observations)", "Monthly benchmarks (historical reports)", "History chart"])
    with t1:
        if quotes:
            cards(quotes)
        else:
            st.info("No export quotation observations.")
    with t2:
        st.caption("World Bank Pink Sheet monthly averages, dated to the first day of each month.")
        if bench:
            cards(bench)
        else:
            st.info("No benchmark data yet (the World Bank connector may be disabled or offline).")
    with t3:
        hist = safe_get("/api/prices/history", {"region": "International", "days": 730, "include_synthetic": inc})
        if hist and hist["items"]:
            h = pd.DataFrame(hist["items"])
            if sel != "All":
                h = h[h["country"] == sel]
            fig = px.line(h, x="price_date", y="price", color="product_name", markers=True,
                          labels={"price": "USD/MT", "price_date": ""})
            fig.update_layout(plot_bgcolor="white", height=420, legend=dict(orientation="h", y=-0.25))
            st.plotly_chart(fig, width="stretch")

st.subheader("International rice news & commentary")
news = safe_get("/api/news/latest", {"region": "International", "include_synthetic": inc})
if news:
    for n in news["items"]:
        kind = {"commentary": "Market commentary", "news": "News", "report": "Report"}.get(n["category"], n["category"])
        with st.container(border=True):
            st.markdown(f"**{n['title']}**  \n<small>{kind} &middot; {n['published_at'][:10]} &middot; {n['source_name']}"
                        f"{' &middot; SYNTHETIC' if n['is_synthetic'] else ''}</small>", unsafe_allow_html=True)
            st.write(n["summary"])
            if n["url"]:
                st.markdown(f"[Source link]({n['url']})")
