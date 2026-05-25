import asyncio
import json
import pytest
from httpx import ASGITransport, AsyncClient
import backend.main as main_mod
from backend.orchestrator import RunOrchestrator
from backend.db import DB
from backend.bus import EventBus
from tests.test_orchestrator import FakeLLM, FakeTavily


@pytest.fixture
async def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ARTIFACTS_DIR", str(tmp_path / "art"))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    # Reset module-level state
    main_mod.state = main_mod._AppState()
    await main_mod.startup()
    lead = [{"action": "decompose", "subtopics": ["A"]}]
    sub = {
        "A": [("finish", {"summary": "ok"})],
        "__data__": [("finish", {"summary": "ok"})],
        "__report__": [
            ("tool", {"name": "write_artifact",
                      "args": {"name": "brief.md", "content": "b",
                               "kind": "markdown"}}),
            ("finish", {"summary": "ok"})],
    }
    main_mod.state.orchestrator = RunOrchestrator(
        db=main_mod.state.db, bus=main_mod.state.bus,
        llm=FakeLLM(lead, sub), tavily=FakeTavily(),
    )
    yield main_mod.app
    await main_mod.shutdown()


async def test_post_run_then_poll_events(app):
    async with AsyncClient(transport=ASGITransport(app=app),
                          base_url="http://t") as ac:
        r = await ac.post("/runs", json={"session_id": "s1", "topic": "x"})
        assert r.status_code == 200
        run_id = r.json()["run_id"]

        # Wait for run to finish
        for _ in range(200):
            r2 = await ac.get(f"/runs/{run_id}/events", params={"from": 0})
            evts = r2.json()
            if any(e["type"] == "run_completed" for e in evts):
                break
            await asyncio.sleep(0.02)
        else:
            pytest.fail("run did not complete")

        types = [e["type"] for e in evts]
        assert types[0] == "run_started"
        assert types[-1] == "run_completed"


async def test_polling_with_cursor_returns_only_new_events(app):
    async with AsyncClient(transport=ASGITransport(app=app),
                          base_url="http://t") as ac:
        r = await ac.post("/runs", json={"session_id": "s1", "topic": "x"})
        run_id = r.json()["run_id"]
        await asyncio.sleep(0.3)
        e1 = (await ac.get(f"/runs/{run_id}/events",
                           params={"from": 0})).json()
        cursor = e1[-1]["seq"] + 1
        e2 = (await ac.get(f"/runs/{run_id}/events",
                           params={"from": cursor})).json()
        # e2 events are strictly newer (or empty if run finished)
        for ev in e2:
            assert ev["seq"] >= cursor


async def test_answer_endpoint_resumes_lead_ask_user(app, monkeypatch):
    # Reconfigure orchestrator with a lead that asks first
    lead = [
        {"action": "ask_user", "question": "tech or commercial?",
         "options": ["tech", "commercial"]},
        {"action": "decompose", "subtopics": ["A"]},
    ]
    sub = {
        "A": [("finish", {"summary": "ok"})],
        "__data__": [("finish", {"summary": "ok"})],
        "__report__": [
            ("tool", {"name": "write_artifact",
                      "args": {"name": "b.md", "content": "b",
                               "kind": "markdown"}}),
            ("finish", {"summary": "ok"})],
    }
    main_mod.state.orchestrator.llm = FakeLLM(lead, sub)
    async with AsyncClient(transport=ASGITransport(app=app),
                          base_url="http://t") as ac:
        r = await ac.post("/runs", json={"session_id": "s1", "topic": "x"})
        run_id = r.json()["run_id"]
        for _ in range(200):
            evts = (await ac.get(f"/runs/{run_id}/events",
                                 params={"from": 0})).json()
            pending = [e for e in evts if e["type"] == "ask_user"]
            if pending:
                break
            await asyncio.sleep(0.02)
        qid = pending[0]["payload"]["question_id"]
        r2 = await ac.post(f"/runs/{run_id}/answer",
                           json={"question_id": qid, "answer": "tech"})
        assert r2.status_code == 200
        for _ in range(200):
            evts = (await ac.get(f"/runs/{run_id}/events",
                                 params={"from": 0})).json()
            if any(e["type"] == "run_completed" for e in evts):
                break
            await asyncio.sleep(0.02)
