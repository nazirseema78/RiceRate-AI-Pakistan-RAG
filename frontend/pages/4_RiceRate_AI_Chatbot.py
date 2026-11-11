import pandas as pd
import streamlit as st

from components.api_client import BackendError, post
from components.ui import setup

setup("RiceRate AI Chatbot", "Ask in English or Pakistani Urdu - exact prices come from the price database, explanations from market reports")

EXAMPLES = [
    "Aaj Multan mein 1121 paddy ka latest available rate kya hai?",
    "Karachi mein broken rice ka latest verified quote kya hai?",
    "Aaj Punjab aur Karachi ke rice rates mein kya farq hai?",
    "International rice market mein aaj kya updates hain?",
    "Pichlay 7 din mein 1121 rice ka rate barha hai ya kam hua?",
    "Kya international rice prices girnay ke signals hain?",
    "Latest available rice market report ka summary do.",
    "Karachi mein rice rates kyun change ho rahay hain?",
]

st.session_state.setdefault("chat", [])
with st.sidebar:
    st.markdown("**Example questions**")
    for i, ex in enumerate(EXAMPLES):
        if st.button(ex, key=f"ex{i}", width="stretch"):
            st.session_state["pending_q"] = ex
    if st.button("Clear chat", type="secondary"):
        st.session_state["chat"] = []


def render_meta(meta: dict) -> None:
    st.caption(f"Route: **{meta['route']}** · language: {meta['language']} · LLM used: {meta.get('llm_provider_used') or 'no (retrieval-only)'}")
    if meta["sources"]:
        with st.expander(f"Sources and observation dates ({len(meta['sources'])})"):
            df = pd.DataFrame(meta["sources"])
            cols = [c for c in ["type", "name", "document", "date", "page", "score", "label"] if c in df.columns]
            st.dataframe(df[cols], width="stretch", hide_index=True)
    if meta.get("retrieved_chunks"):
        with st.expander("Retrieved document chunks"):
            for c in meta["retrieved_chunks"]:
                st.markdown(f"**{c['source']}** (similarity {c['score']:.3f})")
                st.text(c["text"][:700])


for msg in st.session_state["chat"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("meta"):
            render_meta(msg["meta"])

question = st.chat_input("Sawal likhein / Type your question about rice prices...")
question = question or st.session_state.pop("pending_q", None)
if question:
    st.session_state["chat"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("Searching price database and market reports..."):
            history = [{"role": m["role"], "content": m["content"][:5000]} for m in st.session_state["chat"][:-1]][-8:]
            try:
                res = post("/api/chat", {"question": question, "history": history})
                st.markdown(res["answer"])
                render_meta(res)
                st.session_state["chat"].append({"role": "assistant", "content": res["answer"], "meta": res})
            except BackendError as e:
                st.error(str(e))
