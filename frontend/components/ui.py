"""Shared UI styling and widgets (corporate: white, navy headings, restrained green accents)."""
from __future__ import annotations

import html

import streamlit as st

NAVY, GREEN, AMBER, RED, GREY = "#0B2545", "#1B7F4C", "#B26B00", "#B00020", "#5B6770"

CSS = f"""
<style>
.stApp {{ background: #FFFFFF; }}
h1, h2, h3, h4 {{ color: {NAVY} !important; font-family: 'Segoe UI', Roboto, sans-serif; }}
[data-testid="stSidebar"] {{ background: #F4F7FA; }}
.rr-card {{ border: 1px solid #DDE3EA; border-left: 4px solid {GREEN}; border-radius: 8px; padding: 12px 14px;
           margin-bottom: 12px; background: #FFFFFF; box-shadow: 0 1px 2px rgba(11,37,69,.06); min-height: 190px; }}
.rr-card.synthetic {{ border-left-color: {AMBER}; }}
.rr-card.stale {{ border-left-color: {GREY}; }}
.rr-title {{ color: {NAVY}; font-weight: 600; font-size: 0.98rem; margin-bottom: 2px; }}
.rr-sub {{ color: {GREY}; font-size: 0.80rem; }}
.rr-price {{ color: {NAVY}; font-size: 1.45rem; font-weight: 700; margin: 6px 0 2px 0; }}
.rr-unit {{ color: {GREY}; font-size: 0.85rem; font-weight: 500; }}
.rr-meta {{ color: #33414E; font-size: 0.78rem; line-height: 1.35rem; }}
.rr-badge {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 0.70rem; font-weight: 600;
            margin-right: 4px; }}
.b-syn {{ background: #FFF3DC; color: {AMBER}; }}
.b-live {{ background: #E3F4EA; color: {GREEN}; }}
.b-hist {{ background: #E8EEF6; color: {NAVY}; }}
.b-stale {{ background: #EEF0F2; color: {GREY}; }}
.b-today {{ background: #E3F4EA; color: {GREEN}; }}
.rr-banner {{ background: #FFF8E8; border: 1px solid #F1D9A6; color: #6B4A00; padding: 8px 12px; border-radius: 6px;
             font-size: 0.85rem; margin-bottom: 12px; }}
</style>
"""


def setup(title: str, subtitle: str = "") -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.title(title)
    if subtitle:
        st.caption(subtitle)


def synthetic_banner() -> None:
    st.markdown("<div class='rr-banner'><b>Demo mode notice:</b> rows marked <b>SYNTHETIC</b> are fictional demonstration "
                "prices generated for this project. Prices are shown as the <b>latest available</b> observation with "
                "their original date &mdash; never relabelled as today's rate.</div>", unsafe_allow_html=True)


def badges(r: dict) -> str:
    out = []
    if r.get("is_synthetic"):
        out.append("<span class='rr-badge b-syn'>SYNTHETIC</span>")
    elif r.get("data_nature") == "historical":
        out.append("<span class='rr-badge b-hist'>HISTORICAL / MONTHLY</span>")
    else:
        out.append(f"<span class='rr-badge b-live'>{html.escape(r.get('data_nature', '').upper())}</span>")
    if r.get("is_today"):
        out.append("<span class='rr-badge b-today'>TODAY</span>")
    elif r.get("is_stale"):
        out.append("<span class='rr-badge b-stale'>STALE</span>")
    return "".join(out)


def price_card(r: dict) -> None:
    e = lambda x: html.escape(str(x if x is not None else ""))  # noqa: E731
    cls = "synthetic" if r.get("is_synthetic") else "stale" if r.get("is_stale") else ""
    st.markdown(f"""
<div class='rr-card {cls}'>
  <div class='rr-title'>{e(r['product_name'])}</div>
  <div class='rr-sub'>{e(r['variety'])} &middot; {e(r['grade'])}</div>
  <div class='rr-price'>{r['price']:,.0f} <span class='rr-unit'>{e(r['original_unit'])}</span></div>
  <div class='rr-meta'>
    &#128205; {e(r['market'])}, {e(r['city'])}<br/>
    &#128339; Observed {e(r['observation_date'])} &middot; {e(r['freshness_label'])}<br/>
    &#128196; {e(r['source_name'])}<br/>
    &#9989; {e(r['verification_status'])} &middot; {e(r['price_category'])}<br/>
    {badges(r)}
  </div>
</div>""", unsafe_allow_html=True)


def cards(rows: list[dict], per_row: int = 3) -> None:
    for i in range(0, len(rows), per_row):
        cols = st.columns(per_row)
        for c, r in zip(cols, rows[i:i + per_row]):
            with c:
                price_card(r)


def direction_chip(label: str) -> str:
    color = {"Rising": GREEN, "Falling": RED, "Stable": NAVY, "Mixed": AMBER}.get(label, GREY)
    arrow = {"Rising": "&#9650;", "Falling": "&#9660;", "Stable": "&#9654;", "Mixed": "&#8645;"}.get(label, "&#8230;")
    return f"<span style='color:{color};font-weight:600'>{arrow} {html.escape(label)}</span>"
