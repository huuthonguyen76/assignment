"""Right-column tab: flat artifact list + inline preview."""
from __future__ import annotations
import streamlit as st
from streamlit_app import api_client
from streamlit_app.state import get_runs, find_run


_KIND_LANG = {"sql": "sql", "yaml": "yaml", "json": "json"}


def render_artifacts_tab():
    runs = get_runs()
    if not runs:
        st.info("No artifacts yet.")
        return
    options = [r["run_id"] for r in runs]
    labels = {r["run_id"]: r["topic"] for r in runs}
    chosen = st.selectbox("Run", options,
                          format_func=lambda r: labels[r],
                          index=len(options) - 1)
    arts = api_client.list_artifacts(chosen)
    if not arts:
        st.info("Run has no artifacts yet.")
        return
    st.dataframe(arts, use_container_width=True)
    art_id = st.selectbox("Preview",
                          [a["id"] for a in arts],
                          format_func=lambda i:
                              next(a["name"] for a in arts if a["id"] == i))
    info = next(a for a in arts if a["id"] == art_id)
    content = api_client.get_artifact_bytes(chosen, art_id)
    if info["kind"] == "markdown":
        st.markdown(content.decode("utf-8"))
    elif info["kind"] == "image":
        st.image(content)
    elif info["kind"] in _KIND_LANG:
        st.code(content.decode("utf-8"), language=_KIND_LANG[info["kind"]])
    else:
        st.code(content.decode("utf-8"))
    st.download_button("Download", content, file_name=info["name"])


def render_final_brief_tab():
    runs = get_runs()
    completed = [r for r in runs if r["ui_state"].final_artifact_id]
    if not completed:
        st.info("No completed run yet.")
        return
    latest = completed[-1]
    aid = latest["ui_state"].final_artifact_id
    if not aid:
        st.info("Run completed without a final artifact.")
        return
    content = api_client.get_artifact_bytes(latest["run_id"], aid)
    st.markdown(content.decode("utf-8"))
