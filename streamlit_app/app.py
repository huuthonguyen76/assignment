"""Deep Analyst — Streamlit UI."""
from __future__ import annotations
from dotenv import load_dotenv

load_dotenv(override=True)

import streamlit as st
from backend.decoder import apply_event
from streamlit_app.state import get_runs, find_run, get_poll_ms
from streamlit_app import api_client
from streamlit_app.components.chat_column import render_chat_column
from streamlit_app.components.artifacts_tab import (
    render_artifacts_tab, render_final_brief_tab,
)


st.set_page_config(page_title="Deep Analyst", layout="wide")
st.title("🔬 Deep Analyst — Research Intelligence Platform")


def _has_active_runs() -> bool:
    for run in get_runs():
        ui = run["ui_state"]
        if ui.tree is None or ui.tree.status not in ("completed", "failed"):
            return True
    return False


@st.fragment(
    run_every=f"{get_poll_ms()}ms" if _has_active_runs() else None)
def poll_all_runs():
    """Poll every active run for new events and apply them to UIState."""
    for run in get_runs():
        ui = run["ui_state"]
        if ui.tree is not None and ui.tree.status in ("completed", "failed"):
            continue   # done; stop polling
        from_seq = ui.last_seq + 1
        try:
            events = api_client.fetch_events(run["run_id"], from_seq=from_seq)
        except Exception as e:
            st.toast(f"Poll error: {e}", icon="⚠️")
            return
        applied = 0
        for ev in events:
            try:
                apply_event(ui, ev)
                applied += 1
            except ValueError:
                # gap / unknown node — full re-pull from 0
                ui.__init__()
                events_full = api_client.fetch_events(
                    run["run_id"], from_seq=0, limit=10000)
                for ev2 in events_full:
                    apply_event(ui, ev2)
                applied = len(events_full)
                break
        # Fragment reruns do not redraw widgets outside the fragment; refresh
        # the page when new events land so chat/trace show ask_user, tree, etc.
        if applied:
            st.rerun()


col_chat, col_right = st.columns([1, 1])

with col_chat:
    render_chat_column()

with col_right:
    tab_trace, tab_artifacts, tab_brief = st.tabs(
        ["Trace", "Artifacts", "Final Brief"])
    with tab_trace:
        st.caption(
            "Trace view also appears inline in the chat column. "
            "This tab is for focused inspection.")
        runs = get_runs()
        if runs:
            from streamlit_app.components.trace_tree import render_tree
            active = next((r for r in reversed(runs)
                           if r["ui_state"].tree is not None), None)
            if active and active["ui_state"].tree:
                render_tree(
                    active["ui_state"].tree,
                    active["run_id"],
                    key_prefix=f"trace_{active['run_id']}_",
                )
    with tab_artifacts:
        render_artifacts_tab()
    with tab_brief:
        render_final_brief_tab()

poll_all_runs()
