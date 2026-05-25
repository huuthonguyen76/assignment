import json
from datetime import datetime
from pathlib import Path
import pytest
from backend.decoder import UIState, apply_event
from backend.schema import (
    AgentEvent, EventType,
    RunStartedPayload, NodeCreatedPayload, NodeStatusChangedPayload,
    ThinkingPayload, ToolStartedPayload, ToolFinishedPayload,
    AskUserPayload, AskUserAnsweredPayload,
    ArtifactCreatedPayload, SubagentCompletedPayload,
    ErrorPayload, RunCompletedPayload,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _e(seq, type_, payload, node_id="root", parent=None):
    return AgentEvent(seq=seq, run_id="r1", node_id=node_id,
                      parent_node_id=parent, ts=datetime.utcnow(),
                      type=type_, payload=payload)


def test_run_started_creates_root():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    assert s.tree.id == "root"
    assert s.tree.title == "X"
    assert s.tree.status == "running"
    assert s.last_seq == 0


def test_node_created_attaches_under_parent():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    apply_event(s, _e(1, EventType.NODE_CREATED,
                      NodeCreatedPayload(role="lead-analyst", status="running"),
                      node_id="lead", parent="root"))
    assert s.tree.children[0].id == "lead"
    assert s.tree.children[0].role == "lead-analyst"


def test_node_status_transitions():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    apply_event(s, _e(1, EventType.NODE_CREATED,
                      NodeCreatedPayload(role="lead-analyst", status="running"),
                      node_id="lead", parent="root"))
    apply_event(s, _e(2, EventType.NODE_STATUS_CHANGED,
                      NodeStatusChangedPayload(status="completed"),
                      node_id="lead", parent="root"))
    assert s.tree.find("lead").status == "completed"


def test_ask_user_sets_pending_and_marks_awaiting():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    apply_event(s, _e(1, EventType.NODE_CREATED,
                      NodeCreatedPayload(role="lead-analyst", status="running"),
                      node_id="lead", parent="root"))
    apply_event(s, _e(2, EventType.ASK_USER,
                      AskUserPayload(question_id="q1", question="why?",
                                     asked_by="lead"),
                      node_id="lead", parent="root"))
    assert s.pending_question.question_id == "q1"
    assert s.tree.find("lead").status == "awaiting_user"
    apply_event(s, _e(3, EventType.ASK_USER_ANSWERED,
                      AskUserAnsweredPayload(question_id="q1", answer="ok"),
                      node_id="lead", parent="root"))
    assert s.pending_question is None


def test_tool_events_append_to_node_events():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    apply_event(s, _e(1, EventType.NODE_CREATED,
                      NodeCreatedPayload(role="lead-analyst", status="running"),
                      node_id="lead", parent="root"))
    apply_event(s, _e(2, EventType.TOOL_STARTED,
                      ToolStartedPayload(tool_name="search",
                                         tool_call_id="t1", input={"q": "x"}),
                      node_id="lead", parent="root"))
    apply_event(s, _e(3, EventType.TOOL_FINISHED,
                      ToolFinishedPayload(tool_call_id="t1",
                                          output_summary="...", ok=True),
                      node_id="lead", parent="root"))
    assert len(s.tree.find("lead").events) == 2


def test_artifact_created_lists_under_node_and_globally():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    apply_event(s, _e(1, EventType.NODE_CREATED,
                      NodeCreatedPayload(role="web-researcher",
                                         title="sub", status="running"),
                      node_id="r1", parent="root"))
    apply_event(s, _e(2, EventType.ARTIFACT_CREATED,
                      ArtifactCreatedPayload(artifact_id="a1", name="n.md",
                                             artifact_kind="markdown",
                                             bytes=100),
                      node_id="r1", parent="root"))
    assert s.artifacts[0].artifact_id == "a1"
    assert s.tree.find("r1").artifact_ids == ["a1"]


def test_error_attaches_to_referenced_node():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    apply_event(s, _e(1, EventType.NODE_CREATED,
                      NodeCreatedPayload(role="web-researcher",
                                         status="running"),
                      node_id="r1", parent="root"))
    apply_event(s, _e(2, EventType.ERROR,
                      ErrorPayload(where="tool", message="boom",
                                   recoverable=False, node_id_ref="r1"),
                      node_id="r1", parent="root"))
    assert s.tree.find("r1").errors[0].message == "boom"


def test_run_completed_marks_tree_and_sets_final():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    apply_event(s, _e(1, EventType.RUN_COMPLETED,
                      RunCompletedPayload(final_artifact_id="final.md")))
    assert s.tree.status == "completed"
    assert s.final_artifact_id == "final.md"


def test_gap_in_seq_raises():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    with pytest.raises(ValueError, match="seq gap"):
        apply_event(s, _e(5, EventType.RUN_COMPLETED,
                          RunCompletedPayload(final_artifact_id="f.md")))


def test_replay_idempotent_when_cursor_advanced():
    """Applying events 1..N then N+1..M equals applying 1..M once."""
    a = UIState()
    b = UIState()
    events = _canonical_event_list()
    for e in events:
        apply_event(a, e)
    half = len(events) // 2
    for e in events[:half]:
        apply_event(b, e)
    # cursor is now b.last_seq; replay from half onward
    for e in events[half:]:
        apply_event(b, e)
    # both trees should be identical shape
    assert _tree_summary(a.tree) == _tree_summary(b.tree)
    assert a.last_seq == b.last_seq


def _canonical_event_list() -> list[AgentEvent]:
    out = []
    out.append(_e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    out.append(_e(1, EventType.NODE_CREATED,
                  NodeCreatedPayload(role="lead-analyst", status="running"),
                  node_id="lead", parent="root"))
    out.append(_e(2, EventType.THINKING,
                  ThinkingPayload(text="planning..."),
                  node_id="lead", parent="root"))
    out.append(_e(3, EventType.NODE_CREATED,
                  NodeCreatedPayload(role="web-researcher", title="sub1",
                                     status="queued"),
                  node_id="r1", parent="lead"))
    out.append(_e(4, EventType.NODE_CREATED,
                  NodeCreatedPayload(role="web-researcher", title="sub2",
                                     status="queued"),
                  node_id="r2", parent="lead"))
    out.append(_e(5, EventType.NODE_STATUS_CHANGED,
                  NodeStatusChangedPayload(status="completed"),
                  node_id="r1", parent="lead"))
    out.append(_e(6, EventType.NODE_STATUS_CHANGED,
                  NodeStatusChangedPayload(status="completed"),
                  node_id="r2", parent="lead"))
    out.append(_e(7, EventType.RUN_COMPLETED,
                  RunCompletedPayload(final_artifact_id="f.md")))
    return out


def _tree_summary(n) -> list:
    return [n.id, n.role, n.status,
            [_tree_summary(c) for c in n.children]]


def test_two_parallel_researchers_have_independent_event_lists():
    """Same role, same parent, interleaved events → each lands in its own node."""
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    apply_event(s, _e(1, EventType.NODE_CREATED,
                      NodeCreatedPayload(role="lead-analyst", status="running"),
                      node_id="lead", parent="root"))
    apply_event(s, _e(2, EventType.NODE_CREATED,
                      NodeCreatedPayload(role="web-researcher", title="A",
                                         status="queued"),
                      node_id="rA", parent="lead"))
    apply_event(s, _e(3, EventType.NODE_CREATED,
                      NodeCreatedPayload(role="web-researcher", title="B",
                                         status="queued"),
                      node_id="rB", parent="lead"))
    # Interleave thinking events from both
    apply_event(s, _e(4, EventType.THINKING,
                      ThinkingPayload(text="A1"),
                      node_id="rA", parent="lead"))
    apply_event(s, _e(5, EventType.THINKING,
                      ThinkingPayload(text="B1"),
                      node_id="rB", parent="lead"))
    apply_event(s, _e(6, EventType.THINKING,
                      ThinkingPayload(text="A2"),
                      node_id="rA", parent="lead"))
    apply_event(s, _e(7, EventType.THINKING,
                      ThinkingPayload(text="B2"),
                      node_id="rB", parent="lead"))

    a_events = [e.payload.text for e in s.tree.find("rA").events]
    b_events = [e.payload.text for e in s.tree.find("rB").events]
    assert a_events == ["A1", "A2"]
    assert b_events == ["B1", "B2"]


def test_double_apply_is_noop():
    s = UIState()
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="X")))
    apply_event(s, _e(0, EventType.RUN_STARTED, RunStartedPayload(topic="Y")))
    # Second apply was a no-op (seq 0 already applied); topic unchanged
    assert s.tree.title == "X"
