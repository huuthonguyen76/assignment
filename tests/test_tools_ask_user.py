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
