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
