from datetime import datetime
import pytest
from pydantic import ValidationError
from backend.schema import (
    AgentEvent, EventType,
    RunStartedPayload, NodeCreatedPayload, NodeStatusChangedPayload,
    ThinkingPayload, AgentMessagePayload,
    ToolStartedPayload, ToolFinishedPayload,
    AskUserPayload, AskUserAnsweredPayload,
    ArtifactCreatedPayload, SubagentCompletedPayload,
    ErrorPayload, RunCompletedPayload,
)


def _ev(type_, payload):
    return AgentEvent(
        seq=1, run_id="r1", node_id="n1", parent_node_id=None,
        ts=datetime.utcnow(), type=type_, payload=payload,
    )


def test_run_started_roundtrip():
    e = _ev(EventType.RUN_STARTED, RunStartedPayload(topic="Anthropic vs OpenAI"))
    data = e.model_dump_json()
    e2 = AgentEvent.model_validate_json(data)
    assert e2.payload.topic == "Anthropic vs OpenAI"
    assert e2.type == EventType.RUN_STARTED


def test_all_thirteen_event_types_exist():
    expected = {
        "run_started", "node_created", "node_status_changed",
        "thinking", "agent_message",
        "tool_started", "tool_finished",
        "ask_user", "ask_user_answered",
        "artifact_created", "subagent_completed",
        "error", "run_completed",
    }
    assert {e.value for e in EventType} == expected


def test_payload_discriminator_rejects_mismatch():
    with pytest.raises(ValidationError):
        AgentEvent(
            seq=1, run_id="r1", node_id="n1", parent_node_id=None,
            ts=datetime.utcnow(),
            type=EventType.RUN_STARTED,
            payload=ThinkingPayload(text="oops", delta=False),  # wrong payload
        )
