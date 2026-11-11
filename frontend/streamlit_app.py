"""RiceRate AI Pakistan - Streamlit frontend.

Run from the project root (with the FastAPI backend already running):
    streamlit run frontend/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(page_title="RiceRate AI Pakistan", page_icon="\U0001F33E", layout="wide")

from components.api_client import BACKEND_URL, get, BackendError  # noqa: E402

PAGES = Path(__file__).resolve().parent / "pages"
nav = st.navigation([
    st.Page(PAGES / "1_Market_Overview.py", title="Market Overview", icon="\U0001F4CA", default=True),
    st.Page(PAGES / "2_Price_Comparison.py", title="Price Comparison", icon="⚖️"),
    st.Page(PAGES / "3_International_Market.py", title="International Market", icon="\U0001F30F"),
    st.Page(PAGES / "4_RiceRate_AI_Chatbot.py", title="RiceRate AI Chatbot", icon="\U0001F4AC"),
    st.Page(PAGES / "5_News_and_Trends.py", title="News & Trends", icon="\U0001F4F0"),
    st.Page(PAGES / "6_Data_Source_Status.py", title="Data Source Status", icon="\U0001F6F0️"),
])

with st.sidebar:
    st.markdown("### \U0001F33E RiceRate AI Pakistan")
    st.caption("Rice price intelligence - Lower Punjab, Karachi & international markets")
    try:
        h = get("/api/health", timeout=5)
        st.success(f"Backend connected - {h['price_observations']:,} observations, {h['vector_chunks']} document chunks")
    except BackendError:
        st.error(f"Backend not reachable at {BACKEND_URL}")
    st.session_state.setdefault("include_synthetic", True)
    st.toggle("Include synthetic demo data", key="include_synthetic",
              help="Turn off to see only live / historical / imported observations from real sources.")

nav.run()
