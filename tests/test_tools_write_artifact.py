import os
from pathlib import Path
import pytest
from datetime import datetime
from backend.db import DB
from backend.bus import EventBus
from backend.tools.write_artifact import WriteArtifactTool


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
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


async def test_write_creates_file_db_row_and_event(setup, tmp_path):
    db, bus = setup
    tool = WriteArtifactTool(bus=bus, run_id="r1", node_id="n1",
                             parent_node_id=None)
    art_id = await tool.write(name="notes.md", content="# hi",
                              kind="markdown")
    # file exists
    p = Path(os.environ["APP_ARTIFACTS_DIR"]) / "r1" / "n1" / "notes.md"
    assert p.exists() and p.read_text() == "# hi"
    # db row
    row = await db.fetchone("SELECT name, kind, bytes FROM artifacts WHERE id=?",
                            (art_id,))
    assert row == ("notes.md", "markdown", 4)
    # event was emitted
    events = await db.fetch_events_from("r1")
    assert events[0].type.value == "artifact_created"
    assert events[0].payload.artifact_id == art_id
