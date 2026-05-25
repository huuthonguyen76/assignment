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
        ("root", "r1", None, "root", "topic", "running"))
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
