"""Pure decoder. Consumes normalized AgentEvent → mutates UIState.

This module is the asset. Backend asserts against it. Streamlit renders from it.
Both sides import the SAME function so behavior is identical.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from backend.schema import (
    AgentEvent, NodeRole, NodeStatus, ErrorPayload, AskUserPayload,
    ArtifactCreatedPayload,
)


@dataclass
class Node:
    id: str
    role: NodeRole
    title: str | None
    status: NodeStatus
    parent_id: str | None = None
    summary: str | None = None
    children: list["Node"] = field(default_factory=list)
    events: list[AgentEvent] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    errors: list[ErrorPayload] = field(default_factory=list)

    def find(self, node_id: str) -> Optional["Node"]:
        if self.id == node_id:
            return self
        for c in self.children:
            hit = c.find(node_id)
            if hit is not None:
                return hit
        return None


@dataclass
class UIState:
    tree: Node | None = None
    pending_question: AskUserPayload | None = None
    artifacts: list[ArtifactCreatedPayload] = field(default_factory=list)
    final_artifact_id: str | None = None
    last_seq: int = -1


from backend.schema import EventType


def apply_event(state: UIState, ev: AgentEvent) -> None:
    """Pure: mutate state in place. Idempotent under cursor advance."""
    # Skip already-applied events (replay safety)
    if ev.seq <= state.last_seq:
        return
    # Enforce gap-free monotonic
    if ev.seq != state.last_seq + 1:
        raise ValueError(
            f"seq gap: expected {state.last_seq + 1}, got {ev.seq}"
        )

    t = ev.type
    p = ev.payload

    if t == EventType.RUN_STARTED:
        state.tree = Node(id=ev.node_id, role="root", title=p.topic,
                          status="running")
    elif t == EventType.NODE_CREATED:
        parent = state.tree.find(ev.parent_node_id) if state.tree else None
        if parent is None:
            raise ValueError(f"unknown parent {ev.parent_node_id}")
        parent.children.append(Node(
            id=ev.node_id, role=p.role, title=p.title,
            status=p.status, parent_id=ev.parent_node_id,
        ))
    elif t == EventType.NODE_STATUS_CHANGED:
        node = state.tree.find(ev.node_id)
        if node is None:
            raise ValueError(f"unknown node {ev.node_id}")
        node.status = p.status
    elif t in (EventType.THINKING, EventType.AGENT_MESSAGE,
               EventType.TOOL_STARTED, EventType.TOOL_FINISHED):
        node = state.tree.find(ev.node_id)
        if node is None:
            raise ValueError(f"unknown node {ev.node_id}")
        node.events.append(ev)
    elif t == EventType.ASK_USER:
        state.pending_question = p
        node = state.tree.find(ev.node_id)
        if node is not None:
            node.status = "awaiting_user"
    elif t == EventType.ASK_USER_ANSWERED:
        state.pending_question = None
    elif t == EventType.ARTIFACT_CREATED:
        state.artifacts.append(p)
        node = state.tree.find(ev.node_id)
        if node is not None:
            node.artifact_ids.append(p.artifact_id)
    elif t == EventType.SUBAGENT_COMPLETED:
        node = state.tree.find(ev.node_id)
        if node is not None:
            node.summary = p.summary
    elif t == EventType.ERROR:
        target = state.tree.find(p.node_id_ref) if state.tree else None
        if target is not None:
            target.errors.append(p)
    elif t == EventType.RUN_COMPLETED:
        if state.tree:
            state.tree.status = "completed"
        state.final_artifact_id = p.final_artifact_id
    else:
        raise AssertionError(f"unhandled event type {t}")

    state.last_seq = ev.seq
