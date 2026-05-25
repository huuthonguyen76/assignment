# Deep Analyst Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an agent-transparent research chat app — multi-agent orchestration over OpenHands SDK, FastAPI backend, Streamlit UI, full real-time event decode and trace-tree rendering, all 16 capstone requirements.

**Architecture:** Python everywhere. FastAPI on `:8000` runs an asyncio orchestrator that spawns N parallel OpenHands `Conversation` instances. A normalized 13-type `AgentEvent` stream is persisted to SQLite by `(run_id, seq)` and tailed via `?from=last_seq` polling. Streamlit on `:8501` polls via `httpx` inside `st.fragment(run_every=0.5)` and rebuilds the trace tree client-side using a pure `apply_event` decoder shared with the backend.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, openhands-sdk, openai (for OpenCode Zen), tavily-python, streamlit, pydantic v2, aiosqlite, pytest, pytest-asyncio, httpx.

**Spec:** `docs/superpowers/specs/2026-05-25-deep-analyst-openhands-design.md` (commit `7ac8084`).

**OpenHands SDK note:** Exact event class names and import paths may differ slightly between `openhands-sdk` releases. The only place coupled to this surface is `backend/bus.py::TaggingSubscriber._normalize`. If imports differ from those shown in Task 12, adjust only that file. The rest of the system speaks the normalized `AgentEvent` schema.

---

## File Structure

Files created by this plan (in dependency order):

| Path | Responsibility |
|---|---|
| `pyproject.toml`, `Makefile`, `.env.example`, `.gitignore` | Project bootstrap |
| `backend/schema.py` | Pydantic `AgentEvent` envelope + 13 payload classes + enums |
| `backend/db.py` | aiosqlite wrapper: migrations, atomic `next_seq`, event insert/fetch |
| `backend/decoder.py` | `UIState`, UI-side `Node`, pure `apply_event()` function |
| `backend/bus.py` | `EventBus` (emit/subscribe/await_answer), `TaggingSubscriber` |
| `backend/llm.py` | OpenCode Zen client wrapper, JSON-mode helper, retry |
| `backend/tools/tavily_search.py` | OpenHands Tool over Tavily Search API |
| `backend/tools/write_artifact.py` | OpenHands Tool that writes to `./.data/artifacts/{run_id}/{node_id}/` |
| `backend/tools/ask_user.py` | OpenHands Tool implementing the blocking-call pause pattern |
| `backend/agents/lead.py` | Lead decompose() prompt + structured-output schema |
| `backend/agents/web_researcher.py`, `data_analyst.py`, `report_writer.py` | Sub-agent factories |
| `backend/orchestrator.py` | `RunOrchestrator`: run() with gather over parallel Conversations |
| `backend/main.py` | FastAPI app + all routes |
| `streamlit_app/api_client.py` | `httpx` wrappers for all backend endpoints |
| `streamlit_app/state.py` | Typed `st.session_state` accessors |
| `streamlit_app/components/trace_tree.py` | Expander tree + `st.columns` parallel viz |
| `streamlit_app/components/chat_column.py` | Live chat + run stack + activity ticker |
| `streamlit_app/components/ask_user_form.py` | Pending-question form |
| `streamlit_app/components/artifacts_tab.py` | Artifact list + inline preview |
| `streamlit_app/app.py` | Entrypoint, layout, polling fragment |
| `tests/test_decoder.py`, `test_orchestrator.py`, `test_api.py`, `test_render_snapshot.py` | The four test suites |
| `tests/fixtures/*.json` | Event-list fixtures |
| `README.md`, `design/one-pager.md` | Deliverables |

---

## Task 1: Project bootstrap

**Files:**
- Create: `pyproject.toml`, `Makefile`, `.env.example`, `.gitignore`, `README.md` (stub), and empty package skeletons

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "deep-analyst"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "openhands-sdk>=1.0.0",
  "openai>=1.40",
  "tavily-python>=0.5",
  "streamlit>=1.36",
  "pydantic>=2.7",
  "aiosqlite>=0.20",
  "httpx>=0.27",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "pytest-mock>=3.12",
  "respx>=0.21",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create `.env.example`**

```
OPENCODE_ZEN_API_KEY=
OPENCODE_ZEN_BASE_URL=https://opencode.ai/zen/v1
OPENCODE_ZEN_MODEL=grok-code-fast-1
TAVILY_API_KEY=
APP_DB_PATH=./.data/app.db
APP_ARTIFACTS_DIR=./.data/artifacts
APP_POLL_INTERVAL_MS=500
```

- [ ] **Step 3: Create `.gitignore`**

```
.data/
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
.coverage
*.egg-info/
```

- [ ] **Step 4: Create `Makefile`**

```make
.PHONY: dev test backend ui install demo

install:
	uv venv && uv pip install -e ".[dev]"

backend:
	uv run uvicorn backend.main:app --reload --port 8000

ui:
	uv run streamlit run streamlit_app/app.py --server.port 8501

dev:
	@echo "Run 'make backend' and 'make ui' in two terminals."

test:
	uv run pytest -v

demo: install
	@cp -n .env.example .env || true
	@echo "Edit .env with your API keys, then run 'make backend' and 'make ui'."
```

- [ ] **Step 5: Create skeleton package directories**

```bash
mkdir -p backend/agents backend/tools
mkdir -p streamlit_app/components
mkdir -p tests/fixtures
touch backend/__init__.py backend/agents/__init__.py backend/tools/__init__.py
touch streamlit_app/__init__.py streamlit_app/components/__init__.py
touch tests/__init__.py
```

- [ ] **Step 6: Create README stub** at `README.md`:

```markdown
# Deep Analyst

Agent-transparent research chat. See `docs/superpowers/specs/2026-05-25-deep-analyst-openhands-design.md`.

## Quick start

    make install
    cp .env.example .env       # fill in OPENCODE_ZEN_API_KEY, TAVILY_API_KEY
    make backend               # terminal 1
    make ui                    # terminal 2
    open http://localhost:8501
```

- [ ] **Step 7: Verify install works**

Run: `make install`
Expected: virtualenv created, deps installed, no errors. If `openhands-sdk` is not yet on PyPI under that exact name, install it from its current location (`pip install openhands-sdk` or `pip install openhands-ai`) and update `pyproject.toml`. Re-run.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml Makefile .env.example .gitignore README.md backend streamlit_app tests
git commit -m "chore: project bootstrap"
```

---

## Task 2: Pydantic AgentEvent schema

**Files:**
- Create: `backend/schema.py`
- Test: `tests/test_schema.py`

- [ ] **Step 1: Write the failing test** at `tests/test_schema.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_schema.py -v`
Expected: ImportError on `backend.schema`.

- [ ] **Step 3: Create `backend/schema.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_schema.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/schema.py tests/test_schema.py
git commit -m "feat(schema): AgentEvent envelope + 13 payload types"
```

---

## Task 3: SQLite db wrapper

**Files:**
- Create: `backend/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test** at `tests/test_db.py`:

```python
import asyncio
from datetime import datetime
import pytest
from backend.db import DB
from backend.schema import AgentEvent, EventType, RunStartedPayload, ThinkingPayload


@pytest.fixture
async def db(tmp_path):
    d = DB(path=str(tmp_path / "t.db"))
    await d.connect()
    await d.init_schema()
    yield d
    await d.close()


async def test_init_creates_tables(db):
    rows = await db.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    names = {r[0] for r in rows}
    assert {"sessions", "runs", "nodes", "events", "artifacts",
            "pending_questions"} <= names


async def test_insert_and_fetch_events_round_trip(db):
    await db.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                     ("s1", datetime.utcnow()))
    await db.execute(
        "INSERT INTO runs (id, session_id, topic, started_at, status, next_seq) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        ("r1", "s1", "topic", datetime.utcnow(), "running"))

    e = AgentEvent(
        seq=await db.next_seq("r1"),
        run_id="r1", node_id="root", parent_node_id=None,
        ts=datetime.utcnow(),
        type=EventType.RUN_STARTED,
        payload=RunStartedPayload(topic="topic"),
    )
    await db.insert_event(e)
    fetched = await db.fetch_events_from("r1", from_seq=0)
    assert len(fetched) == 1
    assert fetched[0].seq == 0
    assert fetched[0].payload.topic == "topic"


async def test_next_seq_is_atomic_under_concurrency(db):
    await db.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                     ("s1", datetime.utcnow()))
    await db.execute(
        "INSERT INTO runs (id, session_id, topic, started_at, status, next_seq) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        ("r1", "s1", "topic", datetime.utcnow(), "running"))

    seqs = await asyncio.gather(*[db.next_seq("r1") for _ in range(100)])
    assert sorted(seqs) == list(range(100))   # gap-free, no duplicates
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py -v`
Expected: ImportError.

- [ ] **Step 3: Create `backend/db.py`**

```python
"""aiosqlite wrapper. One DB instance per process; serialized via asyncio.Lock."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import aiosqlite
from backend.schema import AgentEvent, EventType, _TYPE_TO_PAYLOAD

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    title TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    topic TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    next_seq INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    parent_id TEXT REFERENCES nodes(id),
    role TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    node_id TEXT NOT NULL,
    parent_node_id TEXT,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_node ON events(run_id, node_id);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    node_id TEXT NOT NULL REFERENCES nodes(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    path_on_disk TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_questions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    node_id TEXT NOT NULL REFERENCES nodes(id),
    question TEXT NOT NULL,
    options_json TEXT,
    answer TEXT,
    asked_at TIMESTAMP NOT NULL,
    answered_at TIMESTAMP
);
"""


class DB:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("APP_DB_PATH", "./.data/app.db")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._seq_locks: dict[str, asyncio.Lock] = {}

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def init_schema(self):
        async with self._lock:
            await self._conn.executescript(SCHEMA_SQL)
            await self._conn.commit()

    async def execute(self, sql: str, params=()):
        async with self._lock:
            await self._conn.execute(sql, params)
            await self._conn.commit()

    async def fetchall(self, sql: str, params=()):
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            rows = await cur.fetchall()
            await cur.close()
            return rows

    async def fetchone(self, sql: str, params=()):
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            row = await cur.fetchone()
            await cur.close()
            return row

    def _seq_lock_for(self, run_id: str) -> asyncio.Lock:
        if run_id not in self._seq_locks:
            self._seq_locks[run_id] = asyncio.Lock()
        return self._seq_locks[run_id]

    async def next_seq(self, run_id: str) -> int:
        async with self._seq_lock_for(run_id):
            async with self._lock:
                cur = await self._conn.execute(
                    "SELECT next_seq FROM runs WHERE id=?", (run_id,))
                row = await cur.fetchone()
                await cur.close()
                if row is None:
                    raise KeyError(f"unknown run {run_id}")
                n = row[0]
                await self._conn.execute(
                    "UPDATE runs SET next_seq=? WHERE id=?", (n + 1, run_id))
                await self._conn.commit()
                return n

    async def insert_event(self, ev: AgentEvent):
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO events (run_id, seq, ts, node_id, parent_node_id, "
                "type, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ev.run_id, ev.seq, ev.ts, ev.node_id, ev.parent_node_id,
                 ev.type.value, ev.payload.model_dump_json()),
            )
            await self._conn.commit()

    async def fetch_events_from(
        self, run_id: str, from_seq: int = 0, limit: int = 1000
    ) -> list[AgentEvent]:
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT seq, ts, node_id, parent_node_id, type, payload_json "
                "FROM events WHERE run_id=? AND seq>=? ORDER BY seq LIMIT ?",
                (run_id, from_seq, limit),
            )
            rows = await cur.fetchall()
            await cur.close()
        out: list[AgentEvent] = []
        for seq, ts, node_id, parent_node_id, type_, payload_json in rows:
            t = EventType(type_)
            payload = _TYPE_TO_PAYLOAD[t].model_validate_json(payload_json)
            out.append(AgentEvent(
                seq=seq, run_id=run_id, node_id=node_id,
                parent_node_id=parent_node_id, ts=ts,
                type=t, payload=payload,
            ))
        return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_db.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/db.py tests/test_db.py
git commit -m "feat(db): aiosqlite wrapper with atomic next_seq and event store"
```

---

## Task 4: UI Node tree + UIState

**Files:**
- Create: `backend/decoder.py` (Node + UIState only — `apply_event` comes in Task 5)
- Test: `tests/test_node_tree.py`

- [ ] **Step 1: Write the failing test** at `tests/test_node_tree.py`:

```python
import pytest
from backend.decoder import Node, UIState


def test_find_locates_descendant():
    root = Node(id="root", role="root", title="t", status="running")
    lead = Node(id="lead", role="lead-analyst", title=None, status="running",
                parent_id="root")
    root.children.append(lead)
    r1 = Node(id="r1", role="web-researcher", title="sub1", status="queued",
              parent_id="lead")
    lead.children.append(r1)
    assert root.find("r1") is r1
    assert root.find("missing") is None


def test_uistate_initial_shape():
    s = UIState()
    assert s.tree is None
    assert s.pending_question is None
    assert s.artifacts == []
    assert s.final_artifact_id is None
```

- [ ] **Step 2: Run test, expect ImportError**

Run: `uv run pytest tests/test_node_tree.py -v`

- [ ] **Step 3: Create `backend/decoder.py` (Node + UIState only)**

```python
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_node_tree.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/decoder.py tests/test_node_tree.py
git commit -m "feat(decoder): Node tree + UIState dataclasses"
```

---

## Task 5: `apply_event` decoder + tests

**Files:**
- Modify: `backend/decoder.py` (append `apply_event`)
- Create: `tests/test_decoder.py`
- Create: `tests/fixtures/canonical_run.json`

- [ ] **Step 1: Write the failing canonical-run test** at `tests/test_decoder.py`:

```python
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
```

- [ ] **Step 2: Run test, see all 9 fail with `apply_event` import error**

Run: `uv run pytest tests/test_decoder.py -v`

- [ ] **Step 3: Append `apply_event` to `backend/decoder.py`**

```python
# Append at bottom of backend/decoder.py

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
```

- [ ] **Step 4: Run all decoder tests**

Run: `uv run pytest tests/test_decoder.py -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/decoder.py tests/test_decoder.py
git commit -m "feat(decoder): apply_event with gap detection and replay safety"
```

---

## Task 6: Decoder — parallel-no-race + advanced fixtures

**Files:**
- Modify: `tests/test_decoder.py` (add tests)

- [ ] **Step 1: Add the parallel-no-race test** at the bottom of `tests/test_decoder.py`:

```python
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
```

- [ ] **Step 2: Run all decoder tests**

Run: `uv run pytest tests/test_decoder.py -v`
Expected: 12 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_decoder.py
git commit -m "test(decoder): parallel-no-race + idempotent re-apply"
```

---

## Task 7: EventBus (emit/subscribe/await_answer)

**Files:**
- Create: `backend/bus.py` (EventBus only — TaggingSubscriber comes in Task 12)
- Test: `tests/test_bus.py`

- [ ] **Step 1: Write the failing test** at `tests/test_bus.py`:

```python
import asyncio
from datetime import datetime
import uuid
import pytest
from backend.db import DB
from backend.bus import EventBus
from backend.schema import EventType, RunStartedPayload, AskUserPayload


@pytest.fixture
async def bus(tmp_path):
    db = DB(path=str(tmp_path / "t.db"))
    await db.connect()
    await db.init_schema()
    await db.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                     ("s1", datetime.utcnow()))
    await db.execute(
        "INSERT INTO runs (id, session_id, topic, started_at, status, next_seq) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        ("r1", "s1", "topic", datetime.utcnow(), "running"))
    await db.execute(
        "INSERT INTO nodes (id, run_id, parent_id, role, title, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("n1", "r1", None, "lead-analyst", None, "running"))
    bus = EventBus(db)
    yield bus
    await db.close()


async def test_emit_persists_and_publishes(bus):
    received = []
    q = bus.subscribe("r1")

    async def reader():
        ev = await q.get()
        received.append(ev)

    task = asyncio.create_task(reader())
    await bus.emit(run_id="r1", node_id="n1", parent_node_id=None,
                   type=EventType.RUN_STARTED,
                   payload=RunStartedPayload(topic="hi"))
    await task
    assert received[0].payload.topic == "hi"
    assert received[0].seq == 0

    persisted = await bus.db.fetch_events_from("r1", from_seq=0)
    assert len(persisted) == 1


async def test_ask_user_await_answer_blocks_then_resolves(bus):
    q_id = str(uuid.uuid4())
    await bus.persist_pending(run_id="r1", node_id="n1",
                              question_id=q_id, question="why?")

    async def answerer():
        await asyncio.sleep(0.05)
        await bus.set_answer(q_id, "because")

    answer_task = asyncio.create_task(answerer())
    result = await bus.await_answer(q_id)
    await answer_task
    assert result == "because"
```

- [ ] **Step 2: Run test, expect ImportError**

Run: `uv run pytest tests/test_bus.py -v`

- [ ] **Step 3: Create `backend/bus.py`**

```python
"""EventBus: atomic seq, SQLite persist, in-memory pub/sub, ask_user gates.

TaggingSubscriber is added in Task 12.
"""
from __future__ import annotations
import asyncio
import json
from collections import defaultdict
from datetime import datetime
from backend.db import DB
from backend.schema import (
    AgentEvent, EventType, EventPayload,
)


class EventBus:
    def __init__(self, db: DB):
        self.db = db
        self._subscribers: dict[str, list[asyncio.Queue[AgentEvent]]] = defaultdict(list)
        self._answers: dict[str, asyncio.Future[str]] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, run_id: str) -> asyncio.Queue[AgentEvent]:
        q: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._subscribers[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue):
        if q in self._subscribers[run_id]:
            self._subscribers[run_id].remove(q)

    async def emit(
        self, *, run_id: str, node_id: str, parent_node_id: str | None,
        type: EventType, payload: EventPayload,
    ) -> AgentEvent:
        async with self._lock:
            seq = await self.db.next_seq(run_id)
            ev = AgentEvent(
                seq=seq, run_id=run_id, node_id=node_id,
                parent_node_id=parent_node_id, ts=datetime.utcnow(),
                type=type, payload=payload,
            )
            await self.db.insert_event(ev)
        for q in list(self._subscribers[run_id]):
            q.put_nowait(ev)
        return ev

    async def persist_pending(
        self, *, run_id: str, node_id: str, question_id: str,
        question: str, options: list[str] | None = None,
    ):
        await self.db.execute(
            "INSERT INTO pending_questions (id, run_id, node_id, question, "
            "options_json, asked_at) VALUES (?, ?, ?, ?, ?, ?)",
            (question_id, run_id, node_id, question,
             json.dumps(options) if options else None, datetime.utcnow()),
        )
        self._answers[question_id] = asyncio.get_running_loop().create_future()

    async def await_answer(self, question_id: str) -> str:
        fut = self._answers.get(question_id)
        if fut is None:
            # Possibly created in a different process restart; poll DB
            fut = asyncio.get_running_loop().create_future()
            self._answers[question_id] = fut
        return await fut

    async def set_answer(self, question_id: str, answer: str):
        await self.db.execute(
            "UPDATE pending_questions SET answer=?, answered_at=? WHERE id=?",
            (answer, datetime.utcnow(), question_id),
        )
        fut = self._answers.get(question_id)
        if fut and not fut.done():
            fut.set_result(answer)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_bus.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/bus.py tests/test_bus.py
git commit -m "feat(bus): EventBus with emit, subscribe, ask_user gates"
```

---

## Task 8: OpenCode Zen LLM client

**Files:**
- Create: `backend/llm.py`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Write the failing test** at `tests/test_llm.py`:

```python
import json
import pytest
import respx
import httpx
from backend.llm import OpenCodeZenClient, LLMError


@pytest.fixture
def client():
    return OpenCodeZenClient(
        api_key="test", base_url="https://opencode.test/v1",
        model="grok-code-fast-1", max_retries=2,
    )


@respx.mock
async def test_json_call_returns_parsed_dict(client):
    respx.post("https://opencode.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content":
                '{"action":"decompose","subtopics":["a","b","c"]}'}}]},
        )
    )
    out = await client.json_call(
        system="be helpful", user="decompose: X",
        schema_hint={"action": "decompose|ask_user"},
    )
    assert out == {"action": "decompose", "subtopics": ["a", "b", "c"]}


@respx.mock
async def test_malformed_json_triggers_one_retry_then_raises(client):
    respx.post("https://opencode.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "not json {"}}]},
        )
    )
    with pytest.raises(LLMError):
        await client.json_call(system="s", user="u", schema_hint={})


@respx.mock
async def test_429_retries_then_succeeds(client):
    calls = {"n": 0}
    def respond(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, text="rate limit")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})
    respx.post("https://opencode.test/v1/chat/completions").mock(side_effect=respond)
    out = await client.json_call(system="s", user="u", schema_hint={})
    assert out == {"ok": True}
    assert calls["n"] == 2
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest tests/test_llm.py -v`

- [ ] **Step 3: Create `backend/llm.py`**

```python
"""OpenCode Zen client. OpenAI-compatible chat completions endpoint."""
from __future__ import annotations
import asyncio
import json
import os
import re
from typing import Any
import httpx


class LLMError(Exception):
    pass


class OpenCodeZenClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.getenv("OPENCODE_ZEN_API_KEY", "")
        self.base_url = (
            base_url or os.getenv("OPENCODE_ZEN_BASE_URL",
                                  "https://opencode.ai/zen/v1")
        ).rstrip("/")
        self.model = model or os.getenv("OPENCODE_ZEN_MODEL",
                                        "grok-code-fast-1")
        self.max_retries = max_retries
        self.timeout = timeout

    async def chat_call(
        self, *, system: str, user: str, temperature: float = 0.2,
        tools: list[dict] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {self.api_key}"}

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload, headers=headers,
                    )
                if r.status_code == 429 or r.status_code >= 500:
                    raise LLMError(f"{r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                return r.json()
            except (httpx.TransportError, LLMError) as e:
                last_err = e
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(0.5 * (2 ** attempt))
        raise last_err  # unreachable

    async def json_call(
        self, *, system: str, user: str,
        schema_hint: dict | None = None,
    ) -> dict:
        """Calls the model and parses JSON from the response.

        Strategy: append explicit JSON-only instruction; on parse failure,
        one corrective retry with the failed text echoed back.
        """
        sys = system + (
            "\n\nRespond with ONLY a JSON object matching this schema, no prose: "
            + json.dumps(schema_hint or {})
        )
        for attempt in range(2):
            resp = await self.chat_call(system=sys, user=user, temperature=0.1)
            content = resp["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            if parsed is not None:
                return parsed
            user = (
                "Your previous response could not be parsed as JSON. "
                "Output ONLY a JSON object."
            )
        raise LLMError("model failed to produce valid JSON after retry")


_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    # strip code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_llm.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/llm.py tests/test_llm.py
git commit -m "feat(llm): OpenCode Zen client with json_call + retry/backoff"
```

---

## Task 9: Tavily search tool

**Files:**
- Create: `backend/tools/tavily_search.py`
- Test: `tests/test_tools_tavily.py`

- [ ] **Step 1: Write the failing test** at `tests/test_tools_tavily.py`:

```python
import pytest
from backend.tools.tavily_search import TavilySearchTool, SearchResult


@pytest.fixture
def fake_tavily(monkeypatch):
    calls = []
    class FakeClient:
        def search(self, query, max_results=5, **kwargs):
            calls.append((query, max_results))
            return {
                "results": [
                    {"url": "https://a.com", "title": "A",
                     "content": "hello", "score": 0.9},
                    {"url": "https://b.com", "title": "B",
                     "content": "world", "score": 0.8},
                ]
            }
    monkeypatch.setattr(
        "backend.tools.tavily_search.TavilyClient",
        lambda api_key: FakeClient(),
    )
    return calls


async def test_tool_returns_normalized_results(fake_tavily, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    tool = TavilySearchTool()
    res = await tool.search(query="anthropic agents", max_results=2)
    assert len(res) == 2
    assert res[0].url == "https://a.com"
    assert fake_tavily[0] == ("anthropic agents", 2)


async def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        TavilySearchTool()
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest tests/test_tools_tavily.py -v`

- [ ] **Step 3: Create `backend/tools/tavily_search.py`**

```python
"""Tavily search wrapped as a callable; OpenHands Tool binding added in Task 12."""
from __future__ import annotations
import os
from dataclasses import dataclass
from tavily import TavilyClient


@dataclass
class SearchResult:
    url: str
    title: str
    content: str
    score: float


class TavilySearchTool:
    name = "tavily_search"
    description = "Search the web for current information. Returns top results."

    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY not set")
        self._client = TavilyClient(api_key=key)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raw = self._client.search(query=query, max_results=max_results,
                                  search_depth="basic")
        return [
            SearchResult(
                url=r["url"], title=r["title"],
                content=r.get("content", ""),
                score=r.get("score", 0.0),
            )
            for r in raw.get("results", [])
        ]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_tools_tavily.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/tools/tavily_search.py tests/test_tools_tavily.py
git commit -m "feat(tools): Tavily search wrapper"
```

---

## Task 10: write_artifact tool

**Files:**
- Create: `backend/tools/write_artifact.py`
- Test: `tests/test_tools_write_artifact.py`

- [ ] **Step 1: Write the failing test** at `tests/test_tools_write_artifact.py`:

```python
import os
from pathlib import Path
import pytest
from datetime import datetime
from backend.db import DB
from backend.bus import EventBus
from backend.tools.write_artifact import WriteArtifactTool


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    db = DB(path=str(tmp_path / "t.db"))
    await db.connect(); await db.init_schema()
    await db.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                     ("s1", datetime.utcnow()))
    await db.execute(
        "INSERT INTO runs (id, session_id, topic, started_at, status, next_seq) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        ("r1", "s1", "topic", datetime.utcnow(), "running"))
    await db.execute(
        "INSERT INTO nodes (id, run_id, parent_id, role, title, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("n1", "r1", None, "web-researcher", "sub", "running"))
    bus = EventBus(db)
    yield db, bus
    await db.close()


async def test_write_creates_file_db_row_and_event(setup, tmp_path):
    db, bus = setup
    tool = WriteArtifactTool(bus=bus, run_id="r1", node_id="n1",
                             parent_node_id=None)
    art_id = await tool.write(name="notes.md", content="# hi",
                              kind="markdown")
    # file exists
    p = Path(os.environ["APP_ARTIFACTS_DIR"]) / "r1" / "n1" / "notes.md"
    assert p.exists() and p.read_text() == "# hi"
    # db row
    row = await db.fetchone("SELECT name, kind, bytes FROM artifacts WHERE id=?",
                            (art_id,))
    assert row == ("notes.md", "markdown", 4)
    # event was emitted
    events = await db.fetch_events_from("r1")
    assert events[0].type.value == "artifact_created"
    assert events[0].payload.artifact_id == art_id
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest tests/test_tools_write_artifact.py -v`

- [ ] **Step 3: Create `backend/tools/write_artifact.py`**

```python
"""Write artifact to disk + DB row + artifact_created event."""
from __future__ import annotations
import os
import uuid
from pathlib import Path
from backend.bus import EventBus
from backend.schema import (
    EventType, ArtifactCreatedPayload, ArtifactKind,
)


class WriteArtifactTool:
    name = "write_artifact"
    description = "Write a file the user should see. kind: markdown|sql|yaml|json|image|text"

    def __init__(self, bus: EventBus, run_id: str, node_id: str,
                 parent_node_id: str | None):
        self.bus = bus
        self.run_id = run_id
        self.node_id = node_id
        self.parent_node_id = parent_node_id

    async def write(self, name: str, content: str,
                    kind: ArtifactKind = "text") -> str:
        base = Path(os.environ.get("APP_ARTIFACTS_DIR", "./.data/artifacts"))
        dirpath = base / self.run_id / self.node_id
        dirpath.mkdir(parents=True, exist_ok=True)
        safe = name.replace("..", "_").replace("/", "_")
        path = dirpath / safe
        path.write_text(content)
        size = len(content.encode("utf-8"))
        art_id = str(uuid.uuid4())
        await self.bus.db.execute(
            "INSERT INTO artifacts (id, run_id, node_id, name, kind, bytes, "
            "path_on_disk) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (art_id, self.run_id, self.node_id, safe, kind, size, str(path)),
        )
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.ARTIFACT_CREATED,
            payload=ArtifactCreatedPayload(
                artifact_id=art_id, name=safe,
                artifact_kind=kind, bytes=size,
            ),
        )
        return art_id
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_tools_write_artifact.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/tools/write_artifact.py tests/test_tools_write_artifact.py
git commit -m "feat(tools): write_artifact tool with disk + db + event"
```

---

## Task 11: ask_user blocking tool

**Files:**
- Create: `backend/tools/ask_user.py`
- Test: `tests/test_tools_ask_user.py`

- [ ] **Step 1: Write the failing test** at `tests/test_tools_ask_user.py`:

```python
import asyncio
from datetime import datetime
import pytest
from backend.db import DB
from backend.bus import EventBus
from backend.tools.ask_user import AskUserTool


@pytest.fixture
async def setup(tmp_path):
    db = DB(path=str(tmp_path / "t.db"))
    await db.connect(); await db.init_schema()
    await db.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                     ("s1", datetime.utcnow()))
    await db.execute(
        "INSERT INTO runs (id, session_id, topic, started_at, status, next_seq) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        ("r1", "s1", "topic", datetime.utcnow(), "running"))
    await db.execute(
        "INSERT INTO nodes (id, run_id, parent_id, role, title, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("n1", "r1", None, "web-researcher", "sub", "running"))
    bus = EventBus(db)
    yield db, bus
    await db.close()


async def test_ask_blocks_then_returns_answer(setup):
    db, bus = setup
    tool = AskUserTool(bus=bus, run_id="r1", node_id="n1",
                       parent_node_id=None, asked_by="subagent")

    async def answer_later():
        await asyncio.sleep(0.05)
        # find the latest pending question for n1
        row = await db.fetchone(
            "SELECT id FROM pending_questions WHERE node_id=? "
            "AND answer IS NULL", ("n1",))
        await bus.set_answer(row[0], "use option A")

    task = asyncio.create_task(answer_later())
    out = await tool.ask(question="A or B?", options=["A", "B"])
    await task
    assert out == "use option A"

    types = [e.type.value for e in await db.fetch_events_from("r1")]
    assert "ask_user" in types
    assert "ask_user_answered" in types
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest tests/test_tools_ask_user.py -v`

- [ ] **Step 3: Create `backend/tools/ask_user.py`**

```python
"""ask_user tool: blocks one coroutine until POST /answer arrives.

Per spec tenet #5: block coroutines, never streams.
"""
from __future__ import annotations
import uuid
from backend.bus import EventBus
from backend.schema import (
    EventType, AskUserPayload, AskUserAnsweredPayload, AskedBy,
)


class AskUserTool:
    name = "ask_user"
    description = (
        "Ask the human user a clarifying question. Use sparingly — only when "
        "you genuinely cannot proceed without input."
    )

    def __init__(self, bus: EventBus, run_id: str, node_id: str,
                 parent_node_id: str | None, asked_by: AskedBy):
        self.bus = bus
        self.run_id = run_id
        self.node_id = node_id
        self.parent_node_id = parent_node_id
        self.asked_by = asked_by

    async def ask(self, question: str,
                  options: list[str] | None = None) -> str:
        q_id = str(uuid.uuid4())
        await self.bus.persist_pending(
            run_id=self.run_id, node_id=self.node_id,
            question_id=q_id, question=question, options=options,
        )
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.ASK_USER,
            payload=AskUserPayload(
                question_id=q_id, question=question,
                options=options, asked_by=self.asked_by,
            ),
        )
        answer = await self.bus.await_answer(q_id)
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.ASK_USER_ANSWERED,
            payload=AskUserAnsweredPayload(question_id=q_id, answer=answer),
        )
        return answer
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_tools_ask_user.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/tools/ask_user.py tests/test_tools_ask_user.py
git commit -m "feat(tools): ask_user blocking-call tool"
```

---

## Task 12: Sub-agent runner + OpenHands event normalizer

**Files:**
- Modify: `backend/bus.py` (append `TaggingSubscriber`)
- Create: `backend/agents/sub_agent.py` (small runner that wraps an OpenHands Conversation)
- Test: `tests/test_subagent_runner.py`

Architectural note: rather than depend on OpenHands' specific event class names (which may shift between releases), we adopt an **adapter pattern**: `TaggingSubscriber` exposes a simple `emit_*` API that the sub-agent runner calls. The runner is what touches OpenHands directly. This isolates the SDK surface to one file.

- [ ] **Step 1: Append `TaggingSubscriber` to `backend/bus.py`**

```python
# Append at bottom of backend/bus.py
from backend.schema import (
    AgentMessagePayload, ThinkingPayload,
    ToolStartedPayload, ToolFinishedPayload,
    ErrorPayload, ErrorWhere,
)


class TaggingSubscriber:
    """Adapter: holds (run_id, node_id, parent_node_id) and exposes typed
    emit_* methods. The sub-agent runner calls these as it observes OpenHands
    events. Node identity is stamped from the closure — NEVER from event content.
    """
    def __init__(self, bus: EventBus, run_id: str, node_id: str,
                 parent_node_id: str | None):
        self.bus = bus
        self.run_id = run_id
        self.node_id = node_id
        self.parent_node_id = parent_node_id

    async def emit_thinking(self, text: str, delta: bool = False):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.THINKING,
            payload=ThinkingPayload(text=text, delta=delta),
        )

    async def emit_agent_message(self, text: str):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.AGENT_MESSAGE,
            payload=AgentMessagePayload(text=text),
        )

    async def emit_tool_started(self, tool_name: str, tool_call_id: str,
                                input: dict):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.TOOL_STARTED,
            payload=ToolStartedPayload(
                tool_name=tool_name, tool_call_id=tool_call_id, input=input),
        )

    async def emit_tool_finished(self, tool_call_id: str,
                                 output_summary: str, ok: bool,
                                 output_ref: str | None = None):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.TOOL_FINISHED,
            payload=ToolFinishedPayload(
                tool_call_id=tool_call_id, output_summary=output_summary,
                ok=ok, output_ref=output_ref),
        )

    async def emit_error(self, where: ErrorWhere, message: str,
                         recoverable: bool):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.ERROR,
            payload=ErrorPayload(
                where=where, message=message, recoverable=recoverable,
                node_id_ref=self.node_id),
        )
```

- [ ] **Step 2: Write the failing test** at `tests/test_subagent_runner.py`:

```python
"""Tests the sub-agent runner with a FakeLLM. Real OpenHands integration
happens in Task 15's orchestrator tests."""
from datetime import datetime
import pytest
from backend.db import DB
from backend.bus import EventBus, TaggingSubscriber
from backend.agents.sub_agent import run_research_subagent


class FakeLLM:
    def __init__(self, plan):
        self.plan = list(plan)  # list of (kind, payload)
        self.i = 0
    async def step(self, history):
        item = self.plan[self.i]; self.i += 1
        return item


class FakeTavily:
    async def search(self, query, max_results=5):
        return [type("R", (), {"url": "https://x", "title": "X",
                               "content": "data", "score": 1.0})()]


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ARTIFACTS_DIR", str(tmp_path / "art"))
    db = DB(path=str(tmp_path / "t.db"))
    await db.connect(); await db.init_schema()
    await db.execute("INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                     ("s1", datetime.utcnow()))
    await db.execute(
        "INSERT INTO runs (id, session_id, topic, started_at, status, next_seq) "
        "VALUES (?, ?, ?, ?, ?, 0)",
        ("r1", "s1", "topic", datetime.utcnow(), "running"))
    await db.execute(
        "INSERT INTO nodes (id, run_id, parent_id, role, title, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("n1", "r1", "root", "web-researcher", "sub-A", "running"))
    bus = EventBus(db)
    sub = TaggingSubscriber(bus, run_id="r1", node_id="n1",
                            parent_node_id="root")
    yield db, bus, sub


async def test_research_subagent_searches_and_writes_note(setup):
    db, bus, sub = setup
    fake_llm = FakeLLM([
        ("think", "I need to search."),
        ("tool", {"name": "tavily_search", "args": {"query": "anthropic"}}),
        ("think", "Now I'll write notes."),
        ("tool", {"name": "write_artifact",
                  "args": {"name": "anthropic.md",
                           "content": "# Anthropic\n- ...",
                           "kind": "markdown"}}),
        ("finish", {"summary": "Found 1 source."}),
    ])
    summary, art_ids = await run_research_subagent(
        subtopic="sub-A", subscriber=sub, llm=fake_llm,
        tavily=FakeTavily(), bus=bus,
    )
    assert summary == "Found 1 source."
    assert len(art_ids) == 1
    types = [e.type.value for e in await db.fetch_events_from("r1")]
    assert "thinking" in types
    assert "tool_started" in types
    assert "tool_finished" in types
    assert "artifact_created" in types
```

- [ ] **Step 3: Run, expect ImportError**

Run: `uv run pytest tests/test_subagent_runner.py -v`

- [ ] **Step 4: Create `backend/agents/sub_agent.py`**

```python
"""Sub-agent runner. In production the `llm` argument is an OpenHands
Conversation; in tests it's a FakeLLM. Both expose `.step(history)` returning
(kind, payload). Supported kinds: "think" | "tool" | "finish".

This pattern lets us evolve the orchestration without coupling to a specific
OpenHands SDK release. When wiring the real SDK (production), create a thin
adapter class that wraps a Conversation and yields these tuples.
"""
from __future__ import annotations
import uuid
from typing import Any
from backend.bus import EventBus, TaggingSubscriber
from backend.tools.write_artifact import WriteArtifactTool
from backend.tools.ask_user import AskUserTool


async def run_research_subagent(
    *, subtopic: str, subscriber: TaggingSubscriber, llm,
    tavily, bus: EventBus,
) -> tuple[str, list[str]]:
    """Drive a web-researcher loop until the LLM emits "finish".

    Returns (summary, list_of_artifact_ids).
    """
    history: list[dict] = [{"role": "user", "content": f"subtopic: {subtopic}"}]
    artifact_ids: list[str] = []
    writer = WriteArtifactTool(
        bus=bus, run_id=subscriber.run_id, node_id=subscriber.node_id,
        parent_node_id=subscriber.parent_node_id,
    )
    asker = AskUserTool(
        bus=bus, run_id=subscriber.run_id, node_id=subscriber.node_id,
        parent_node_id=subscriber.parent_node_id, asked_by="subagent",
    )

    while True:
        kind, payload = await llm.step(history)

        if kind == "think":
            await subscriber.emit_thinking(payload)
            history.append({"role": "assistant", "content": payload})

        elif kind == "tool":
            name = payload["name"]
            args = payload.get("args", {})
            tcid = str(uuid.uuid4())
            await subscriber.emit_tool_started(name, tcid, args)
            try:
                if name == "tavily_search":
                    results = await tavily.search(
                        args["query"], max_results=args.get("max_results", 5))
                    summary = f"{len(results)} results: " + ", ".join(
                        r.title for r in results[:3])
                    out = {"results": [r.__dict__ for r in results]}
                    await subscriber.emit_tool_finished(
                        tcid, output_summary=summary, ok=True)
                    history.append(
                        {"role": "tool", "tool_call_id": tcid, "content": str(out)})
                elif name == "write_artifact":
                    art_id = await writer.write(
                        name=args["name"], content=args["content"],
                        kind=args.get("kind", "markdown"),
                    )
                    artifact_ids.append(art_id)
                    await subscriber.emit_tool_finished(
                        tcid, output_summary=f"wrote {args['name']}",
                        ok=True, output_ref=art_id)
                    history.append(
                        {"role": "tool", "tool_call_id": tcid,
                         "content": f"saved {art_id}"})
                elif name == "ask_user":
                    answer = await asker.ask(
                        question=args["question"], options=args.get("options"))
                    await subscriber.emit_tool_finished(
                        tcid, output_summary="user answered", ok=True)
                    history.append(
                        {"role": "tool", "tool_call_id": tcid, "content": answer})
                else:
                    await subscriber.emit_tool_finished(
                        tcid, output_summary=f"unknown tool {name}", ok=False)
                    await subscriber.emit_error(
                        where="tool", message=f"unknown tool {name}",
                        recoverable=False)
            except Exception as e:
                await subscriber.emit_tool_finished(
                    tcid, output_summary=str(e), ok=False)
                await subscriber.emit_error(
                    where="tool", message=str(e), recoverable=True)
                history.append(
                    {"role": "tool", "tool_call_id": tcid,
                     "content": f"ERROR: {e}"})

        elif kind == "finish":
            return payload["summary"], artifact_ids

        else:
            raise ValueError(f"unknown LLM step kind: {kind}")
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_subagent_runner.py -v`
Expected: 1 passed.

- [ ] **Step 6: Commit**

```bash
git add backend/bus.py backend/agents/sub_agent.py tests/test_subagent_runner.py
git commit -m "feat(agents): sub-agent runner + TaggingSubscriber adapter"
```

---

## Task 13: Lead-analyst decompose() + sub-agent prompts

**Files:**
- Create: `backend/agents/lead.py`, `backend/agents/web_researcher.py`, `backend/agents/data_analyst.py`, `backend/agents/report_writer.py`
- Test: `tests/test_agents_prompts.py`

- [ ] **Step 1: Write a smoke test** at `tests/test_agents_prompts.py`:

```python
from backend.agents.lead import LEAD_SYSTEM_PROMPT, DECOMPOSE_SCHEMA_HINT
from backend.agents.web_researcher import WEB_RESEARCHER_PROMPT
from backend.agents.data_analyst import DATA_ANALYST_PROMPT
from backend.agents.report_writer import REPORT_WRITER_PROMPT


def test_prompts_are_nonempty_strings():
    assert isinstance(LEAD_SYSTEM_PROMPT, str) and len(LEAD_SYSTEM_PROMPT) > 100
    assert "decompose" in LEAD_SYSTEM_PROMPT.lower()
    assert "ask_user" in LEAD_SYSTEM_PROMPT.lower()
    assert "subtopics" in DECOMPOSE_SCHEMA_HINT
    for p in (WEB_RESEARCHER_PROMPT, DATA_ANALYST_PROMPT, REPORT_WRITER_PROMPT):
        assert isinstance(p, str) and len(p) > 100
```

- [ ] **Step 2: Create `backend/agents/lead.py`**

```python
LEAD_SYSTEM_PROMPT = """You are the lead-analyst of a research team.

Your ONLY job is to decompose a research request into 2-4 focused subtopics,
each of which can be researched independently by a sub-agent. You never do
research yourself.

When the request is ambiguous in scope, perspective, or which industry/angle
the user cares about, ASK ONE clarifying question first. Examples of when to
ask:
- "Research X" where X has multiple distinct industries or angles.
- The user mentions competitors but doesn't say which dimensions matter.
- The topic could be technical, commercial, or regulatory.

When the request is clear enough, decompose immediately.

Subtopics must be:
- specific enough that a researcher can search for them
- mutually non-overlapping
- collectively covering the user's question
"""

DECOMPOSE_SCHEMA_HINT = {
    "action": "decompose | ask_user",
    "subtopics": ["string (when action=decompose, 2-4 items)"],
    "question": "string (when action=ask_user)",
    "options": ["string (optional, when action=ask_user)"],
}
```

- [ ] **Step 3: Create `backend/agents/web_researcher.py`**

```python
WEB_RESEARCHER_PROMPT = """You are a web researcher focused on ONE subtopic.

Workflow:
1. Use tavily_search to gather information (max 5 searches).
2. Read the returned snippets — they include URL, title, and content excerpt.
3. Synthesize findings into a markdown note via write_artifact.
   - name: short-slug-derived-from-subtopic.md
   - kind: markdown
   - content: structured with headings, bullet points, and inline citations
     like [source: <url>].
4. Finish with a one-sentence summary of what you found.

Use ask_user ONLY if the subtopic itself is incoherent or contradictory.
Do not ask the user clarifying questions about research preferences — make
your best call and document it in the notes.
"""
```

- [ ] **Step 4: Create `backend/agents/data_analyst.py`**

```python
DATA_ANALYST_PROMPT = """You are a data analyst.

Inputs: markdown notes written by web-researchers in
./.data/artifacts/<run_id>/<researcher_node_id>/. Use read_file and the
artifact listing to find them.

Workflow:
1. Read every researcher note.
2. Extract concrete metrics, comparisons, dates, and named entities.
3. Write a structured summary via write_artifact:
   - name: data_summary.md
   - kind: markdown
   - sections: "Key metrics", "Comparisons table", "Notable claims with sources"
4. Optionally write a second artifact with a comparison table in markdown.
5. Finish with a one-sentence summary.

You do not have access to external search. Work only from researcher notes.
"""
```

- [ ] **Step 5: Create `backend/agents/report_writer.py`**

```python
REPORT_WRITER_PROMPT = """You are a report writer.

Read all prior artifacts (researcher notes + data_summary.md). Synthesize a
final research brief.

Required structure:
1. Executive summary (3-5 sentences)
2. Findings by subtopic (one section per researcher)
3. Cross-cutting observations
4. Limitations and open questions
5. Sources (list of all unique URLs cited)

Write the brief via write_artifact:
   - name: research_brief.md
   - kind: markdown

Finish with a one-sentence summary describing the brief.
"""
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_agents_prompts.py -v`
Expected: 1 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/agents tests/test_agents_prompts.py
git commit -m "feat(agents): system prompts for lead and three sub-roles"
```

---

## Task 14: RunOrchestrator

**Files:**
- Create: `backend/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test** at `tests/test_orchestrator.py`:

```python
import asyncio
from datetime import datetime
import pytest
from backend.db import DB
from backend.bus import EventBus
from backend.orchestrator import RunOrchestrator


class FakeLLM:
    """Drives lead decompose + per-sub-agent step loops via a scripted plan."""
    def __init__(self, lead_plan, sub_plans):
        self.lead_plan = lead_plan
        self.sub_plans = sub_plans   # dict subtopic -> list of steps
        self.sub_iters: dict[str, int] = {}

    async def decompose(self, topic, prior_answer=None):
        return self.lead_plan.pop(0)

    async def step(self, history, subtopic):
        i = self.sub_iters.get(subtopic, 0)
        item = self.sub_plans[subtopic][i]
        self.sub_iters[subtopic] = i + 1
        return item


class FakeTavily:
    async def search(self, query, max_results=5):
        return [type("R", (), {"url": "https://x", "title": query,
                               "content": "content", "score": 1.0})()]


@pytest.fixture
async def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ARTIFACTS_DIR", str(tmp_path / "art"))
    db = DB(path=str(tmp_path / "t.db"))
    await db.connect(); await db.init_schema()
    bus = EventBus(db)
    yield db, bus
    await db.close()


async def test_canonical_run_emits_complete_event_sequence(harness):
    db, bus = harness
    lead = [{"action": "decompose", "subtopics": ["A", "B", "C"]}]
    sub = {
        s: [("think", "ok"),
            ("tool", {"name": "tavily_search", "args": {"query": s}}),
            ("tool", {"name": "write_artifact",
                      "args": {"name": f"{s}.md", "content": f"# {s}",
                               "kind": "markdown"}}),
            ("finish", {"summary": f"sub-{s} done"})]
        for s in ("A", "B", "C")
    }
    # data-analyst and report-writer use same step API; minimal plan
    sub["__data__"] = [
        ("think", "reading notes"),
        ("tool", {"name": "write_artifact",
                  "args": {"name": "data_summary.md",
                           "content": "summary", "kind": "markdown"}}),
        ("finish", {"summary": "data done"}),
    ]
    sub["__report__"] = [
        ("think", "synthesizing"),
        ("tool", {"name": "write_artifact",
                  "args": {"name": "research_brief.md",
                           "content": "# Brief", "kind": "markdown"}}),
        ("finish", {"summary": "brief done"}),
    ]
    orch = RunOrchestrator(db=db, bus=bus, llm=FakeLLM(lead, sub),
                           tavily=FakeTavily())
    run_id = await orch.start_run(session_id="s1", topic="why agents?")
    await orch.wait(run_id)

    events = await db.fetch_events_from(run_id)
    types = [e.type.value for e in events]

    assert types[0] == "run_started"
    assert "ask_user" not in types               # no scoping question
    # Three researcher nodes pre-created before any of them runs
    nc = [e for e in events if e.type.value == "node_created"
          and e.payload.role == "web-researcher"]
    assert len(nc) == 3
    # All three created BEFORE any thinking events from them
    first_research_thinking = next(
        i for i, e in enumerate(events)
        if e.type.value == "thinking"
        and e.parent_node_id is not None
        and any(c.payload.role == "web-researcher" and c.node_id == e.node_id
                for c in nc))
    last_node_created = max(
        i for i, e in enumerate(events)
        if e.type.value == "node_created"
        and e.payload.role == "web-researcher")
    assert last_node_created < first_research_thinking

    # data-analyst and report-writer ran sequentially after researchers
    da = next(e for e in events if e.type.value == "node_created"
              and e.payload.role == "data-analyst")
    rw = next(e for e in events if e.type.value == "node_created"
              and e.payload.role == "report-writer")
    assert da.seq < rw.seq
    # all researcher status=completed before data-analyst node created
    researcher_done_seqs = [
        e.seq for e in events if e.type.value == "node_status_changed"
        and e.payload.status == "completed"
        and any(n.node_id == e.node_id and n.payload.role == "web-researcher"
                for n in nc)]
    assert max(researcher_done_seqs) < da.seq

    assert types[-1] == "run_completed"


async def test_lead_ask_user_pauses_then_resumes(harness):
    db, bus = harness
    lead_plan = [
        {"action": "ask_user", "question": "tech or commercial?",
         "options": ["tech", "commercial"]},
        {"action": "decompose", "subtopics": ["A"]},
    ]
    sub = {
        "A": [("finish", {"summary": "ok"})],
        "__data__": [("finish", {"summary": "ok"})],
        "__report__": [("tool", {"name": "write_artifact",
                                 "args": {"name": "f.md", "content": "b",
                                          "kind": "markdown"}}),
                       ("finish", {"summary": "ok"})],
    }
    orch = RunOrchestrator(db=db, bus=bus, llm=FakeLLM(lead_plan, sub),
                           tavily=FakeTavily())
    run_id = await orch.start_run(session_id="s1", topic="vague")

    # Wait for the ask_user event to land
    for _ in range(50):
        events = await db.fetch_events_from(run_id)
        if any(e.type.value == "ask_user" for e in events):
            break
        await asyncio.sleep(0.02)
    else:
        pytest.fail("ask_user not emitted")

    pending = await db.fetchone(
        "SELECT id FROM pending_questions WHERE answer IS NULL")
    await bus.set_answer(pending[0], "commercial")
    await orch.wait(run_id)

    events = await db.fetch_events_from(run_id)
    types = [e.type.value for e in events]
    assert types.count("ask_user") == 1
    assert types.count("ask_user_answered") == 1
    assert types[-1] == "run_completed"
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest tests/test_orchestrator.py -v`

- [ ] **Step 3: Create `backend/orchestrator.py`**

```python
"""RunOrchestrator: lead decompose → parallel researchers →
sequential data-analyst → sequential report-writer."""
from __future__ import annotations
import asyncio
import uuid
from datetime import datetime
from backend.db import DB
from backend.bus import EventBus, TaggingSubscriber
from backend.schema import (
    EventType, RunStartedPayload, NodeCreatedPayload,
    NodeStatusChangedPayload, AskUserPayload, AskUserAnsweredPayload,
    SubagentCompletedPayload, RunCompletedPayload, ErrorPayload,
)
from backend.tools.write_artifact import WriteArtifactTool
from backend.agents.sub_agent import run_research_subagent


class RunOrchestrator:
    def __init__(self, db: DB, bus: EventBus, llm, tavily):
        self.db = db
        self.bus = bus
        self.llm = llm
        self.tavily = tavily
        self._tasks: dict[str, asyncio.Task] = {}

    async def start_run(self, *, session_id: str, topic: str) -> str:
        # Ensure session exists
        row = await self.db.fetchone(
            "SELECT id FROM sessions WHERE id=?", (session_id,))
        if row is None:
            await self.db.execute(
                "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                (session_id, datetime.utcnow()))
        run_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO runs (id, session_id, topic, started_at, status, "
            "next_seq) VALUES (?, ?, ?, ?, ?, 0)",
            (run_id, session_id, topic, datetime.utcnow(), "running"))
        self._tasks[run_id] = asyncio.create_task(self._run(run_id, topic))
        return run_id

    async def wait(self, run_id: str):
        if run_id in self._tasks:
            await self._tasks[run_id]

    async def _create_node(self, run_id, node_id, parent_id, role, title,
                           status):
        await self.db.execute(
            "INSERT INTO nodes (id, run_id, parent_id, role, title, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (node_id, run_id, parent_id, role, title, status))
        await self.bus.emit(
            run_id=run_id, node_id=node_id, parent_node_id=parent_id,
            type=EventType.NODE_CREATED,
            payload=NodeCreatedPayload(role=role, title=title,
                                       status=status),
        )

    async def _set_status(self, run_id, node_id, parent_id, status,
                          reason=None):
        await self.db.execute(
            "UPDATE nodes SET status=? WHERE id=?", (status, node_id))
        await self.bus.emit(
            run_id=run_id, node_id=node_id, parent_node_id=parent_id,
            type=EventType.NODE_STATUS_CHANGED,
            payload=NodeStatusChangedPayload(status=status, reason=reason),
        )

    async def _run(self, run_id: str, topic: str):
        root = "root"
        try:
            # Root node + run_started
            await self.db.execute(
                "INSERT INTO nodes (id, run_id, parent_id, role, title, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (root, run_id, None, "root", topic, "running"))
            await self.bus.emit(
                run_id=run_id, node_id=root, parent_node_id=None,
                type=EventType.RUN_STARTED,
                payload=RunStartedPayload(topic=topic))

            # Lead node
            lead_id = "lead"
            await self._create_node(run_id, lead_id, root, "lead-analyst",
                                    None, "running")

            # Lead decompose (may ask_user, possibly multiple times)
            prior_answer = None
            while True:
                decision = await self.llm.decompose(topic, prior_answer)
                if decision["action"] == "ask_user":
                    q_id = str(uuid.uuid4())
                    await self.bus.persist_pending(
                        run_id=run_id, node_id=lead_id, question_id=q_id,
                        question=decision["question"],
                        options=decision.get("options"))
                    await self.bus.emit(
                        run_id=run_id, node_id=lead_id, parent_node_id=root,
                        type=EventType.ASK_USER,
                        payload=AskUserPayload(
                            question_id=q_id, question=decision["question"],
                            options=decision.get("options"), asked_by="lead"))
                    await self._set_status(run_id, lead_id, root,
                                           "awaiting_user")
                    answer = await self.bus.await_answer(q_id)
                    await self.bus.emit(
                        run_id=run_id, node_id=lead_id, parent_node_id=root,
                        type=EventType.ASK_USER_ANSWERED,
                        payload=AskUserAnsweredPayload(
                            question_id=q_id, answer=answer))
                    await self._set_status(run_id, lead_id, root, "running")
                    prior_answer = answer
                    continue
                if decision["action"] == "decompose":
                    subtopics = decision["subtopics"]
                    break
                raise ValueError(
                    f"unknown lead action: {decision['action']}")

            # Pre-create researcher nodes (all queued) BEFORE any starts
            researcher_nodes = []
            for st in subtopics:
                nid = f"r_{uuid.uuid4().hex[:8]}"
                await self._create_node(run_id, nid, lead_id,
                                        "web-researcher", st, "queued")
                researcher_nodes.append((nid, st))

            # Parallel fan-out
            results = await asyncio.gather(
                *[self._run_researcher(run_id, nid, st, lead_id)
                  for nid, st in researcher_nodes],
                return_exceptions=True,
            )
            successful_research_ids = []
            for (nid, st), res in zip(researcher_nodes, results):
                if isinstance(res, Exception):
                    await self.bus.emit(
                        run_id=run_id, node_id=nid, parent_node_id=lead_id,
                        type=EventType.ERROR,
                        payload=ErrorPayload(
                            where="conversation", message=str(res),
                            recoverable=False, node_id_ref=nid))
                    await self._set_status(run_id, nid, lead_id, "failed")
                else:
                    successful_research_ids.append(nid)

            # Sequential data-analyst
            data_id = "data"
            await self._create_node(run_id, data_id, lead_id, "data-analyst",
                                    None, "running")
            data_sub = TaggingSubscriber(self.bus, run_id, data_id, lead_id)
            data_summary, _ = await run_research_subagent(
                subtopic="__data__", subscriber=data_sub,
                llm=_ScopedLLM(self.llm, "__data__"),
                tavily=self.tavily, bus=self.bus)
            await self.bus.emit(
                run_id=run_id, node_id=data_id, parent_node_id=lead_id,
                type=EventType.SUBAGENT_COMPLETED,
                payload=SubagentCompletedPayload(summary=data_summary))
            await self._set_status(run_id, data_id, lead_id, "completed")

            # Sequential report-writer
            report_id = "report"
            await self._create_node(run_id, report_id, lead_id,
                                    "report-writer", None, "running")
            report_sub = TaggingSubscriber(self.bus, run_id, report_id, lead_id)
            report_summary, report_artifacts = await run_research_subagent(
                subtopic="__report__", subscriber=report_sub,
                llm=_ScopedLLM(self.llm, "__report__"),
                tavily=self.tavily, bus=self.bus)
            await self.bus.emit(
                run_id=run_id, node_id=report_id, parent_node_id=lead_id,
                type=EventType.SUBAGENT_COMPLETED,
                payload=SubagentCompletedPayload(
                    summary=report_summary, artifact_ids=report_artifacts))
            await self._set_status(run_id, report_id, lead_id, "completed")
            await self._set_status(run_id, lead_id, root, "completed")

            # Run completed
            final = report_artifacts[0] if report_artifacts else ""
            await self.db.execute(
                "UPDATE runs SET status=?, finished_at=? WHERE id=?",
                ("completed", datetime.utcnow(), run_id))
            await self.bus.emit(
                run_id=run_id, node_id=root, parent_node_id=None,
                type=EventType.RUN_COMPLETED,
                payload=RunCompletedPayload(final_artifact_id=final))

        except Exception as e:
            await self.db.execute(
                "UPDATE runs SET status=?, finished_at=? WHERE id=?",
                ("failed", datetime.utcnow(), run_id))
            await self.bus.emit(
                run_id=run_id, node_id=root, parent_node_id=None,
                type=EventType.ERROR,
                payload=ErrorPayload(
                    where="orchestrator", message=str(e),
                    recoverable=False, node_id_ref=root))

    async def _run_researcher(self, run_id, node_id, subtopic, parent_id):
        await self._set_status(run_id, node_id, parent_id, "running")
        sub = TaggingSubscriber(self.bus, run_id, node_id, parent_id)
        summary, art_ids = await run_research_subagent(
            subtopic=subtopic, subscriber=sub,
            llm=_ScopedLLM(self.llm, subtopic),
            tavily=self.tavily, bus=self.bus,
        )
        await self.bus.emit(
            run_id=run_id, node_id=node_id, parent_node_id=parent_id,
            type=EventType.SUBAGENT_COMPLETED,
            payload=SubagentCompletedPayload(summary=summary,
                                             artifact_ids=art_ids))
        await self._set_status(run_id, node_id, parent_id, "completed")


class _ScopedLLM:
    """Adapter that turns a multi-subtopic FakeLLM (used in tests) or real
    LLM into the single-step API expected by run_research_subagent.
    """
    def __init__(self, llm, subtopic):
        self.llm = llm
        self.subtopic = subtopic

    async def step(self, history):
        if hasattr(self.llm, "step"):
            try:
                return await self.llm.step(history, self.subtopic)
            except TypeError:
                return await self.llm.step(history)
        raise AttributeError("LLM must expose .step()")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_orchestrator.py -v`
Expected: 2 passed. If `test_canonical_run` fails due to interleaving sensitivity, add `await asyncio.sleep(0)` inside `_run_researcher` after status change to deterministically yield.

- [ ] **Step 5: Commit**

```bash
git add backend/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(orchestrator): lead decompose + parallel researchers + sequential phases"
```

---

## Task 15: FastAPI app + core routes

**Files:**
- Create: `backend/main.py`
- Test: `tests/test_api.py`

- [ ] **Step 1: Write the failing test** at `tests/test_api.py`:

```python
import asyncio
import json
import pytest
from httpx import ASGITransport, AsyncClient
import backend.main as main_mod
from backend.orchestrator import RunOrchestrator
from backend.db import DB
from backend.bus import EventBus
from tests.test_orchestrator import FakeLLM, FakeTavily


@pytest.fixture
async def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ARTIFACTS_DIR", str(tmp_path / "art"))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    # Reset module-level state
    main_mod.state = main_mod._AppState()
    await main_mod.startup()
    lead = [{"action": "decompose", "subtopics": ["A"]}]
    sub = {
        "A": [("finish", {"summary": "ok"})],
        "__data__": [("finish", {"summary": "ok"})],
        "__report__": [
            ("tool", {"name": "write_artifact",
                      "args": {"name": "brief.md", "content": "b",
                               "kind": "markdown"}}),
            ("finish", {"summary": "ok"})],
    }
    main_mod.state.orchestrator = RunOrchestrator(
        db=main_mod.state.db, bus=main_mod.state.bus,
        llm=FakeLLM(lead, sub), tavily=FakeTavily(),
    )
    yield main_mod.app
    await main_mod.shutdown()


async def test_post_run_then_poll_events(app):
    async with AsyncClient(transport=ASGITransport(app=app),
                          base_url="http://t") as ac:
        r = await ac.post("/runs", json={"session_id": "s1", "topic": "x"})
        assert r.status_code == 200
        run_id = r.json()["run_id"]

        # Wait for run to finish
        for _ in range(200):
            r2 = await ac.get(f"/runs/{run_id}/events", params={"from": 0})
            evts = r2.json()
            if any(e["type"] == "run_completed" for e in evts):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("run did not complete")

        types = [e["type"] for e in evts]
        assert types[0] == "run_started"
        assert types[-1] == "run_completed"


async def test_polling_with_cursor_returns_only_new_events(app):
    async with AsyncClient(transport=ASGITransport(app=app),
                          base_url="http://t") as ac:
        r = await ac.post("/runs", json={"session_id": "s1", "topic": "x"})
        run_id = r.json()["run_id"]
        await asyncio.sleep(0.3)
        e1 = (await ac.get(f"/runs/{run_id}/events",
                           params={"from": 0})).json()
        cursor = e1[-1]["seq"] + 1
        e2 = (await ac.get(f"/runs/{run_id}/events",
                           params={"from": cursor})).json()
        # e2 events are strictly newer (or empty if run finished)
        for ev in e2:
            assert ev["seq"] >= cursor


async def test_answer_endpoint_resumes_lead_ask_user(app, monkeypatch):
    # Reconfigure orchestrator with a lead that asks first
    lead = [
        {"action": "ask_user", "question": "tech or commercial?",
         "options": ["tech", "commercial"]},
        {"action": "decompose", "subtopics": ["A"]},
    ]
    sub = {
        "A": [("finish", {"summary": "ok"})],
        "__data__": [("finish", {"summary": "ok"})],
        "__report__": [
            ("tool", {"name": "write_artifact",
                      "args": {"name": "b.md", "content": "b",
                               "kind": "markdown"}}),
            ("finish", {"summary": "ok"})],
    }
    main_mod.state.orchestrator.llm = FakeLLM(lead, sub)
    async with AsyncClient(transport=ASGITransport(app=app),
                          base_url="http://t") as ac:
        r = await ac.post("/runs", json={"session_id": "s1", "topic": "x"})
        run_id = r.json()["run_id"]
        for _ in range(200):
            evts = (await ac.get(f"/runs/{run_id}/events",
                                 params={"from": 0})).json()
            pending = [e for e in evts if e["type"] == "ask_user"]
            if pending:
                break
            await asyncio.sleep(0.02)
        qid = pending[0]["payload"]["question_id"]
        r2 = await ac.post(f"/runs/{run_id}/answer",
                           json={"question_id": qid, "answer": "tech"})
        assert r2.status_code == 200
        for _ in range(200):
            evts = (await ac.get(f"/runs/{run_id}/events",
                                 params={"from": 0})).json()
            if any(e["type"] == "run_completed" for e in evts):
                break
            await asyncio.sleep(0.02)
```

- [ ] **Step 2: Run, expect ImportError**

Run: `uv run pytest tests/test_api.py -v`

- [ ] **Step 3: Create `backend/main.py`**

```python
"""FastAPI app for Deep Analyst."""
from __future__ import annotations
import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel
from backend.db import DB
from backend.bus import EventBus
from backend.llm import OpenCodeZenClient
from backend.tools.tavily_search import TavilySearchTool
from backend.orchestrator import RunOrchestrator
from backend.agents.lead import LEAD_SYSTEM_PROMPT, DECOMPOSE_SCHEMA_HINT


@dataclass
class _AppState:
    db: DB | None = None
    bus: EventBus | None = None
    orchestrator: RunOrchestrator | None = None


state = _AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    try:
        yield
    finally:
        await shutdown()


async def startup():
    state.db = DB()
    await state.db.connect()
    await state.db.init_schema()
    state.bus = EventBus(state.db)
    try:
        llm = _RealLeadLLM(OpenCodeZenClient())
        tavily = TavilySearchTool()
        state.orchestrator = RunOrchestrator(
            db=state.db, bus=state.bus, llm=llm, tavily=tavily,
        )
    except RuntimeError:
        # Missing env vars in dev — leave orchestrator None; tests inject their own
        state.orchestrator = None


async def shutdown():
    if state.db:
        await state.db.close()


app = FastAPI(lifespan=lifespan)


class StartRunReq(BaseModel):
    session_id: str
    topic: str


class AnswerReq(BaseModel):
    question_id: str
    answer: str


@app.post("/runs")
async def post_run(req: StartRunReq):
    if state.orchestrator is None:
        raise HTTPException(503, "orchestrator not configured (check env vars)")
    run_id = await state.orchestrator.start_run(
        session_id=req.session_id, topic=req.topic)
    return {"run_id": run_id}


@app.get("/runs/{run_id}/events")
async def get_events(run_id: str, from_: int = Query(0, alias="from"),
                     limit: int = 1000):
    events = await state.db.fetch_events_from(run_id, from_seq=from_, limit=limit)
    return [json.loads(e.model_dump_json()) for e in events]


@app.get("/runs/{run_id}/events/stream")
async def sse_events(run_id: str, request: Request,
                     last_event_id: int = Query(0, alias="from")):
    q = state.bus.subscribe(run_id)

    async def gen():
        # First: backfill from last_event_id
        backlog = await state.db.fetch_events_from(run_id, from_seq=last_event_id)
        for e in backlog:
            yield f"id: {e.seq}\ndata: {e.model_dump_json()}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    e = await asyncio.wait_for(q.get(), timeout=15.0)
                    if e.seq < last_event_id:
                        continue
                    yield f"id: {e.seq}\ndata: {e.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            state.bus.unsubscribe(run_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/runs/{run_id}/answer")
async def post_answer(run_id: str, req: AnswerReq):
    await state.bus.set_answer(req.question_id, req.answer)
    return {"ok": True}


@app.post("/runs/{run_id}/retry")
async def post_retry(run_id: str, node_id: str):
    # Stretch goal #14 — minimal implementation: re-run the failed researcher.
    # Look up node, spawn new node with same subtopic.
    row = await state.db.fetchone(
        "SELECT role, title, parent_id FROM nodes WHERE id=?", (node_id,))
    if row is None:
        raise HTTPException(404, "node not found")
    role, title, parent_id = row
    if role != "web-researcher":
        raise HTTPException(400, "only web-researcher retries supported")
    if state.orchestrator is None:
        raise HTTPException(503, "no orchestrator")
    import uuid as _u
    new_id = f"r_{_u.uuid4().hex[:8]}"
    await state.orchestrator._create_node(
        run_id, new_id, parent_id, "web-researcher", title, "queued")
    asyncio.create_task(
        state.orchestrator._run_researcher(run_id, new_id, title, parent_id))
    return {"new_node_id": new_id}


@app.get("/runs/{run_id}/artifacts")
async def list_artifacts(run_id: str):
    rows = await state.db.fetchall(
        "SELECT id, node_id, name, kind, bytes FROM artifacts WHERE run_id=?",
        (run_id,))
    return [{"id": r[0], "node_id": r[1], "name": r[2],
             "kind": r[3], "bytes": r[4]} for r in rows]


@app.get("/runs/{run_id}/artifacts/{artifact_id}")
async def get_artifact(run_id: str, artifact_id: str):
    row = await state.db.fetchone(
        "SELECT path_on_disk, name FROM artifacts WHERE id=? AND run_id=?",
        (artifact_id, run_id))
    if row is None:
        raise HTTPException(404, "artifact not found")
    return FileResponse(row[0], filename=row[1])


@app.get("/sessions")
async def list_sessions():
    rows = await state.db.fetchall(
        "SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
    return [{"id": r[0], "title": r[1], "created_at": str(r[2])} for r in rows]


@app.get("/sessions/{session_id}/runs")
async def list_session_runs(session_id: str):
    rows = await state.db.fetchall(
        "SELECT id, topic, status, started_at, finished_at FROM runs "
        "WHERE session_id=? ORDER BY started_at",
        (session_id,))
    return [
        {"id": r[0], "topic": r[1], "status": r[2],
         "started_at": str(r[3]),
         "finished_at": str(r[4]) if r[4] else None}
        for r in rows
    ]


class _RealLeadLLM:
    """Wraps OpenCodeZenClient to expose decompose() and step()."""
    def __init__(self, client: OpenCodeZenClient):
        self.client = client

    async def decompose(self, topic: str, prior_answer: str | None = None):
        user = f"Research request: {topic}"
        if prior_answer:
            user += f"\n\nUser's clarification: {prior_answer}"
        return await self.client.json_call(
            system=LEAD_SYSTEM_PROMPT, user=user,
            schema_hint=DECOMPOSE_SCHEMA_HINT,
        )

    async def step(self, history, subtopic=None):
        # Production wiring of sub-agent step loops via OpenHands SDK is the
        # subject of Task 16 (production hardening). For initial run, use a
        # ReAct-style JSON prompt.
        from backend.agents.web_researcher import WEB_RESEARCHER_PROMPT
        from backend.agents.data_analyst import DATA_ANALYST_PROMPT
        from backend.agents.report_writer import REPORT_WRITER_PROMPT
        system = WEB_RESEARCHER_PROMPT
        if subtopic == "__data__":
            system = DATA_ANALYST_PROMPT
        elif subtopic == "__report__":
            system = REPORT_WRITER_PROMPT
        schema = {
            "kind": "think | tool | finish",
            "text": "string (when kind=think)",
            "tool": {"name": "string", "args": {}},
            "summary": "string (when kind=finish)",
        }
        out = await self.client.json_call(
            system=system,
            user=f"history:\n{json.dumps(history[-10:])}",
            schema_hint=schema,
        )
        if out.get("kind") == "think":
            return ("think", out.get("text", ""))
        if out.get("kind") == "tool":
            return ("tool", out.get("tool", {"name": "", "args": {}}))
        if out.get("kind") == "finish":
            return ("finish", {"summary": out.get("summary", "")})
        return ("finish", {"summary": "(no output)"})
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_api.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py tests/test_api.py
git commit -m "feat(api): FastAPI routes for runs, events, answer, retry, sessions, artifacts"
```

---

## Task 16: OpenHands SDK production wiring (replace `_RealLeadLLM.step`)

This task replaces the ReAct-style JSON loop inside `_RealLeadLLM` with a real OpenHands SDK `Conversation` for each sub-agent. The orchestrator code does not change — only the LLM adapter.

**Files:**
- Modify: `backend/main.py` — replace `_RealLeadLLM` with an `OpenHandsBackedLLM` that, for each sub-agent step, runs one turn of an OpenHands Conversation and maps its emitted Action/Observation back to the (think|tool|finish) tuple our runner expects.
- Add: `backend/agents/openhands_adapter.py`

- [ ] **Step 1: Create `backend/agents/openhands_adapter.py`** (full code below; verify imports against the installed `openhands-sdk` and adjust if class names differ — see SDK note at top of plan)

```python
"""OpenHands SDK adapter. Maps an OpenHands `Conversation` to the
(think|tool|finish) step API our runner expects."""
from __future__ import annotations
from openhands.sdk import Conversation, LLM, Agent
from openhands.sdk.event import (
    MessageEvent, ActionEvent, ObservationEvent, AgentFinishEvent,
)


class OpenHandsConversationLLM:
    """One Conversation per sub-agent role/subtopic."""

    def __init__(self, *, system_prompt: str, model: str, api_key: str,
                 base_url: str, tools: list):
        self.llm = LLM(model=model, api_key=api_key, base_url=base_url)
        self.agent = Agent(llm=self.llm, system_prompt=system_prompt,
                           tools=tools)
        self.conv = Conversation(agent=self.agent)
        self._consumed_event_ids: set[str] = set()

    async def step(self, history):
        """Run one assistant turn; convert its emitted events to a tuple."""
        # Send the most recent user/tool messages into the Conversation.
        last = history[-1] if history else None
        if last and last["role"] == "user":
            await self.conv.send_message(last["content"])
        elif last and last["role"] == "tool":
            await self.conv.add_tool_result(
                tool_call_id=last["tool_call_id"], content=last["content"])

        # Drive one turn
        async for ev in self.conv.step():
            if ev.id in self._consumed_event_ids:
                continue
            self._consumed_event_ids.add(ev.id)
            if isinstance(ev, MessageEvent):
                return ("think", ev.content)
            if isinstance(ev, ActionEvent):
                return ("tool",
                        {"name": ev.tool_name, "args": ev.tool_input,
                         "tool_call_id": ev.tool_call_id})
            if isinstance(ev, AgentFinishEvent):
                return ("finish", {"summary": ev.final_message or ""})
        return ("finish", {"summary": "(no output)"})
```

- [ ] **Step 2: Modify `backend/main.py`** — replace the body of `_RealLeadLLM.step` to dispatch to a per-subtopic `OpenHandsConversationLLM` instance, while keeping `_RealLeadLLM.decompose` unchanged. Find this block in `backend/main.py`:

```python
class _RealLeadLLM:
    """Wraps OpenCodeZenClient to expose decompose() and step()."""
```

Replace the whole class with:

```python
class _RealLeadLLM:
    """Lead decompose uses OpenCode Zen json_call directly; per-subagent step
    loops are driven by OpenHands SDK Conversations."""
    def __init__(self, client: OpenCodeZenClient):
        self.client = client
        self._per_sub: dict[str, "OpenHandsConversationLLM"] = {}

    async def decompose(self, topic: str, prior_answer: str | None = None):
        user = f"Research request: {topic}"
        if prior_answer:
            user += f"\n\nUser's clarification: {prior_answer}"
        return await self.client.json_call(
            system=LEAD_SYSTEM_PROMPT, user=user,
            schema_hint=DECOMPOSE_SCHEMA_HINT,
        )

    def _ohll_for(self, subtopic: str):
        from backend.agents.openhands_adapter import OpenHandsConversationLLM
        from backend.agents.web_researcher import WEB_RESEARCHER_PROMPT
        from backend.agents.data_analyst import DATA_ANALYST_PROMPT
        from backend.agents.report_writer import REPORT_WRITER_PROMPT
        if subtopic in self._per_sub:
            return self._per_sub[subtopic]
        prompt = WEB_RESEARCHER_PROMPT
        if subtopic == "__data__":
            prompt = DATA_ANALYST_PROMPT
        elif subtopic == "__report__":
            prompt = REPORT_WRITER_PROMPT
        # Tools list passed here is just for the model's tool schema; actual
        # execution is handled in run_research_subagent.
        ohll = OpenHandsConversationLLM(
            system_prompt=prompt,
            model=self.client.model, api_key=self.client.api_key,
            base_url=self.client.base_url,
            tools=[
                {"name": "tavily_search",
                 "parameters": {"query": "string",
                                "max_results": "integer"}},
                {"name": "write_artifact",
                 "parameters": {"name": "string", "content": "string",
                                "kind": "string"}},
                {"name": "ask_user",
                 "parameters": {"question": "string",
                                "options": "array"}},
            ],
        )
        self._per_sub[subtopic] = ohll
        return ohll

    async def step(self, history, subtopic=None):
        ohll = self._ohll_for(subtopic or "default")
        return await ohll.step(history)
```

- [ ] **Step 3: Verify all earlier tests still pass**

Run: `uv run pytest -v -k "not test_api"`
Expected: all previous suites pass. (The API test uses FakeLLM, which bypasses OpenHands entirely.)

Run: `uv run pytest tests/test_api.py -v`
Expected: pass (FakeLLM injection still works because the test overrides `state.orchestrator.llm`).

- [ ] **Step 4: Smoke test against real OpenHands SDK and OpenCode Zen**

Manually:
```bash
cp .env.example .env  # fill in OPENCODE_ZEN_API_KEY and TAVILY_API_KEY
make backend           # in terminal 1
curl -X POST http://localhost:8000/runs \
  -H 'content-type: application/json' \
  -d '{"session_id":"smoke","topic":"compare Anthropic and OpenAI on developer ergonomics"}'
# Note the run_id, then:
curl "http://localhost:8000/runs/<RUN_ID>/events?from=0" | jq '.[].type' | head -20
```
Expected: see `run_started`, `node_created` (lead, then 2-4 researchers), `thinking`, `tool_started`/`tool_finished` for `tavily_search`, eventually `run_completed`. If imports in `openhands_adapter.py` fail, adjust them per the installed `openhands-sdk` version and rerun.

- [ ] **Step 5: Commit**

```bash
git add backend/main.py backend/agents/openhands_adapter.py
git commit -m "feat(integration): wire OpenHands SDK Conversations into sub-agent step loop"
```

---

## Task 17: Streamlit API client + state accessors

**Files:**
- Create: `streamlit_app/api_client.py`, `streamlit_app/state.py`

- [ ] **Step 1: Create `streamlit_app/api_client.py`**

```python
"""Thin httpx wrappers around the FastAPI endpoints."""
from __future__ import annotations
import os
import httpx
from backend.schema import AgentEvent, _TYPE_TO_PAYLOAD, EventType

API_BASE = os.getenv("APP_API_BASE", "http://localhost:8000")


def start_run(session_id: str, topic: str) -> str:
    r = httpx.post(f"{API_BASE}/runs",
                   json={"session_id": session_id, "topic": topic},
                   timeout=10.0)
    r.raise_for_status()
    return r.json()["run_id"]


def fetch_events(run_id: str, from_seq: int = 0,
                 limit: int = 200) -> list[AgentEvent]:
    r = httpx.get(f"{API_BASE}/runs/{run_id}/events",
                  params={"from": from_seq, "limit": limit}, timeout=10.0)
    r.raise_for_status()
    out: list[AgentEvent] = []
    for raw in r.json():
        out.append(AgentEvent.model_validate(raw))
    return out


def submit_answer(run_id: str, question_id: str, answer: str):
    r = httpx.post(f"{API_BASE}/runs/{run_id}/answer",
                   json={"question_id": question_id, "answer": answer},
                   timeout=10.0)
    r.raise_for_status()


def retry_node(run_id: str, node_id: str) -> str:
    r = httpx.post(f"{API_BASE}/runs/{run_id}/retry",
                   params={"node_id": node_id}, timeout=10.0)
    r.raise_for_status()
    return r.json()["new_node_id"]


def list_artifacts(run_id: str) -> list[dict]:
    r = httpx.get(f"{API_BASE}/runs/{run_id}/artifacts", timeout=10.0)
    r.raise_for_status()
    return r.json()


def get_artifact_bytes(run_id: str, artifact_id: str) -> bytes:
    r = httpx.get(f"{API_BASE}/runs/{run_id}/artifacts/{artifact_id}",
                  timeout=10.0)
    r.raise_for_status()
    return r.content


def list_sessions() -> list[dict]:
    r = httpx.get(f"{API_BASE}/sessions", timeout=10.0)
    r.raise_for_status()
    return r.json()


def list_session_runs(session_id: str) -> list[dict]:
    r = httpx.get(f"{API_BASE}/sessions/{session_id}/runs", timeout=10.0)
    r.raise_for_status()
    return r.json()
```

- [ ] **Step 2: Create `streamlit_app/state.py`**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/api_client.py streamlit_app/state.py
git commit -m "feat(ui): API client and session_state accessors"
```

---

## Task 18: Trace tree component (with parallel viz)

**Files:**
- Create: `streamlit_app/components/trace_tree.py`

- [ ] **Step 1: Create the trace tree component**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add streamlit_app/components/trace_tree.py
git commit -m "feat(ui): trace tree component with parallel st.columns"
```

---

## Task 19: Chat column + ask_user form

**Files:**
- Create: `streamlit_app/components/chat_column.py`, `streamlit_app/components/ask_user_form.py`

- [ ] **Step 1: Create `streamlit_app/components/ask_user_form.py`**

```python
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
```

- [ ] **Step 2: Create `streamlit_app/components/chat_column.py`**

```python
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
```

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/components/chat_column.py streamlit_app/components/ask_user_form.py
git commit -m "feat(ui): chat column with run stack + ask_user form + ticker"
```

---

## Task 20: Artifacts tab

**Files:**
- Create: `streamlit_app/components/artifacts_tab.py`

- [ ] **Step 1: Create the artifacts tab**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add streamlit_app/components/artifacts_tab.py
git commit -m "feat(ui): artifacts tab + final brief tab"
```

---

## Task 21: Streamlit app entrypoint + polling fragment

**Files:**
- Create: `streamlit_app/app.py`

- [ ] **Step 1: Create `streamlit_app/app.py`**

```python
"""Deep Analyst — Streamlit UI."""
from __future__ import annotations
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


@st.fragment(run_every=f"{get_poll_ms()}ms")
def poll_all_runs():
    """Poll every active run for new events and apply them to UIState."""
    for run in get_runs():
        ui = run["ui_state"]
        if ui.tree is not None and ui.tree.status == "completed":
            continue   # done; stop polling
        from_seq = ui.last_seq + 1
        try:
            events = api_client.fetch_events(run["run_id"], from_seq=from_seq)
        except Exception as e:
            st.toast(f"Poll error: {e}", icon="⚠️")
            return
        for ev in events:
            try:
                apply_event(ui, ev)
            except ValueError as e:
                # gap / unknown node — full re-pull from 0
                ui.__init__()
                events_full = api_client.fetch_events(
                    run["run_id"], from_seq=0, limit=10000)
                for ev2 in events_full:
                    apply_event(ui, ev2)
                break


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
                render_tree(active["ui_state"].tree, active["run_id"])
    with tab_artifacts:
        render_artifacts_tab()
    with tab_brief:
        render_final_brief_tab()

poll_all_runs()
```

- [ ] **Step 2: Manual smoke test**

In two terminals:
```bash
make backend     # terminal 1
make ui          # terminal 2
```
Open http://localhost:8501. Type a research question. Expect to see the lead node appear, then researcher nodes pre-created (queued), then their events stream in. If the lead asks a question, the form should appear and accept your answer.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/app.py
git commit -m "feat(ui): Streamlit entrypoint with polling fragment + multi-tab right column"
```

---

## Task 22: Render snapshot test

**Files:**
- Create: `tests/test_render_snapshot.py`
- Create: `backend/render_markdown.py` (sidecar text renderer used only by tests)

- [ ] **Step 1: Create `backend/render_markdown.py`**

```python
"""Text-only tree renderer for golden-file tests. Not used by the Streamlit UI."""
from __future__ import annotations
from backend.decoder import Node


_ICON = {"queued": "◯", "running": "◐", "awaiting_user": "⏸",
         "completed": "✓", "failed": "✗", "skipped": "—"}


def render_tree_to_markdown(root: Node, depth: int = 0) -> str:
    if root is None:
        return "(empty)"
    indent = "  " * depth
    label = f"{indent}{_ICON.get(root.status, '?')} {root.role}"
    if root.title:
        label += f" — {root.title}"
    out = [label]
    for ev in root.events:
        t = ev.type.value
        if t == "thinking":
            out.append(f"{indent}  ▸ thinking: {ev.payload.text}")
        elif t == "tool_started":
            out.append(f"{indent}  ▸ tool: {ev.payload.tool_name}")
        elif t == "tool_finished":
            ok = "ok" if ev.payload.ok else "fail"
            out.append(f"{indent}  ▸ tool→{ok}: "
                       f"{ev.payload.output_summary[:60]}")
    for c in root.children:
        out.append(render_tree_to_markdown(c, depth + 1))
    return "\n".join(out)
```

- [ ] **Step 2: Create the test** at `tests/test_render_snapshot.py`:

```python
from backend.decoder import UIState, apply_event
from backend.render_markdown import render_tree_to_markdown
from tests.test_decoder import _canonical_event_list


def test_canonical_run_renders_expected_shape():
    s = UIState()
    for ev in _canonical_event_list():
        apply_event(s, ev)
    out = render_tree_to_markdown(s.tree)
    # Hand-built expected shape — update intentionally if event list changes
    assert "✓ root" in out
    assert "lead-analyst" in out
    assert "web-researcher — sub1" in out
    assert "web-researcher — sub2" in out
    # Researchers are children of lead-analyst (indented 2 spaces deeper)
    lines = out.splitlines()
    lead_line = next(i for i, l in enumerate(lines) if "lead-analyst" in l)
    sub_line = next(i for i, l in enumerate(lines) if "sub1" in l)
    assert sub_line > lead_line
    assert lines[sub_line].startswith("    ")  # deeper indent than lead
```

- [ ] **Step 3: Run**

Run: `uv run pytest tests/test_render_snapshot.py -v`
Expected: 1 passed.

- [ ] **Step 4: Commit**

```bash
git add backend/render_markdown.py tests/test_render_snapshot.py
git commit -m "test(render): markdown sidecar renderer + canonical-run snapshot"
```

---

## Task 23: One-pager design document

**Files:**
- Create: `design/one-pager.md`

- [ ] **Step 1: Create `design/one-pager.md`**

```markdown
# Deep Analyst — One-Pager

## Title
Agent-Transparent Research Chat (Domain A) on OpenHands SDK + Streamlit.

## Tenets
1. The decoder is the asset. Raw SDK events normalize to a typed schema on the backend.
2. Node identity is decided at orchestration time, not derived from event content.
3. Persistence is source of truth; UI is a cache. Refresh, replay, and live tail are the same operation.
4. Streamlit's rerun model is a constraint, not a problem — we polled-fragment with a cursor.
5. Block coroutines, never streams.

## Problem
Build a chat application that gives users full transparency into multi-agent execution
(thinking, tool calls, parallel sub-agents, ask_user, artifacts) under two hard constraints:
OpenHands SDK (no native parallel sub-agent delegation) and OpenCode Zen free models.

## Proposed Solution
A Python backend (FastAPI + asyncio + OpenHands SDK) wraps each sub-agent in its own
`Conversation` and runs N of them concurrently via `asyncio.gather`. A `TaggingSubscriber`
stamps each emitted event with a stable `node_id` chosen at orchestration time, so two
parallel `web-researcher` instances always land in distinct tree nodes deterministically.
Events normalize to a 13-type `AgentEvent` schema, persist to SQLite by `(run_id, seq)`,
and stream to a Streamlit UI via `?from=<seq>` polling. The Streamlit app rebuilds the
trace tree client-side with a pure `apply_event` decoder shared with the backend.

## Key Design Questions
- **Single message or multiple per run?** A run is one user message → one trace tree.
  Multiple messages in a session each get their own run, stacked in the chat column.
- **How do parallel agents appear?** Pre-created `queued` nodes show immediately; sibling
  nodes that are simultaneously `running` render side-by-side via `st.columns`.
- **What happens during ask_user?** One coroutine blocks on an `asyncio.Event` keyed by
  `question_id`. The stream stays open; other parallel agents continue. POST `/answer`
  resolves the event and the orchestrator/tool resumes.
- **How are artifacts surfaced?** Inline per-node in the trace, flat in an Artifacts tab,
  and the final brief gets its own tab driven by `run_completed.final_artifact_id`.

## Goals
- All 16 capstone requirements end-to-end.
- Decoder unit tests cover the 13 event types, parallel-no-race, and replay equivalence.
- ask_user works for both lead (structured output) and sub-agent (OpenHands tool).
- Refresh-survives-state via SQLite + on-disk artifacts.
- Model swap is one env-var change.

## Non-goals
- No authentication or multi-user.
- No optimistic UI; polling at 500ms is good enough.
- No streaming of the final report-writer output; arrives as one artifact.
- No deployment story; local dev only.

## Open Questions
1. OpenCode Zen JSON-mode reliability for the lead `decompose()` — fallback regex extract + one retry.
2. OpenHands SDK exact event class names; isolated in `openhands_adapter.py`.
3. Tavily quota under demo load — capped at 5 searches per researcher.
4. Streamlit fragment cost at 500ms; configurable via env.
5. Whether `data-analyst` should ask_user — capability is open; behavior is prompt-tuning.
```

- [ ] **Step 2: Commit**

```bash
git add design/one-pager.md
git commit -m "docs: Amazon-style one-pager design doc"
```

---

## Task 24: README polish + run instructions

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Overwrite `README.md`** with the production version:

```markdown
# Deep Analyst — Agent-Transparent Research Chat

A working chat application that gives full transparency into a multi-agent research
workflow — thinking, tool calls, parallel sub-agents, ask_user pauses, and artifacts —
built on **OpenHands SDK** with **OpenCode Zen** free models, exposed via a **FastAPI**
backend and a **Streamlit** UI.

## Architecture

See `docs/superpowers/specs/2026-05-25-deep-analyst-openhands-design.md` and
`design/one-pager.md`. Two-process layout: FastAPI on `:8000`, Streamlit on `:8501`.

```
User → Streamlit (polling) → FastAPI → RunOrchestrator → N parallel OpenHands Conversations
                                            │                       │
                                            ▼                       ▼
                                          SQLite ← EventBus ← TaggingSubscriber
```

## Quick start

```bash
make install                # uv venv + deps
cp .env.example .env        # fill in OPENCODE_ZEN_API_KEY and TAVILY_API_KEY
make backend                # terminal 1
make ui                     # terminal 2
open http://localhost:8501
```

## What to try

1. **Simple decompose:** ask "Compare LangChain and CrewAI for enterprise agents."
   Expect: lead decomposes into 2-3 subtopics, researchers run in parallel, final brief appears.
2. **Lead ask_user:** ask "Research AI." Expect: lead asks a scoping question; answer it; run proceeds.
3. **Refresh in the middle:** while a run is mid-flight, refresh the browser. Expect: all events replay from SQLite, tree rebuilds.
4. **Retry a failed researcher:** if a Tavily search fails, click "Retry this researcher" on the failed node.

## Tests

```bash
make test
```

Test suites:
- `test_schema.py` — Pydantic AgentEvent envelope validation.
- `test_db.py` — atomic `next_seq`, event round-trip.
- `test_decoder.py` — all 13 event types, parallel-no-race, replay equivalence.
- `test_bus.py` — emit/subscribe, ask_user gate.
- `test_subagent_runner.py` — researcher loop with FakeLLM.
- `test_orchestrator.py` — canonical run + lead ask_user pause/resume.
- `test_api.py` — POST /runs, GET /events (polling), POST /answer.
- `test_llm.py`, `test_tools_tavily.py`, `test_tools_write_artifact.py`, `test_tools_ask_user.py`.
- `test_render_snapshot.py` — markdown snapshot of the trace tree.

## Known limitations

- **OpenHands SDK event class names** are pinned in `backend/agents/openhands_adapter.py`.
  If your installed SDK version differs, adjust imports there. The rest of the system
  speaks only the normalized `AgentEvent` schema.
- **OpenCode Zen free models** vary in JSON-mode reliability. Lead `decompose()` falls
  back to a regex extract on parse failure and retries once. If your chosen model
  exceeds a ~10% malformed-JSON rate, swap models via `OPENCODE_ZEN_MODEL`.
- **Tavily free tier** is 1,000 searches/month. Each researcher caps at 5 searches.
- **Streamlit polling** is 500ms; configurable via `APP_POLL_INTERVAL_MS`. The fragment
  re-execution model means very rapid event bursts may visually arrive in clusters.
- **No authentication.** Single local user; sessions are local-only in SQLite.

## File map

| Path | Purpose |
|---|---|
| `backend/schema.py` | 13-type `AgentEvent` Pydantic schema |
| `backend/db.py` | aiosqlite wrapper, atomic `next_seq` |
| `backend/bus.py` | EventBus + TaggingSubscriber |
| `backend/decoder.py` | Pure `apply_event` + Node tree |
| `backend/llm.py` | OpenCode Zen client + json_call + retry |
| `backend/tools/*.py` | tavily_search, write_artifact, ask_user |
| `backend/agents/*.py` | system prompts + OpenHands adapter |
| `backend/orchestrator.py` | `RunOrchestrator` (gather over parallel subs) |
| `backend/main.py` | FastAPI app + all routes |
| `streamlit_app/` | UI (entrypoint + components) |
| `tests/` | pytest suites |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: production README with quick start, tests, limitations"
```

---

## Self-review (against spec)

Coverage check — every capstone requirement (#1-#16) mapped to a task:

| # | Requirement | Task(s) |
|---|---|---|
| 1 | Event stream consumer | T17, T21 (polling fragment) |
| 2 | Agent event decoder | T2 (schema), T5 (apply_event) |
| 3 | Trace tree builder | T4, T5 |
| 4 | Expandable trace panel | T18 (st.expander) |
| 5 | Parallel agent visualization | T14 (orchestrator emits queued siblings), T18 (st.columns) |
| 6 | ask_user flow | T11 (tool), T14 (lead path), T15 (POST /answer), T19 (form) |
| 7 | Chat panel with live status | T19, T21 |
| 8 | Agent state indicators | T18 (`_STATUS_ICON`) |
| 9 | Artifact collection | T10 (tool), T20 (tab) |
| 10 | Error handling | T14 (try/except in orchestrator), T18 (error display), T21 (poll error toast) |
| 11 | Reconnection with replay | T5 (idempotent cursor), T15 (GET /events?from=), T21 (re-pull on gap) |
| 12 | Auto-collapse completed nodes | T18 (`expanded=node.status in ("running", ...)`)|
| 13 | Multi-run stacking | T17 (`get_runs`), T19 (run-stack expanders) |
| 14 | Retry/Rerun on error | T15 (POST /retry), T18 (retry button) |
| 15 | Activity ticker | T17 (`latest_activity_line`), T19 (st.caption) |
| 16 | Persistence | T3 (SQLite), T15 (sessions endpoints), T21 (cold-start re-pull) |

Placeholder scan: no "TBD", no "implement later", every code step is complete code.

Type consistency: `AgentEvent`, `EventType`, `Node`, `UIState`, `EventBus`, `TaggingSubscriber`, `RunOrchestrator` names are used consistently across tasks. The `subscriber` parameter name in `run_research_subagent` matches across Tasks 12 and 14.

Spec sections covered:
- Architecture diagram → T15 + T21
- Agent + node model → T4
- Execution flow → T14
- TaggingSubscriber + bus → T7, T12
- Event schema (13 types) → T2
- apply_event → T5
- ask_user end-to-end → T11, T14, T19
- Persistence schema (6 tables) → T3
- Multi-run stacking → T19
- Artifacts surfacing → T10, T20
- Error handling + retry → T14, T15, T18
- Testing strategy → covered by per-task tests + T22

All clear.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-25-deep-analyst-openhands.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for a 24-task plan with strong test discipline.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
