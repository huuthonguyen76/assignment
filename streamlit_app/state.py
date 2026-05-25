"""Typed accessors for st.session_state. Keep this file boring."""
from __future__ import annotations
import uuid
import streamlit as st
from backend.decoder import UIState


def get_session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    return st.session_state.session_id


def get_runs() -> list[dict]:
    """Each run: {run_id, topic, ui_state: UIState, started_at}"""
    if "runs" not in st.session_state:
        st.session_state.runs = []
    return st.session_state.runs


def add_run(run_id: str, topic: str):
    runs = get_runs()
    runs.append({"run_id": run_id, "topic": topic, "ui_state": UIState()})


def find_run(run_id: str) -> dict | None:
    for r in get_runs():
        if r["run_id"] == run_id:
            return r
    return None


def get_poll_ms() -> int:
    import os
    return int(os.getenv("APP_POLL_INTERVAL_MS", "500"))


def latest_activity_line() -> str | None:
    """Walk all runs, find most recent thinking/tool_started across nodes."""
    latest = None
    latest_seq = -1
    for r in get_runs():
        ui = r["ui_state"]
        if ui.tree is None:
            continue

        def _walk(node):
            nonlocal latest, latest_seq
            for ev in node.events:
                if ev.type.value in ("thinking", "tool_started")\
                        and ev.seq > latest_seq:
                    latest_seq = ev.seq
                    if ev.type.value == "thinking":
                        latest = f"◐ {node.role}"
                        if node.title:
                            latest += f" [{node.title}]"
                        latest += f": {ev.payload.text[:60]}"
                    else:
                        latest = f"◐ {node.role}"
                        if node.title:
                            latest += f" [{node.title}]"
                        latest += f": calling {ev.payload.tool_name}"
            for c in node.children:
                _walk(c)
        _walk(ui.tree)
    return latest
