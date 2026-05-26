# Deep Analyst — Agent-Transparent Research Chat (1-Pager)

> Amazon-style design doc. Domain A ("Deep Analyst") from `ASSIGNMENT.md`.
> Backend: FastAPI + OpenHands SDK adapter. UI: Streamlit. Persistence: SQLite.
> The contract between them is a single typed envelope, `AgentEvent`
> (`backend/schema.py`), driven by a pure decoder (`backend/decoder.py`) that
> both sides import.

---

## Tenets (in priority order)

1. **The decoder is the asset.** A pure, deterministic `apply_event(state, ev)`
   function is the single source of truth for what the user sees. Backend asserts
   against it; UI renders from it. No business logic lives in the renderer.
2. **One envelope, thirteen types.** Every event the UI ever sees flows through
   the same `AgentEvent` Pydantic class with a discriminated `payload` union.
   Raw SDK shapes never leak past the adapter.
3. **Node identity is stamped by the producer, never inferred by the consumer.**
   The `(run_id, node_id, parent_node_id)` triple is set at emit time by a
   `TaggingSubscriber` bound to a closure. The decoder trusts it absolutely.
4. **Persistence first, broadcast second.** Every event is `INSERT`-ed under
   an atomic `next_seq` *before* it is fan-out to subscribers. Reload = replay.
5. **Pause is a server-side `await`, not a closed connection.** `ask_user`
   blocks the orchestrator task on an `asyncio.Future`; the HTTP stream stays
   open and emits heartbeats.
6. **Streaming UX over RPC.** The chat must never look idle. Render
   intermediate state (queued, running, awaiting_user) the moment the event
   lands.

---

## Problem

Multi-agent orchestrations are opaque. The Claude Agent SDK / OpenHands SDK
emit a heterogeneous stream of events (LLM deltas, tool calls, sub-agent
spawns, hook signals, user-input requests, file writes). Naively rendering
this as a chat log produces an unreadable wall of text with no structure,
loses parent/child relationships when multiple sub-agents run in parallel,
and breaks when an agent pauses for a user question. We need a chat application
that:

- Decodes the raw event stream into a **nested trace tree** that grows as
  events arrive — not after the run finishes.
- Visualises **parallel sub-agents** running concurrently and distinguishes
  them from sequential phases.
- Handles **`ask_user`** as an interactive pause: surface the question, collect
  the answer, resume the same run.
- **Collects artifacts** (markdown notes, summary tables, the final brief)
  and surfaces them coherently, attributed to the agent that produced them.
- Survives **page refresh, disconnect, and parallel-event races** without
  duplicating or dropping state.

---

## Proposed Solution

Two processes. FastAPI (`:8000`) owns the orchestrator, the SDK adapter, the
event bus, and SQLite. Streamlit (`:8501`) is a thin polling client that calls
the same `decoder.apply_event` to rebuild `UIState` on every refresh.

```
User ──▶ Streamlit ─poll /events?from=N─▶ FastAPI ──▶ RunOrchestrator
                                            │            │ asyncio.gather
                                            │            ├─▶ web-researcher  (parallel)
                                            │            ├─▶ web-researcher  (parallel)
                                            │            └─▶ web-researcher  (parallel)
                                            │                  │
                                            ▼                  ▼
                              SQLite ◀─ EventBus  ◀─── TaggingSubscriber
                                          │
                                          └─▶ in-memory pub/sub (SSE)
```

The **on-wire contract** is `AgentEvent(seq, run_id, node_id, parent_node_id,
ts, type, payload)`. `seq` is a per-run monotonic integer assigned inside the
`EventBus` under an `asyncio.Lock` via `db.next_seq()`. The decoder enforces
`ev.seq == state.last_seq + 1` — gap-free — and silently drops `ev.seq <=
state.last_seq` (replay-safe).

### Q1. Single chat message per run, or one per event?

**Decision: one chat row per *run*, with an embedded expandable trace tree.
Streaming sub-events update the tree in place; they do not produce new chat
rows.**

Implementation:
- The chat column (`streamlit_app/components/chat_column.py`) holds two roles:
  `user` (the topic) and `assistant` (the run). The assistant row is created
  when `RUN_STARTED` arrives and is mutated thereafter — `THINKING`,
  `TOOL_STARTED`, etc. write into the `Node.events` list of the right tree
  node, not into a new chat message.
- The final brief (the `report-writer` artifact) is rendered *inside* the same
  assistant row when `RUN_COMPLETED` fires.

**Why not one chat message per agent event?** Three reasons:
1. **Ordering breaks under parallelism.** Three web-researchers emit `THINKING`
   and `TOOL_STARTED` interleaved by `seq`. Rendered as a flat chat log, the
   reader can't tell which thought belongs to which researcher. The tree
   preserves provenance for free via `parent_node_id`.
2. **Streamlit re-render cost.** Each chat message is its own
   `st.chat_message()` block. A 200-event run would mean 200 blocks, none of
   which collapse coherently. The expander-per-node model collapses cleanly:
   completed sub-agents auto-collapse via the `expanded = node.status in
   ("running", "awaiting_user", "failed")` rule (`trace_tree.py:42`).
3. **Multi-run stacking.** Stretch goal #13 requires older runs to collapse.
   That is trivially `st.expander(expanded=False)` around the whole assistant
   row when one chat row = one run. Mapping it onto a per-event flat log would
   require synthesising group boundaries from `RUN_STARTED`/`RUN_COMPLETED`.

**Why not one chat row per phase (lead → researchers → data → report)?**
The phase boundaries are implementation detail of *this* orchestrator. The
decoder must work for any agent topology (per Tenet 2 and pitfall #5
"hardcoding agent names"). Phase rendering would force the UI to know
domain-specific milestones; the tree does not.

### Q2. How do parallel agents appear?

**Decision: side-by-side `st.columns` while siblings are concurrently running;
stacked vertically once any of them complete.**

Implementation:
- Researcher nodes are **pre-created queued** in a loop *before* the
  `asyncio.gather` fan-out (`orchestrator.py:122-134`). This guarantees the
  decoder sees all parallel siblings as children of `lead-analyst` before any
  child emits a `THINKING` event — eliminating the race in pitfall #4 where
  the UI shrinks back to a single column when the first child reports activity.
- The tree renderer (`trace_tree.py:46-55`) inspects siblings: if ≥2 children
  share `status == "running"` and none are merely `queued`, it lays them out
  in `st.columns(len(children))`. Otherwise it stacks. Once one finishes, the
  next render naturally falls back to vertical (the running set is now
  unbalanced), which is the desired "fan-in" affordance.
- Each parallel child carries its own `node_id` (`r_<uuid8>`) so the decoder's
  `Node.find(node_id)` routes every event unambiguously — even though all
  three siblings have `role == "web-researcher"`. This directly addresses the
  assignment's "multiple instances of the same agent type" requirement.
- Parallel-no-race is asserted by `test_decoder.py` (interleaved-seq input
  produces a tree that equals the non-interleaved version).

**Why not a swimlane / Gantt-style timeline?** Honest answer: implementation
cost in Streamlit. Streamlit has no first-class timeline widget; building one
requires a custom component or a Plotly chart, which loses the expandable tool
input/output that reviewers spend most of their time reading. The
columns-while-running pattern gives the *visual signal* of parallelism (you
literally see three panels animating at once) while keeping the expandable
detail view.

**Why not always render columns?** Once researchers finish, their nodes
auto-collapse to a one-line summary. Three collapsed summaries in three thin
columns are harder to scan than three full-width collapsed rows.

**Why pre-create queued nodes instead of creating them lazily on first child
event?** Two reasons. (a) Decoder safety: `NODE_CREATED` arriving *after* its
first `THINKING` would force the decoder to either buffer-and-replay or
tolerate unknown nodes, both of which weaken Tenet 1. (b) UX: the user sees
all three subtopics announced together at fan-out time, not one at a time as
each researcher happens to start LLM-calling.

### Q3. What happens during `ask_user`?

**Decision: orchestrator task `await`s on a per-question `asyncio.Future`; the
HTTP stream stays open; the UI shows an inline form scoped to the asking node.**

Implementation trace:
1. Lead emits `ASK_USER` (`orchestrator.py:98`) carrying `question_id`,
   `question`, optional `options`, and `asked_by="lead"`. The same call
   `INSERT`s a row into `pending_questions` (`bus.persist_pending`) so the
   question survives a backend restart.
2. Lead emits `NODE_STATUS_CHANGED → awaiting_user`. Decoder
   (`decoder.py:86-90`) sets `state.pending_question = payload` *and* marks
   the node `awaiting_user`. The chat renderer keys off
   `state.pending_question` to show the form (`ask_user_form.py`).
3. Orchestrator calls `await self.bus.await_answer(q_id)` — a plain Future
   `await`. **No CPU is burned, no stream is closed, no polling happens.** The
   SSE stream continues to emit `: heartbeat` every 15s (`main.py:113`) so
   intermediaries don't kill the socket.
4. UI POSTs `/runs/{run_id}/answer` with `{question_id, answer}`. FastAPI
   calls `bus.set_answer` which `UPDATE`s `pending_questions` *and* resolves
   the Future.
5. Orchestrator wakes, emits `ASK_USER_ANSWERED`, flips the node back to
   `running`, and loops the `decompose()` call with `prior_answer` so the lead
   can either re-ask or proceed (`orchestrator.py:90-114`).
6. Decoder clears `state.pending_question`; UI removes the form.

**Why a Future + open SSE stream, not "close stream, reopen on answer"?**
Pitfall #3 directly. Closing means the UI has to remember it was mid-run,
re-issue `GET /events?from=N`, and reconcile state. Worse, any *other*
sub-agent that emits after the lead's pause (in this architecture there is
none; in a more aggressive design there could be) would lose its events to
the dropped subscriber. Keeping the stream open with heartbeats is one line
of code (`asyncio.wait_for(q.get(), timeout=15.0)` + `yield ": heartbeat"`)
and turns reconnection into a non-event.

**Why persist `pending_questions` in SQLite?** Refresh-during-pause is the
demo path. The Streamlit poll re-issues `GET /events?from=0` on every page
load; the decoder rebuilds `state.pending_question` purely from the
`ASK_USER` event in the replay stream — but if the backend crashes between
emit and answer, the SQLite row is what lets us rehydrate the future on
restart.

**Why not bake the question into the chat as a plain assistant message and
let the user type a normal chat reply?** It's ambiguous which run the reply
belongs to (assignment requires multi-run sessions, stretch goal #13). The
explicit `question_id` round-trip eliminates that ambiguity and lets us
support typed answers (free-text vs `options` radio) without a NLP layer.

**Why allow nested `ask_user` from sub-agents (`asked_by="subagent"`)?** It's
in the schema for future use; current orchestrator only emits `asked_by="lead"`.
Calling it out as an extension point now means the decoder, persistence, and
UI form all already handle it — no schema migration when we wire it up.

### Q4. How are artifacts surfaced?

**Decision: three concurrent surfaces, all backed by the same `artifacts`
table: (a) per-node badge inside the trace, (b) a dedicated "Artifacts" tab
listing everything for the run, (c) the final brief is inlined into the chat
on `RUN_COMPLETED`.**

Implementation:
- Artifacts are *not* tool outputs returned to the LLM. The `write_artifact`
  tool (`backend/tools/write_artifact.py`) writes the file to `.data/<run_id>/`,
  `INSERT`s into the `artifacts` table, and emits an `ARTIFACT_CREATED` event
  *separately* from the `TOOL_FINISHED` for the tool call. This separation
  matters: tool outputs are agent-internal context; artifacts are
  user-surfaceable.
- The decoder (`decoder.py:93-97`) appends to `state.artifacts` (the flat list
  for the Artifacts tab) *and* to `node.artifact_ids` (the per-node list for
  the in-tree badge). Both lists are derived from the same event — no
  divergent state.
- `SUBAGENT_COMPLETED` carries `artifact_ids: list[str]` so the final summary
  block can show "this researcher produced 2 artifacts" without traversing
  the event log.
- `RUN_COMPLETED.final_artifact_id` is special-cased: it's the report-writer's
  output, which the chat column auto-renders inline (the user wants the brief,
  not a link to download it).
- Download is `GET /runs/{run_id}/artifacts/{artifact_id}` returning
  `FileResponse` from `artifacts.path_on_disk` — same row, no content duplication
  in SQLite.

**Why three surfaces instead of one canonical list?** Different intents:
- **In-tree badge** answers "what did *this* researcher produce?" — used while
  reading the trace.
- **Artifacts tab** answers "what files exist?" — used when reviewing the
  whole run after it ends.
- **Inline final brief** answers "what's the answer to my question?" — the
  default user goal.
  All three read from `state.artifacts` (plus `node.artifact_ids` and
  `state.final_artifact_id`), so consistency is automatic.

**Why a separate `ARTIFACT_CREATED` event rather than scanning
`TOOL_FINISHED.output_ref` for file paths?** Robustness. A researcher can
call `write_artifact` zero, one, or many times per turn; coupling artifact
discovery to a regex over tool output is the kind of "raw payload leaking
past the adapter" that Tenet 2 explicitly forbids. The explicit event also
lets us cleanly distinguish "the tool succeeded and produced a file" from
"the tool succeeded and didn't" without inspecting payloads.

**Why store on disk under `.data/<run_id>/` instead of as a SQLite BLOB?**
(a) The reviewer/operator can `cat` them. (b) Streamlit and the API can
stream them as `FileResponse` without `SELECT … FROM artifacts` of binary
data. (c) Markdown and SQL artifacts are small but image artifacts in the
data-analyst phase can be 100KB+; SQLite handles this poorly without
configuration.

---

## Goals (24h must-haves; map 1:1 to assignment §Must-Have)

- **G1 Decoder correctness.** All 13 event types in `EventType` have explicit
  branches in `apply_event`; `test_decoder.py` covers each. Gap-free seq
  enforced; replay idempotent.
- **G2 Tree fidelity.** `parent_node_id` is the only mechanism that places a
  node in the tree. Same-role siblings (three `web-researcher` instances) are
  distinguished by `node_id`.
- **G3 Parallel rendering.** Concurrently running siblings render as
  `st.columns`. Pre-created queued nodes prevent layout flicker.
- **G4 `ask_user` round-trip.** Form → POST `/answer` → Future resolution →
  `ASK_USER_ANSWERED` → resume. Stream stays open throughout.
- **G5 Artifact surfacing.** Per-node, per-run tab, inline final brief.
- **G6 Refresh survival.** Polling `/events?from=0` replays the entire stream
  through the decoder; UIState reconstitutes deterministically.
- **G7 Typed envelope.** `AgentEvent.payload` is a discriminated Pydantic
  union; the decoder is fully typed.
- **G8 Tests.** Decoder routing per-event-type; tree-shape assertions;
  parallel interleave equivalence; orchestrator canonical run + `ask_user`
  pause/resume.

## Non-goals

- **Authentication, multi-tenant isolation, RBAC.** Single local user.
- **Production-grade transport.** Polling at 500ms is good enough for the
  demo; the SSE endpoint exists for the stretch goal but isn't the default UI
  driver (Streamlit's component model is happier with idempotent polling).
- **Editable / re-orderable trace tree.** Read-only.
- **Multi-tab live sync.** Each browser tab is an independent decoder; we
  don't broadcast UI state between them. SQLite is the convergence point on
  refresh.
- **Cancellation mid-run.** Out of scope; SDK task is cooperative-cancelled
  on backend shutdown only.
- **Long-term storage / cleanup.** `.data/<run_id>/` accumulates; rotation
  is operator-managed.
- **Cross-domain support (Domain B / dbt).** Schema is generic enough to
  extend, but role enum is currently the four research roles.

---

## Open Questions

1. **Streaming transport in production.** Streamlit polling is fine for the
   demo, but the SSE endpoint (`/events/stream`) exists and would be the
   default in a non-Streamlit UI. Should we ship Streamlit's polling and
   document the SSE endpoint as "the API", or invest in a JS-driven
   component that actually consumes SSE? *Leaning: ship polling, document
   SSE.*
2. **Nested `ask_user`.** The schema supports `asked_by="subagent"` but the
   orchestrator only emits `"lead"`. If a web-researcher asks the user
   mid-run, do we pause just that researcher (siblings keep going) or the
   whole fan-out? *Leaning: pause-just-that-researcher; the gather already
   tolerates per-task await.*
3. **Retry semantics.** `POST /runs/{run_id}/retry?node_id=…` creates a new
   sibling node (`r_<new-uuid>`) and re-runs. Should the failed node stay in
   the tree (audit trail) or be replaced (clean UI)? *Current: stays;
   reviewers can see what was tried.*
4. **JSON-mode brittleness.** Lead `decompose()` uses
   `OpenCodeZenClient.json_call` with a regex-extract fallback on parse
   failure. Acceptable failure rate threshold before we swap models? *No
   data yet; flag for measurement.*
5. **Artifact attribution under retry.** If a researcher is retried and the
   first attempt left an artifact on disk before failing, do we keep both?
   *Current: yes, both are in the table with different `node_id`s. Possibly
   confusing.*
6. **OpenHands SDK version pinning.** Adapter (`openhands_adapter.py`) pins
   event class names. A minor version bump can break imports. Is hooking
   into `sdk.events` by `isinstance` durable enough, or do we want a
   feature-detection shim?
