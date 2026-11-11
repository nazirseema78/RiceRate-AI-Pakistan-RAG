import pandas as pd
import plotly.express as px
import streamlit as st

from components.api_client import safe_get
from components.ui import setup, synthetic_banner

setup("Price Comparison", "Lower Punjab vs Karachi - only equivalent products, grades and price categories are compared")
inc = st.session_state.get("include_synthetic", True)
if inc:
    synthetic_banner()

products = safe_get("/api/products") or {"items": []}
f1, f2, f3, f4, f5 = st.columns(5)
cities = f1.multiselect("Lower Punjab cities", ["Multan", "Muzaffargarh", "Bahawalpur", "Rahim Yar Khan"],
                        default=["Multan", "Muzaffargarh", "Bahawalpur", "Rahim Yar Khan"])
ptype = f2.selectbox("Product type", ["All", "rice", "broken_rice", "paddy"])
varieties = sorted({p["variety"] for p in products["items"] if ptype in ("All", p["product_type"])})
variety = f3.selectbox("Variety", ["All"] + varieties)
grades = sorted({p["grade"] for p in products["items"] if variety in ("All", p["variety"])})
grade = f4.selectbox("Grade", ["All"] + grades)
as_of = f5.date_input("Price date (latest on or before)", value=None)

res = safe_get("/api/prices/compare", {"cities": ",".join(cities), "product_type": ptype, "variety": variety, "grade": grade,
                                       "as_of": as_of.isoformat() if as_of else None, "include_synthetic": inc})
if not res:
    st.stop()
st.caption(res["method"])
comp = pd.DataFrame(res["comparisons"])
if comp.empty:
    st.info("No equivalent Lower Punjab / Karachi pairs for this filter. Paddy is not traded in the Karachi dataset, "
            "so paddy cannot be compared with Karachi.")
else:
    valid = comp[comp["valid"]]
    if not valid.empty:
        fig = px.bar(valid, x="product_name", y="difference_pct", color="city", barmode="group",
                     labels={"difference_pct": "Karachi premium over city (%)", "product_name": ""},
                     color_discrete_sequence=["#0B2545", "#1B7F4C", "#5B8DB8", "#9BC53D"])
        fig.update_layout(plot_bgcolor="white", height=380, margin=dict(t=30, b=10))
        st.plotly_chart(fig, width="stretch")
    show = comp[["product_name", "grade", "price_category", "city", "city_price", "city_unit", "city_date", "karachi_price",
                 "karachi_unit", "karachi_date", "city_normalized", "karachi_normalized", "normalized_unit", "difference",
                 "difference_pct", "note"]].rename(columns={"difference": "diff (PKR/kg)", "difference_pct": "diff %"})
    st.dataframe(show, width="stretch", hide_index=True)
if res["unmatched"]:
    with st.expander(f"{len(res['unmatched'])} observations without an equivalent Karachi product (not compared)"):
        st.dataframe(pd.DataFrame(res["unmatched"]), width="stretch", hide_index=True)

st.subheader("Price history")
c1, c2 = st.columns(2)
pk_opts = {p["name"]: p["product_key"] for p in products["items"]}
sel = c1.selectbox("Product", list(pk_opts) or ["-"])
days = c2.select_slider("Days", [7, 15, 30, 45, 90, 365], value=30)
hist = safe_get("/api/prices/history", {"product_key": pk_opts.get(sel), "days": days, "include_synthetic": inc})
if hist and hist["items"]:
    h = pd.DataFrame(hist["items"])
    h["series"] = h["city"] + " (" + h["original_unit"] + ")"
    fig = px.line(h, x="price_date", y="normalized_price", color="series", markers=True,
                  labels={"normalized_price": f"Price ({h['normalized_unit'].iloc[0]})", "price_date": ""})
    fig.update_layout(plot_bgcolor="white", height=380)
    st.plotly_chart(fig, width="stretch")
else:
    st.info("No history for this product.")
