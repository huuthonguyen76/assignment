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
