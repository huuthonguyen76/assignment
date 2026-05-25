"""Renders the pending ask_user question (if any) as a form."""
from __future__ import annotations
import streamlit as st
from streamlit_app import api_client
from streamlit_app.state import find_run


def render_pending_question(run_id: str):
    run = find_run(run_id)
    if not run:
        return
    pq = run["ui_state"].pending_question
    if pq is None:
        return
    with st.chat_message("assistant"):
        st.warning(pq.question)
    with st.form(f"answer_{pq.question_id}"):
        if pq.options:
            choice = st.radio("Pick one", pq.options, key=f"r_{pq.question_id}")
        else:
            choice = st.text_input("Your answer", key=f"t_{pq.question_id}")
        if st.form_submit_button("Send"):
            api_client.submit_answer(run_id, pq.question_id, choice)
            st.rerun()
