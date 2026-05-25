# Deep Analyst — Research Intelligence Platform (OpenHands SDK + Streamlit)

**Spec date:** 2026-05-25
**Domain:** A — "Deep Analyst" multi-agent research platform
**Scope:** All 16 capstone requirements (must-haves 1–10 + stretch 11–16)
**Constraints (hard):**
- Agent framework: **OpenHands SDK** (not Claude Agent SDK)
- LLM API: **OpenCode Zen** free models (OpenAI-compatible); default `grok-code-fast-1`, swappable via env var

---

## Tenets

1. **The decoder is the asset.** Raw OpenHands events are normalized to a typed `AgentEvent` schema on the backend; the UI and tests consume only the normalized schema.
2. **Node identity is decided at orchestration time, not derived from event content.** This is the only safe way to render parallel sub-agents of the same role.
3. **Persistence is the source of truth; the UI is a cache.** Refresh, reconnect, and replay are the same operation: read from SQLite by `(run_id, seq)`.
4. **Streamlit's rerun model is a constraint, not a problem.** We work with it (polling fragment, session_state cursor, in-place placeholders), not against it.
5. **Block coroutines, never streams.** ask_user pauses one asyncio task; the SSE/polling channel and all sibling agents keep moving.

---

## Problem

The capstone requires a chat application that gives users full transparency into multi-agent execution: thinking, tool calls, parallel sub-agents, ask_user pauses, and artifact output. The agent framework is fixed to OpenHands SDK (which does not natively parallelize sub-agent delegation the way Claude Agent SDK's `Task` tool does) and the LLM provider is fixed to OpenCode Zen free models (OpenAI-compatible, function-calling capable but variable quality across the free roster).

The hard problems are:

- **Parallel sub-agents under OpenHands.** Native `AgentDelegateAction` is sequential. We need true concurrency to satisfy the "parallel agent visualization" requirement.
- **Trace tree under parallelism.** Two `web-researcher` instances with identical role and tool schemas must land in distinct tree nodes deterministically. No race conditions.
- **ask_user without closing the stream.** The README explicitly flags this as a common pitfall. The stream stays open; only event production pauses.
- **All 16 features at once.** Persistence, replay, multi-run stacking, retry/rerun, and activity ticker are stretch goals that interact tightly — they have to be designed in from the start, not bolted on.

---

## Proposed Solution

### Architecture (two processes, one language)

Python everywhere. Streamlit on `:8501`, FastAPI on `:8000`, SQLite as the persistence layer, OpenHands SDK in-process inside FastAPI.

```
┌──────────────────────────────────────────────────────────────────┐
│              Streamlit app   (Python, port 8501)                 │
│                                                                  │
│  st.session_state: { current_run_id, runs[], last_seq, tree,    │
│                       pending_question, artifacts }              │
│                                                                  │
│  Chat column                Trace + Artifacts column             │
│   - live status line         - st.expander tree                  │
│   - ask_user form            - st.columns for parallel viz       │
│   - run-stack expanders      - st.tabs: Trace | Artifacts | Brief│
│                                                                  │
│  @st.fragment(run_every="0.5s")  ← poller per active run        │
│      events = GET /runs/{id}/events?from=last_seq               │
│      for ev in events: apply_event(state, ev)                   │
│      last_seq = events[-1].seq                                  │
└─────────────────────────┬────────────────────────────────────────┘
                          │ httpx (REST; SSE endpoint also exposed
                          │        for non-Streamlit consumers)
                          ▼
┌──────────────────────────────────────────────────────────────────┐
│                  FastAPI backend  (port 8000)                    │
│                                                                  │
│   POST  /runs                       start a run, returns run_id  │
│   GET   /runs/{id}/events?from=&limit=   batch pull (Streamlit) │
│   GET   /runs/{id}/events                SSE stream              │
│   POST  /runs/{id}/answer                submit ask_user answer  │
│   POST  /runs/{id}/retry                 retry a failed sub-node │
│   GET   /runs/{id}/artifacts             list artifacts          │
│   GET   /runs/{id}/artifacts/{name}      fetch artifact content  │
│   GET   /sessions                        list past sessions      │
│   GET   /sessions/{id}/runs              list runs in a session  │
│                                                                  │
│   ┌────────────────────────────────────────────────────────┐     │
│   │           RunOrchestrator (asyncio)                    │     │
│   │  lead-analyst = Python wrapping one LLM decompose call │     │
│   │  → asyncio.gather over N OpenHands Conversations       │     │
│   │  → sequential data-analyst → sequential report-writer  │     │
│   └────────┬────────────────────────────────────┬──────────┘     │
│            │                                    │                │
│      OpenHands Conversation …N parallel… OpenHands Conversation  │
│            │                                    │                │
│            └───────── EventBus ──────────────────┘               │
│                normalizes → AgentEvent schema                    │
│                writes (run_id, seq) into SQLite                  │
│                publishes to in-memory pub/sub for SSE            │
└──────────────────────────────────────────────────────────────────┘
            │                                       │
            ▼                                       ▼
   OpenCode Zen  (grok-code-fast-1)       Tavily Search API
```

### Agent + node model

Every visible item in the trace tree is a `Node`. There are two `Node` views — the **backend persistence view** (one row in `nodes` table) and the **UI tree view** (built by `apply_event` from the event stream). The persistence view is the contract; the UI view is reconstructable from events:

```python
# Backend persistence view (mirror of the `nodes` table)
class NodeRow:
    id: str                        # stable, UUID
    parent_id: str | None          # None for run-root
    run_id: str
    role: Literal["root", "lead-analyst", "web-researcher",
                  "data-analyst", "report-writer"]
    title: str | None              # the subtopic for researchers
    status: Literal["queued", "running", "awaiting_user",
                    "completed", "failed", "skipped"]
    summary: str | None            # set on completion

# UI tree view (rebuilt from events by apply_event)
class Node(NodeRow):
    children: list["Node"]
    events: list[AgentEvent]       # thinking / agent_message / tool_started / tool_finished
    artifact_ids: list[str]
    errors: list[ErrorPayload]
```

Nodes are **pre-created in `queued` state** before any sub-agent starts. This eliminates the "blank until first event arrives" pitfall and gives the UI immediate visual feedback that work is dispatched.

### Execution flow (canonical run)

```
RunOrchestrator.run(topic):

  1. INSERT run row; emit run_started, seq=0, node_id=root
  2. emit node_created (role=lead-analyst, status=running)

  3. LLM decompose(topic)  ── single OpenCode Zen call, JSON-mode
     stream tokens as `thinking` events
     output schema:
       { action: "decompose", subtopics: [str, str, str] }
       | { action: "ask_user", question: str, options?: [str] }

  4. if ask_user:
        INSERT pending_questions, emit ask_user event
        await answer (asyncio.Event)
        emit ask_user_answered; loop to step 3 with answer in context

  5. for each subtopic[i]:
        pre-create node web-researcher[i],
                        parent=lead-analyst,
                        title=subtopic[i],
                        status=queued
        emit node_created

  6. asyncio.gather(  ← THE parallel point
        run_subagent(web-researcher[0]),
        run_subagent(web-researcher[1]),
        run_subagent(web-researcher[2]),
     )

  7. await all → node data-analyst (parent=lead), sequential
  8. node report-writer (parent=lead), sequential
  9. emit run_completed; UPDATE run.status = completed
```

`run_subagent`:

```python
async def run_subagent(node):
    set_status(node, "running")                  # emits node_status_changed
    conv = openhands.Conversation(
        agent=web_researcher_agent(subtopic=node.title),
        tools=[tavily_search, write_artifact, ask_user, read_file],
        llm=opencode_zen_llm(model=settings.MODEL),
    )
    subscriber = TaggingSubscriber(
        run_id=node.run_id,
        node_id=node.id,
        parent_node_id=node.parent_id,
        bus=event_bus,
    )
    conv.event_stream.subscribe(subscriber)
    try:
        result = await conv.run()
        set_status(node, "completed")
        emit_subagent_completed(node, summary=result.summary,
                                artifact_ids=collected_artifact_ids)
    except Exception as e:
        emit_error(where="conversation", node_id_ref=node.id,
                   message=str(e), recoverable=False)
        set_status(node, "failed")
```

### EventBus + TaggingSubscriber (the parent-tagging mechanism)

```python
class TaggingSubscriber:
    """
    Wraps an OpenHands Conversation's event_stream subscription.
    Owns the node identity for everything emitted by that Conversation.
    """
    def __init__(self, run_id, node_id, parent_node_id, bus):
        self.ctx = NodeContext(run_id, node_id, parent_node_id)
        self.bus = bus

    async def on_event(self, raw_event):
        normalized = self._normalize(raw_event)   # raw OH → AgentEvent type
        await self.bus.emit(
            type=normalized.type,
            payload=normalized.payload,
            run_id=self.ctx.run_id,
            node_id=self.ctx.node_id,             # <-- stamped here, NOT from raw
            parent_node_id=self.ctx.parent_node_id,
        )

    def _normalize(self, raw) -> NormalizedEvent:
        match raw:
            case MessageAction(content=text, source="agent"):
                return Norm("agent_message", AgentMessagePayload(text=text))
            case ThinkingEvent(text=t, delta=d):
                return Norm("thinking", ThinkingPayload(text=t, delta=d))
            case ToolCallAction(name=n, input=i, id=tcid):
                return Norm("tool_started",
                            ToolStartedPayload(tool_name=n, tool_call_id=tcid, input=i))
            case ObservationEvent(tool_call_id=tcid, output=o, ok=ok):
                summary, ref = self._maybe_artifact_extract(o)
                return Norm("tool_finished",
                            ToolFinishedPayload(tool_call_id=tcid,
                                                output_summary=summary,
                                                ok=ok, output_ref=ref))
            case ErrorEvent(where=w, message=m, recoverable=r):
                return Norm("error",
                            ErrorPayload(where=w, message=m,
                                         recoverable=r,
                                         node_id_ref=self.ctx.node_id))
            # ... full match in backend/bus.py
```

Two `web-researcher` Conversations running concurrently each have their own subscriber instance with their own closure-captured `node_id`. Their raw events are byte-identical in shape; their normalized events differ only in `node_id`. **No race possible** — the node identity is in the subscriber, not derived from the event payload.

### EventBus.emit

```python
async def emit(self, *, type, payload, run_id, node_id, parent_node_id):
    async with self._lock_for(run_id):
        seq = await self.db.next_seq(run_id)         # atomic counter
        ev = AgentEvent(
            seq=seq, run_id=run_id, ts=utcnow(),
            type=type, node_id=node_id,
            parent_node_id=parent_node_id, payload=payload,
        )
        await self.db.insert_event(ev)               # SQLite write
        for q in self._subscribers[run_id]:          # pub/sub for SSE
            q.put_nowait(ev)
```

The `_lock_for(run_id)` ensures `seq` is gap-free monotonic within a run even under heavy parallelism. (Cross-run, no lock needed.)

### Typed AgentEvent schema (on-wire contract)

Envelope:

```python
class AgentEvent(BaseModel):
    seq: int                       # monotonic per run_id, gap-free
    run_id: str
    node_id: str
    parent_node_id: str | None
    ts: datetime
    type: EventType                # discriminator
    payload: EventPayload          # union narrowed by `type`
```

The 13 event types:

| `type` | Payload fields | Emitted when |
|---|---|---|
| `run_started` | `topic: str` | POST /runs accepted, before any LLM call |
| `node_created` | `role: str`, `title: str \| None`, `status: "queued" \| "running"` | Orchestrator creates a node |
| `node_status_changed` | `status`, `reason: str \| None` | Any status transition |
| `thinking` | `text: str`, `delta: bool` | LLM reasoning tokens (streaming or block) |
| `agent_message` | `text: str` | Agent's user-visible message |
| `tool_started` | `tool_name: str`, `tool_call_id: str`, `input: dict` | Any OpenHands tool invocation |
| `tool_finished` | `tool_call_id: str`, `output_summary: str`, `ok: bool`, `output_ref: str \| None` | Tool returns. Large outputs are stored as artifacts; `output_ref` is the artifact id |
| `ask_user` | `question_id: str`, `question: str`, `options: list[str] \| None`, `asked_by: "lead" \| "subagent"` | Lead structured-output ask OR sub-agent `ask_user` tool call |
| `ask_user_answered` | `question_id: str`, `answer: str` | POST /answer received |
| `artifact_created` | `artifact_id: str`, `name: str`, `kind: Literal[...]`, `bytes: int` | A sub-agent writes a file the user should see |
| `subagent_completed` | `summary: str`, `artifact_ids: list[str]` | Sub-agent finished; convenience for UI summary card |
| `error` | `where: Literal[...]`, `message: str`, `recoverable: bool`, `node_id_ref: str` | Anything raised |
| `run_completed` | `final_artifact_id: str`, `total_tokens: int \| None` | Report-writer done |

### Decoder (the pure function the UI calls)

`backend/decoder.py` — imported by both FastAPI (for assertions) and Streamlit (for actual rendering). One function:

```python
def apply_event(state: UIState, ev: AgentEvent) -> None:
    match ev.type:
        case "run_started":
            state.tree = Node(id=ev.node_id, role="root",
                              title=ev.payload.topic,
                              status="running", children=[])
        case "node_created":
            parent = state.tree.find(ev.parent_node_id)
            parent.children.append(Node(
                id=ev.node_id, role=ev.payload.role,
                title=ev.payload.title,
                status=ev.payload.status,
                children=[], events=[]))
        case "node_status_changed":
            state.tree.find(ev.node_id).status = ev.payload.status
        case "thinking" | "agent_message" | "tool_started" | "tool_finished":
            state.tree.find(ev.node_id).events.append(ev)
        case "ask_user":
            state.pending_question = ev.payload
            state.tree.find(ev.node_id).status = "awaiting_user"
        case "ask_user_answered":
            state.pending_question = None
        case "artifact_created":
            state.artifacts.append(ev.payload)
            state.tree.find(ev.node_id).artifact_ids.append(ev.payload.artifact_id)
        case "subagent_completed":
            n = state.tree.find(ev.node_id)
            n.summary = ev.payload.summary
        case "error":
            state.tree.find(ev.payload.node_id_ref).errors.append(ev.payload)
        case "run_completed":
            state.tree.status = "completed"
            state.final_artifact_id = ev.payload.final_artifact_id
```

This function is total over the union and idempotent under cursor honoring. It is the heart of the "Decoder tests" deliverable.

### ask_user end-to-end

**Path A — lead-analyst asks (structured output).** The decompose LLM call returns `{action: "ask_user", question, options}`. Orchestrator inserts `pending_questions`, emits `ask_user`, awaits `asyncio.Event`. When `/runs/{id}/answer` arrives, the row is updated, `ask_user_answered` is emitted, the event is set, decompose() re-runs with the answer in context.

**Path B — sub-agent asks (OpenHands tool, transparent to LLM).** Sub-agents are configured with an `ask_user` tool:

```python
class AskUserTool(Tool):
    name = "ask_user"
    description = "Ask the human user a clarifying question. Use sparingly."
    parameters = {"question": str, "options": list[str] | None}

    async def call(self, question, options=None):
        q_id = uuid()
        await self._ctx.bus.emit(
            type="ask_user", node_id=self._ctx.node_id,
            parent_node_id=self._ctx.parent_node_id,
            payload=AskUserPayload(question_id=q_id, question=question,
                                   options=options, asked_by="subagent"))
        await self._ctx.bus.persist_pending(q_id, node_id=self._ctx.node_id)
        answer = await self._ctx.bus.await_answer(q_id)   # blocks this task only
        await self._ctx.bus.emit(
            type="ask_user_answered", node_id=self._ctx.node_id,
            parent_node_id=self._ctx.parent_node_id,
            payload=AskUserAnsweredPayload(question_id=q_id, answer=answer))
        return ToolResult(content=answer)
```

From OpenHands' perspective, this is just a slow tool. The SDK doesn't pause or special-case anything. The Conversation's sibling tasks (other parallel `web-researcher` instances) keep running because each is its own asyncio task. **This is how we never close the stream during a pause** (README pitfall): we block one coroutine, not the channel.

### Persistence schema (6 tables)

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    title TEXT
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    topic TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    next_seq INTEGER NOT NULL DEFAULT 0          -- atomic counter
);

CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    parent_id TEXT REFERENCES nodes(id),
    role TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    summary TEXT
);

CREATE TABLE events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    node_id TEXT NOT NULL,
    parent_node_id TEXT,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX idx_events_node ON events(run_id, node_id);

CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    node_id TEXT NOT NULL REFERENCES nodes(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    path_on_disk TEXT NOT NULL
);

CREATE TABLE pending_questions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    node_id TEXT NOT NULL REFERENCES nodes(id),
    question TEXT NOT NULL,
    options_json TEXT,
    answer TEXT,
    asked_at TIMESTAMP NOT NULL,
    answered_at TIMESTAMP
);
```

Artifacts live on disk at `./.data/artifacts/{run_id}/{node_id}/{name}`. SQLite stores metadata + path only.

### Multi-run stacking + replay

A session has many runs. The Streamlit UI renders runs as a vertical stack of `st.expander`s; completed runs auto-collapse, the active run auto-expands. One `@st.fragment(run_every=0.5)` poller per active run (usually 1; supports more if the user fires a second message mid-run).

`st.session_state.last_seq[run_id]` is the cursor. Every poll is `GET /runs/{id}/events?from=<last_seq>&limit=200`. **Replay and live are the same code path** — there is no separate reconnect handler. On Streamlit refresh, the cold start is just `?from=0`.

### Artifacts surfacing

Three views, one source of truth:

1. **Inline in trace tree** — each node lists its `artifact_ids` with click-to-expand.
2. **Artifacts tab** — flat dataframe (node, name, kind, size, created_at) across the whole run, with type-appropriate inline preview: `st.markdown` for `.md`, `st.code(language=...)` for `.sql`/`.yaml`/`.json`, `st.image` for charts, `st.download_button` always.
3. **Final Brief tab** — renders `run.final_artifact_id` directly when `run_completed` arrives. Always one click away.

Large tool outputs (>4KB) are auto-promoted to internal artifacts (e.g. `tavily_result_<id>.json`) so events stay small but full content remains accessible.

### Error handling + retry/rerun

Error taxonomy (the `error.where` field):

| `where` | Recoverable? | Behavior |
|---|---|---|
| `llm` | Yes (auto-retry w/ exponential backoff, max 3) | Silent for first 2 attempts; surfaces on the 3rd. Yellow toast on the node. |
| `tool` | Sometimes | Tool row shows red icon; the sub-agent's LLM decides whether to continue. |
| `conversation` | No | Sub-agent node → `failed`; orchestrator continues with siblings. |
| `orchestrator` | No | Run → `failed`; fatal banner with "Retry from here" button. |

Retry granularity (stretch #14):

- **Retry this sub-agent** — POST `/runs/{id}/retry` with `node_id`. Spawns a fresh Conversation on the same subtopic; old node kept as tombstone for honest history.
- **Skip and continue** — marks failed node `skipped`; orchestrator proceeds. data-analyst is robust to missing notes (reads whatever exists in `./.data/artifacts/{run_id}/`).
- **Retry the whole run** — new run with same topic + replayed ask_user answers.

Activity ticker (stretch #15) is a `st.caption` strip showing the most recent `tool_started` or `thinking` event across all running nodes. Format: `◐ web-researcher#2: searching "Enterprise AI agent deployments"…` Driven by the same `apply_event` pipeline.

### Testing strategy

1. **Decoder unit tests** (`tests/test_decoder.py`) — fixtures are JSON event lists; assertions are tree snapshots. Cover:
   - All 13 event types route correctly.
   - Two parallel `web-researcher` nodes get independent event lists.
   - ask_user → pending set → ask_user_answered → pending cleared.
   - Replay equivalence: applying events 1..N then N+1..M equals applying 1..M.
   - Gap or out-of-order `seq` raises (contract is gap-free monotonic).
2. **Orchestrator integration** (`tests/test_orchestrator.py`) — `FakeLLM` + `FakeTavily`. Drives full run; asserts event sequence shape, `parent_node_id` correctness, real interleaving of parallel researchers via `asyncio.sleep`.
3. **API smoke** (`tests/test_api.py`) — happy path via `httpx.AsyncClient`. No network.
4. **Render snapshot** (`tests/test_render_snapshot.py`) — `render_tree_to_markdown` golden files (sidecar renderer, not the UI).

### Repo layout

```
.
├── README.md                            # setup, architecture overview, limitations
├── pyproject.toml                       # uv-managed
├── Makefile                             # make dev / make test / make demo
├── .env.example                         # OPENCODE_ZEN_API_KEY, OPENCODE_ZEN_BASE_URL,
│                                        # OPENCODE_ZEN_MODEL=grok-code-fast-1,
│                                        # TAVILY_API_KEY
├── docs/
│   └── superpowers/specs/
│       └── 2026-05-25-deep-analyst-openhands-design.md
├── design/
│   └── one-pager.md                     # Amazon-style deliverable
├── backend/
│   ├── main.py                          # FastAPI app + routes
│   ├── schema.py                        # Pydantic AgentEvent + payloads
│   ├── db.py                            # aiosqlite + migrations
│   ├── bus.py                           # EventBus + TaggingSubscriber
│   ├── orchestrator.py                  # RunOrchestrator
│   ├── llm.py                           # OpenCode Zen client wrapper
│   ├── decoder.py                       # apply_event(state, ev); shared with UI
│   ├── agents/
│   │   ├── lead.py                      # decompose() prompt + JSON-mode
│   │   ├── web_researcher.py
│   │   ├── data_analyst.py
│   │   └── report_writer.py
│   └── tools/
│       ├── tavily_search.py
│       ├── write_artifact.py
│       └── ask_user.py
├── streamlit_app/
│   ├── app.py                           # entrypoint
│   ├── api_client.py                    # httpx wrappers
│   ├── state.py                         # st.session_state typed accessors
│   └── components/
│       ├── chat_column.py
│       ├── trace_tree.py                # st.expander + st.columns parallel viz
│       ├── artifacts_tab.py
│       └── ask_user_form.py
├── tests/
│   ├── test_decoder.py
│   ├── test_orchestrator.py
│   ├── test_api.py
│   ├── test_render_snapshot.py
│   └── fixtures/
│       ├── canonical_run.json
│       ├── parallel_no_race.json
│       └── replay_equivalence.json
└── .data/                               # gitignored
    ├── app.db
    └── artifacts/{run_id}/...
```

---

## Goals

- All 10 must-have requirements met end-to-end.
- All 6 stretch requirements (#11–#16) met end-to-end.
- Decoder is unit-tested with explicit parallel-no-race and replay-equivalence fixtures.
- Trace tree correctly nests parallel sub-agents of the same role under their parent, with no race conditions.
- ask_user pause/resume works for both lead (structured output) and sub-agent (OpenHands tool) sources; the stream never closes during a pause.
- Persistence survives Streamlit page refresh and process restart.
- Model is swappable via env var without code changes.

---

## Non-goals

- **No authentication / multi-user.** Single local user; sessions are local-only in SQLite.
- **No optimistic UI.** Streamlit + 0.5s polling makes optimistic updates bug-prone.
- **No streaming the final report.** The brief arrives as one `artifact_created` + `run_completed`. `thinking` events stream only during sub-agent runs.
- **No deployment story.** Local development only. Dockerfile is nice-to-have, not in scope.
- **No telemetry / metrics.** Out of scope.
- **No alternative frontends.** SSE endpoint exists for completeness, but the only supported UI is the bundled Streamlit app.
- **No OpenHands agent-server / sandboxed runtime container.** OpenHands runs in-process inside FastAPI. The `write_artifact` tool writes to a constrained directory; no further sandboxing.

---

## Open Questions

1. **OpenCode Zen model JSON-mode reliability.** The lead-analyst's `decompose()` depends on structured output. If `grok-code-fast-1` returns malformed JSON, we fall back to a regex extractor + one retry. If the fallback rate is >10%, we switch the default model. Owner: implementation phase, instrumented in `backend/llm.py`.
2. **OpenHands SDK API surface stability.** Event class names (`MessageAction`, `ObservationEvent`, `ThinkingEvent`) are taken from current OpenHands SDK conventions; exact import paths will be validated against the installed version during implementation. The `TaggingSubscriber` interface is the only piece coupled to this surface; isolated for easy adjustment.
3. **Tavily quota under demo conditions.** 1,000 searches/month is generous but finite. We cap each sub-agent at 5 searches (configurable) and surface a clear error if Tavily 429s.
4. **Streamlit fragment re-execution cost.** 0.5s polling × multiple active runs could feel laggy on slow machines. The poll interval is configurable in `streamlit_app/app.py`; we'll tune during dev.
5. **Whether `data-analyst` should be allowed to ask_user.** The spec currently allows any sub-agent to use the tool; the README's example only shows researchers asking. We'll keep the capability available; whether the agent prompt encourages it is a prompt-tuning decision, not architectural.

---

## Appendix A — Constraint mapping (every README requirement → where it lives)

| # | Requirement | Where in this design |
|---|---|---|
| 1 | Event stream consumer | Streamlit `@st.fragment(run_every=0.5)` polling `?from=last_seq` |
| 2 | Agent event decoder | `backend/decoder.py::apply_event` |
| 3 | Trace tree builder | Same `apply_event`; tree lives in `st.session_state.tree` |
| 4 | Expandable trace panel | `streamlit_app/components/trace_tree.py` using `st.expander` |
| 5 | Parallel agent visualization | `st.columns` rendering siblings side-by-side when parent has >1 running child |
| 6 | ask_user flow | Section "ask_user end-to-end"; both paths use same wire shape |
| 7 | Chat panel with live status | `streamlit_app/components/chat_column.py` + activity ticker |
| 8 | Agent state indicators | `Node.status` enum rendered with icons (◯ queued / ◐ running / ⏸ awaiting / ✓ completed / ✗ failed) |
| 9 | Artifact collection | `artifact_created` events + `streamlit_app/components/artifacts_tab.py` |
| 10 | Error handling | `error` event + node-level error display + non-fatal toast |
| 11 | Stream reconnection with replay | Cursor-based polling; `?from=last_seq` is identical for live and resume |
| 12 | Auto-collapse completed nodes | `st.expander(expanded=node.status == "running")` |
| 13 | Multi-run stacking | `runs` table + stack of `st.expander`s in chat column |
| 14 | Retry/Rerun on error | `POST /runs/{id}/retry` + UI buttons on failed nodes |
| 15 | Activity ticker | `st.caption` driven by most-recent `tool_started`/`thinking` event |
| 16 | Persistence | SQLite + on-disk artifacts; refresh re-fetches by run_id |
