"""Typed AgentEvent schema — the on-wire contract.

This module is the single source of truth for event shapes. Both FastAPI
(producer side) and Streamlit (consumer side) import these classes.
"""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field, model_validator


class EventType(str, Enum):
    RUN_STARTED = "run_started"
    NODE_CREATED = "node_created"
    NODE_STATUS_CHANGED = "node_status_changed"
    THINKING = "thinking"
    AGENT_MESSAGE = "agent_message"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    ASK_USER = "ask_user"
    ASK_USER_ANSWERED = "ask_user_answered"
    ARTIFACT_CREATED = "artifact_created"
    SUBAGENT_COMPLETED = "subagent_completed"
    ERROR = "error"
    RUN_COMPLETED = "run_completed"


NodeStatus = Literal[
    "queued", "running", "awaiting_user", "completed", "failed", "skipped",
]
NodeRole = Literal[
    "root", "lead-analyst", "web-researcher", "data-analyst", "report-writer",
]
ArtifactKind = Literal["markdown", "sql", "yaml", "json", "image", "text"]
ErrorWhere = Literal["orchestrator", "conversation", "tool", "llm"]
AskedBy = Literal["lead", "subagent"]


# --- Payload classes -------------------------------------------------

class RunStartedPayload(BaseModel):
    kind: Literal["run_started"] = "run_started"
    topic: str

class NodeCreatedPayload(BaseModel):
    kind: Literal["node_created"] = "node_created"
    role: NodeRole
    title: str | None = None
    status: Literal["queued", "running"] = "queued"

class NodeStatusChangedPayload(BaseModel):
    kind: Literal["node_status_changed"] = "node_status_changed"
    status: NodeStatus
    reason: str | None = None

class ThinkingPayload(BaseModel):
    kind: Literal["thinking"] = "thinking"
    text: str
    delta: bool = False

class AgentMessagePayload(BaseModel):
    kind: Literal["agent_message"] = "agent_message"
    text: str

class ToolStartedPayload(BaseModel):
    kind: Literal["tool_started"] = "tool_started"
    tool_name: str
    tool_call_id: str
    input: dict

class ToolFinishedPayload(BaseModel):
    kind: Literal["tool_finished"] = "tool_finished"
    tool_call_id: str
    output_summary: str
    ok: bool
    output_ref: str | None = None

class AskUserPayload(BaseModel):
    kind: Literal["ask_user"] = "ask_user"
    question_id: str
    question: str
    options: list[str] | None = None
    asked_by: AskedBy

class AskUserAnsweredPayload(BaseModel):
    kind: Literal["ask_user_answered"] = "ask_user_answered"
    question_id: str
    answer: str

class ArtifactCreatedPayload(BaseModel):
    kind: Literal["artifact_created"] = "artifact_created"
    artifact_id: str
    name: str
    artifact_kind: ArtifactKind
    bytes: int

class SubagentCompletedPayload(BaseModel):
    kind: Literal["subagent_completed"] = "subagent_completed"
    summary: str
    artifact_ids: list[str] = Field(default_factory=list)

class ErrorPayload(BaseModel):
    kind: Literal["error"] = "error"
    where: ErrorWhere
    message: str
    recoverable: bool
    node_id_ref: str

class RunCompletedPayload(BaseModel):
    kind: Literal["run_completed"] = "run_completed"
    final_artifact_id: str
    total_tokens: int | None = None


EventPayload = Annotated[
    Union[
        RunStartedPayload, NodeCreatedPayload, NodeStatusChangedPayload,
        ThinkingPayload, AgentMessagePayload,
        ToolStartedPayload, ToolFinishedPayload,
        AskUserPayload, AskUserAnsweredPayload,
        ArtifactCreatedPayload, SubagentCompletedPayload,
        ErrorPayload, RunCompletedPayload,
    ],
    Field(discriminator="kind"),
]

# Map AgentEvent.type → required payload class
_TYPE_TO_PAYLOAD = {
    EventType.RUN_STARTED: RunStartedPayload,
    EventType.NODE_CREATED: NodeCreatedPayload,
    EventType.NODE_STATUS_CHANGED: NodeStatusChangedPayload,
    EventType.THINKING: ThinkingPayload,
    EventType.AGENT_MESSAGE: AgentMessagePayload,
    EventType.TOOL_STARTED: ToolStartedPayload,
    EventType.TOOL_FINISHED: ToolFinishedPayload,
    EventType.ASK_USER: AskUserPayload,
    EventType.ASK_USER_ANSWERED: AskUserAnsweredPayload,
    EventType.ARTIFACT_CREATED: ArtifactCreatedPayload,
    EventType.SUBAGENT_COMPLETED: SubagentCompletedPayload,
    EventType.ERROR: ErrorPayload,
    EventType.RUN_COMPLETED: RunCompletedPayload,
}


class AgentEvent(BaseModel):
    seq: int
    run_id: str
    node_id: str
    parent_node_id: str | None
    ts: datetime
    type: EventType
    payload: EventPayload

    @model_validator(mode="after")
    def _payload_matches_type(self):
        expected = _TYPE_TO_PAYLOAD[self.type]
        if not isinstance(self.payload, expected):
            raise ValueError(
                f"type={self.type} requires payload {expected.__name__}, "
                f"got {type(self.payload).__name__}"
            )
        return self
