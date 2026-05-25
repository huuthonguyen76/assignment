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
