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
