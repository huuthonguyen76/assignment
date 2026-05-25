"""Render the trace tree. Siblings that are simultaneously `running` render
side-by-side via st.columns; the rest stack vertically."""
from __future__ import annotations
import streamlit as st
from backend.decoder import Node
from streamlit_app import api_client


_STATUS_ICON = {
    "queued": "◯",
    "running": "◐",
    "awaiting_user": "⏸",
    "completed": "✓",
    "failed": "✗",
    "skipped": "—",
}


def render_tree(node: Node, run_id: str, depth: int = 0):
    """Top-level entry point. Renders one Node and all its descendants."""
    _render_node(node, run_id, depth)


def _render_node(node: Node, run_id: str, depth: int):
    icon = _STATUS_ICON.get(node.status, "?")
    label = f"{icon} **{node.role}**"
    if node.title:
        label += f" — {node.title}"
    expanded = node.status in ("running", "awaiting_user", "failed")
    with st.expander(label, expanded=expanded):
        _render_node_body(node, run_id)
        # Children: side-by-side if multiple are running concurrently
        running_children = [c for c in node.children if c.status == "running"]
        if len(running_children) >= 2 and len(running_children) == len(
                [c for c in node.children if c.status != "queued"]):
            cols = st.columns(len(node.children))
            for col, child in zip(cols, node.children):
                with col:
                    _render_node(child, run_id, depth + 1)
        else:
            for child in node.children:
                _render_node(child, run_id, depth + 1)


def _render_node_body(node: Node, run_id: str):
    if node.summary:
        st.caption(node.summary)
    if node.errors:
        for err in node.errors:
            st.error(f"[{err.where}] {err.message}")
        if node.role == "web-researcher":
            if st.button(f"Retry this researcher", key=f"retry_{node.id}"):
                api_client.retry_node(run_id, node.id)
                st.rerun()
    for ev in node.events:
        t = ev.type.value
        if t == "thinking":
            st.markdown(f"> _thinking:_ {ev.payload.text}")
        elif t == "agent_message":
            st.markdown(f"💬 {ev.payload.text}")
        elif t == "tool_started":
            inp_preview = str(ev.payload.input)[:120]
            st.markdown(
                f"🔧 `{ev.payload.tool_name}` started — `{inp_preview}`")
        elif t == "tool_finished":
            ok = "✓" if ev.payload.ok else "✗"
            st.markdown(
                f"{ok} `{ev.payload.tool_call_id[:8]}` → "
                f"{ev.payload.output_summary[:120]}")
    if node.artifact_ids:
        st.caption(f"📎 {len(node.artifact_ids)} artifact(s)")
