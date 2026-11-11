import pandas as pd
import streamlit as st

from components.api_client import BackendError, cached_get, post, safe_get
from components.ui import setup

setup("Data Source Status", "Which providers are live, historical or synthetic - and when they last delivered data")

data = safe_get("/api/sources/status")
if not data:
    st.stop()

sch = data["scheduler"]
c1, c2, c3 = st.columns(3)
c1.metric("Scheduler", "running" if sch["running_in_this_process"] else ("enabled" if sch["enabled"] else "disabled"))
c2.metric("Scheduled checks (PKT)", ", ".join(f"{h}:00" for h in sch["hours_pkt"].split(",")))
c3.metric("Next run", (sch["next_run"] or "-")[:16].replace("T", " "))
st.caption("A scheduled check does not guarantee a new price: if a source has not published anything new, the previous "
           "observation is kept with its original date.")

NATURE = {"synthetic": "Synthetic (fictional demo)", "live": "Live source", "historical": "Historical / periodic", "imported": "Manual import"}
df = pd.DataFrame(data["sources"])
if not df.empty:
    df["data type"] = df["data_nature"].map(NATURE).fillna(df["data_nature"])
    st.dataframe(df[["name", "provider_key", "data type", "enabled", "requires_api_key", "availability_status",
                     "last_attempted_at", "last_success_at", "last_observation_at", "observation_count", "last_error", "url"]],
                 width="stretch", hide_index=True,
                 column_config={"url": st.column_config.LinkColumn("url")})

st.subheader("Recent ingestion runs")
runs = pd.DataFrame(data["recent_runs"])
if not runs.empty:
    st.dataframe(runs[["provider_key", "trigger", "started_at", "status", "fetched", "inserted", "duplicates", "rejected", "message"]],
                 width="stretch", hide_index=True)

st.subheader("Manual refresh (authorised users)")
st.caption(f"Requires the backend ADMIN_TOKEN. Rate-limited to one refresh every {data['refresh_min_interval_seconds']} seconds.")
with st.form("refresh"):
    token = st.text_input("Admin token", type="password")
    force = st.checkbox("Ignore per-source politeness windows (uses API quota)")
    rebuild = st.checkbox("Rebuild document vector index from scratch")
    if st.form_submit_button("Refresh sources now"):
        try:
            with st.spinner("Checking sources..."):
                res = post("/api/admin/refresh", {"force": force, "rebuild_index": rebuild}, headers={"X-Admin-Token": token})
            st.success("Refresh completed")
            st.dataframe(pd.DataFrame(res["results"]), width="stretch", hide_index=True)
            cached_get.clear()
        except BackendError as e:
            st.error(str(e))
