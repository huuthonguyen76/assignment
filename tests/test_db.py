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
