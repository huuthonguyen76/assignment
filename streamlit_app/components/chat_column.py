"""Chat column: run-stack expanders + activity ticker + new-message input."""
from __future__ import annotations
import streamlit as st
from streamlit_app.state import (
    get_session_id, get_runs, add_run, latest_activity_line,
)
from streamlit_app import api_client
from streamlit_app.components.ask_user_form import render_pending_question
from streamlit_app.components.trace_tree import render_tree


def render_chat_column():
    st.subheader("Chat")
    ticker = latest_activity_line()
    if ticker:
        st.caption(ticker)

    # User input
    topic = st.chat_input("Ask a research question…")
    if topic:
        run_id = api_client.start_run(get_session_id(), topic)
        add_run(run_id, topic)
        st.rerun()

    # Render run stack (newest first; only newest auto-expands)
    runs = get_runs()
    for i, run in enumerate(reversed(runs)):
        is_active = (run["ui_state"].tree is None
                     or run["ui_state"].tree.status != "completed")
        with st.expander(f"Run: {run['topic']}", expanded=is_active):
            render_pending_question(run["run_id"])
            if run["ui_state"].tree is not None:
                render_tree(run["ui_state"].tree, run["run_id"])
            else:
                st.info("Starting…")
