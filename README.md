# Deep Analyst — Agent-Transparent Research Chat

---

A real-time multi-agent research platform that makes the invisible visible — every tool call, thinking step, parallel branch, and human-in-the-loop pause rendered live as a navigable trace tree.

Demo link: https://www.loom.com/share/a0efddc7404140dfbbfb9a04d268db15

---

## Architecture Overview

I built Deep Analyst as a two-process system: a **FastAPI backend** (the orchestration engine) and a **Streamlit frontend** (the live trace UI). They communicate over HTTP — the frontend polls `/runs/{id}/events` for a stream of typed events and renders them into a navigable tree in real time.

The core insight behind my architecture is that **agent orchestration and agent observation are two separate concerns** that should share a single source of truth: the event stream. The backend produces events; the frontend consumes them through a deterministic decoder. Both sides import the same `schema.py` and `decoder.py`, so there's zero drift between what the system does and what the user sees.

```
┌──────────────────────────────────────────────────────────────────┐
│  Streamlit UI (streamlit_app/)                                   │
│  ┌──────────┐  ┌────────────┐  ┌──────────────┐                │
│  │ChatColumn│  │ Trace Tree │  │ Artifacts Tab│                 │
│  └────┬─────┘  └─────┬──────┘  └──────┬───────┘                │
│       │               │                │                         │
│       └───────────────┼────────────────┘                         │
│                       │ poll / submit_answer                     │
└───────────────────────┼──────────────────────────────────────────┘
                        │ HTTP
┌───────────────────────┼──────────────────────────────────────────┐
│  FastAPI Backend (backend/)                                       │
│                       │                                           │
│  ┌────────────────────▼──────────────────────────┐               │
│  │            RunOrchestrator                     │               │
│  │  lead decompose → parallel researchers →      │               │
│  │  sequential data-analyst → report-writer      │               │
│  └────────────┬──────────────────────────────────┘               │
│               │                                                   │
│  ┌────────────▼────────────┐  ┌─────────────────────────┐       │
│  │      EventBus           │  │   OpenCodeZenClient     │       │
│  │  (pub/sub + persist)    │  │   (LLM tool-calling)    │       │
│  └────────────┬────────────┘  └─────────────────────────┘       │
│               │                                                   │
│  ┌────────────▼────────────┐                                     │
│  │  SQLite via aiosqlite   │                                     │
│  │  (WAL mode, monotonic   │                                     │
│  │   seq per run)          │                                     │
│  └─────────────────────────┘                                     │
└──────────────────────────────────────────────────────────────────┘
```

---

## Design Decisions

### 1. Event Sourcing as the Single Source of Truth

I chose event sourcing over a mutable-state API because the entire point of Deep Analyst is transparency. Every agent action — thinking, tool calls, user pauses, errors — is captured as an immutable `AgentEvent` with a monotonic sequence number per run. The UI doesn't ask "what's the current state?" — it replays events through a pure `apply_event` function to reconstruct the tree. This gives me:

- **Time-travel debugging** — I can replay any run from event 0 to see exactly what happened.
- **Gap-free consistency** — the decoder rejects sequence gaps, so the UI either shows a correct tree or raises immediately.
- **Idempotent replay** — `apply_event` skips already-seen seqs, making reconnection trivial.

### 2. Typed Events with Discriminated Unions

I defined 13 event types in `schema.py` as a Pydantic discriminated union (`EventPayload`). Each `AgentEvent` carries a `type` field and a corresponding `payload` class, validated at construction via a model validator. This means:

- The wire format is self-describing — any consumer can deserialize without guessing.
- A mismatched type/payload combination blows up immediately at creation time, not silently downstream.
- I can add new event types without breaking existing consumers (forward compatibility).

### 3. Multi-Agent Orchestration: Fan-Out / Fan-In Pattern

My orchestrator follows a clear pipeline:

1. **Lead analyst** decomposes the research question (may ask the user for clarification first).
2. **Parallel web researchers** — fanned out via `asyncio.gather` — each work on one subtopic independently.
3. **Data analyst** (sequential) — reads researcher artifacts and synthesizes metrics.
4. **Report writer** (sequential) — produces the final brief from all prior work.

I pre-create all researcher nodes (status: `queued`) before any of them starts running. This was a deliberate decision so the UI can render the full planned tree structure immediately, giving the user a sense of scope before work begins.

### 4. Human-in-the-Loop via Coroutine Suspension

Rather than building a complex state machine for user interaction, I used `asyncio.Future` to block a single coroutine until the user responds. When the lead analyst needs clarification:

1. It persists the question to `pending_questions` table.
2. Emits an `ask_user` event (UI renders a form).
3. `await bus.await_answer(question_id)` suspends the orchestrator coroutine.
4. When the user POSTs `/answer`, the future resolves and the orchestrator continues.

This keeps my orchestration code linear and readable — no callbacks, no state machine transitions, just `await`. The coroutine suspends; the stream doesn't.

### 5. LLM Adapter Pattern (DirectResearcherLLM)

I designed the sub-agent runner to be LLM-agnostic. It expects any object with a `.step(history) -> (kind, payload)` interface. In production, `DirectResearcherLLM` wraps OpenAI-compatible tool-calling (including DeepSeek's `reasoning_content` field). In tests, a `FakeLLM` returns scripted tuples.

This means I can swap models, switch between streaming/non-streaming, or even run against a local LLM — the orchestration logic doesn't change. The `_ScopedLLM` adapter adds subtopic-scoping so a single LLM instance can serve multiple sub-agents without confusion.

### 6. SQLite + WAL for Single-Process Simplicity

I picked SQLite (WAL mode) over Postgres/Redis because:

- Deep Analyst is a single-node research tool, not a distributed system.
- WAL gives me concurrent reads while writes serialize naturally through `asyncio.Lock`.
- Zero operational overhead — the database is just a file that travels with the code.
- For production scale-out, replacing `DB` with a Postgres adapter is straightforward since the interface is just `execute/fetchone/fetchall/next_seq`.

### 7. The Decoder as a Shared Contract

`decoder.py` is the most important module in the system. It's a pure function (`apply_event`) that takes a `UIState` and an `AgentEvent` and mutates the state in place. Both the backend tests and the Streamlit frontend use this exact same function. This means:

- The backend can assert its own event sequences produce the correct UI tree.
- The frontend doesn't have its own interpretation logic that could diverge.
- Golden-file tests (`render_markdown.py`) can snapshot the tree without running Streamlit.

### 8. Trace Tree Rendering with Parallel Column Layout

In the Streamlit UI, I render the agent tree as nested expanders. When multiple sibling nodes are simultaneously `running` (the parallel researcher phase), they render side-by-side using `st.columns`. This isn't just cosmetic — it communicates to the user that these agents are working concurrently, matching the actual execution model.

### 9. Retry as a First-Class Operation

If a web researcher fails (network error, LLM refusal, etc.), the user can hit "Retry" in the trace tree. This creates a new node with the same subtopic under the same parent, so the tree shows the attempt history. I chose to create a *new* node rather than mutating the failed one because immutability is a core principle — you never rewrite history.

---

## Implementation Approach

### Backend Layer

| Module | Responsibility |
|--------|----------------|
| `main.py` | FastAPI app, lifespan, REST endpoints |
| `orchestrator.py` | The pipeline: decompose → fan-out → fan-in → report |
| `bus.py` | Atomic event emission, pub/sub, ask_user gates |
| `db.py` | aiosqlite wrapper with schema DDL and monotonic seq |
| `schema.py` | 13 event types, Pydantic models, discriminated union |
| `decoder.py` | Pure event→state reducer (shared with frontend) |
| `llm.py` | OpenAI-compatible client with retry, JSON extraction |
| `agents/direct_llm.py` | Tool-calling loop adapter (handles multi-tool batches) |
| `agents/lead.py` | Lead analyst system prompt + decompose schema |
| `agents/web_researcher.py` | Web researcher system prompt |
| `agents/data_analyst.py` | Data analyst system prompt |
| `agents/report_writer.py` | Report writer system prompt |
| `agents/sub_agent.py` | Universal sub-agent runner (tool dispatch loop) |
| `tools/tavily_search.py` | Tavily web search wrapper |
| `tools/write_artifact.py` | Artifact persistence + event emission |
| `tools/ask_user.py` | Human-in-the-loop blocking tool |

### Frontend Layer

| Module | Responsibility |
|--------|----------------|
| `app.py` | Page layout, polling fragment, tab routing |
| `api_client.py` | Typed httpx calls to the backend |
| `state.py` | `st.session_state` accessors |
| `components/chat_column.py` | Input box, run stack, activity ticker |
| `components/trace_tree.py` | Recursive tree renderer with parallel columns |
| `components/artifacts_tab.py` | Artifact browser + preview + download |
| `components/ask_user_form.py` | Pending question form (radio or text) |

### Testing Strategy

I wrote tests at three levels:

1. **Schema correctness** — roundtrip serialization, discriminator validation, all 13 event types exist.
2. **Bus mechanics** — emit persists + publishes, `await_answer` blocks until resolved.
3. **Orchestrator integration** — a full canonical run (decompose → 3 researchers → data → report → completed), plus the ask_user pause/resume flow.

All async tests use `pytest-asyncio` in auto mode with in-memory SQLite (`tmp_path`). The `FakeLLM` / `FakeTavily` pattern means tests run instantly with no network calls — the orchestrator doesn't know or care whether its LLM is real or scripted.

---

## Key Trade-offs I Made

| Decision | What I gained | What I gave up |
|----------|---------------|----------------|
| Event sourcing over CRUD | Full audit trail, time-travel replay | More events to store, eventual consistency on the UI side |
| SQLite over Postgres | Zero-ops, single file, fast dev cycle | Can't scale horizontally without swapping the DB layer |
| Polling over WebSocket | Simpler Streamlit integration, fragment-based reruns | ~500ms latency instead of sub-100ms push |
| Pre-creating all nodes before execution | User sees full plan immediately | Brief moment where nodes show "queued" before work starts |
| New node on retry (not mutation) | Immutable history, attempt tracking | Tree grows on failures instead of staying compact |
| Pure decoder shared between BE/FE | Zero divergence guarantee | Can't have frontend-only optimistic updates |
