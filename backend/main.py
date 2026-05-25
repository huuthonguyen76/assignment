"""FastAPI app for Deep Analyst."""
from __future__ import annotations
import asyncio
import json
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel
from backend.db import DB
from backend.bus import EventBus
from backend.llm import OpenCodeZenClient
from backend.orchestrator import RunOrchestrator
from backend.agents.lead import LEAD_SYSTEM_PROMPT, DECOMPOSE_SCHEMA_HINT


@dataclass
class _AppState:
    db: DB | None = None
    bus: EventBus | None = None
    orchestrator: RunOrchestrator | None = None


state = _AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    try:
        yield
    finally:
        await shutdown()


async def startup():
    state.db = DB()
    await state.db.connect()
    await state.db.init_schema()
    state.bus = EventBus(state.db)
    try:
        llm = _RealLeadLLM(OpenCodeZenClient())
        from backend.tools.tavily_search import TavilySearchTool
        tavily = TavilySearchTool()
        state.orchestrator = RunOrchestrator(
            db=state.db, bus=state.bus, llm=llm, tavily=tavily,
        )
    except RuntimeError:
        # Missing env vars in dev — leave orchestrator None; tests inject their own
        state.orchestrator = None


async def shutdown():
    if state.db:
        await state.db.close()


app = FastAPI(lifespan=lifespan)


class StartRunReq(BaseModel):
    session_id: str
    topic: str


class AnswerReq(BaseModel):
    question_id: str
    answer: str


@app.post("/runs")
async def post_run(req: StartRunReq):
    if state.orchestrator is None:
        raise HTTPException(503, "orchestrator not configured (check env vars)")
    run_id = await state.orchestrator.start_run(
        session_id=req.session_id, topic=req.topic)
    return {"run_id": run_id}


@app.get("/runs/{run_id}/events")
async def get_events(run_id: str, from_: int = Query(0, alias="from"),
                     limit: int = 1000):
    events = await state.db.fetch_events_from(run_id, from_seq=from_, limit=limit)
    return [json.loads(e.model_dump_json()) for e in events]


@app.get("/runs/{run_id}/events/stream")
async def sse_events(run_id: str, request: Request,
                     last_event_id: int = Query(0, alias="from")):
    q = state.bus.subscribe(run_id)

    async def gen():
        # First: backfill from last_event_id
        backlog = await state.db.fetch_events_from(run_id, from_seq=last_event_id)
        for e in backlog:
            yield f"id: {e.seq}\ndata: {e.model_dump_json()}\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    e = await asyncio.wait_for(q.get(), timeout=15.0)
                    if e.seq < last_event_id:
                        continue
                    yield f"id: {e.seq}\ndata: {e.model_dump_json()}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            state.bus.unsubscribe(run_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/runs/{run_id}/answer")
async def post_answer(run_id: str, req: AnswerReq):
    await state.bus.set_answer(req.question_id, req.answer)
    return {"ok": True}


@app.post("/runs/{run_id}/retry")
async def post_retry(run_id: str, node_id: str):
    row = await state.db.fetchone(
        "SELECT role, title, parent_id FROM nodes WHERE id=?", (node_id,))
    if row is None:
        raise HTTPException(404, "node not found")
    role, title, parent_id = row
    if role != "web-researcher":
        raise HTTPException(400, "only web-researcher retries supported")
    if state.orchestrator is None:
        raise HTTPException(503, "no orchestrator")
    import uuid as _u
    new_id = f"r_{_u.uuid4().hex[:8]}"
    await state.orchestrator._create_node(
        run_id, new_id, parent_id, "web-researcher", title, "queued")
    asyncio.create_task(
        state.orchestrator._run_researcher(run_id, new_id, title, parent_id))
    return {"new_node_id": new_id}


@app.get("/runs/{run_id}/artifacts")
async def list_artifacts(run_id: str):
    rows = await state.db.fetchall(
        "SELECT id, node_id, name, kind, bytes FROM artifacts WHERE run_id=?",
        (run_id,))
    return [{"id": r[0], "node_id": r[1], "name": r[2],
             "kind": r[3], "bytes": r[4]} for r in rows]


@app.get("/runs/{run_id}/artifacts/{artifact_id}")
async def get_artifact(run_id: str, artifact_id: str):
    row = await state.db.fetchone(
        "SELECT path_on_disk, name FROM artifacts WHERE id=? AND run_id=?",
        (artifact_id, run_id))
    if row is None:
        raise HTTPException(404, "artifact not found")
    return FileResponse(row[0], filename=row[1])


@app.get("/sessions")
async def list_sessions():
    rows = await state.db.fetchall(
        "SELECT id, title, created_at FROM sessions ORDER BY created_at DESC")
    return [{"id": r[0], "title": r[1], "created_at": str(r[2])} for r in rows]


@app.get("/sessions/{session_id}/runs")
async def list_session_runs(session_id: str):
    rows = await state.db.fetchall(
        "SELECT id, topic, status, started_at, finished_at FROM runs "
        "WHERE session_id=? ORDER BY started_at",
        (session_id,))
    return [
        {"id": r[0], "topic": r[1], "status": r[2],
         "started_at": str(r[3]),
         "finished_at": str(r[4]) if r[4] else None}
        for r in rows
    ]


class _RealLeadLLM:
    """Lead decompose uses OpenCode Zen json_call directly; per-subagent step
    loops are driven by OpenHands SDK Conversations."""
    def __init__(self, client: OpenCodeZenClient):
        self.client = client
        self._per_sub: dict[str, object] = {}

    async def decompose(self, topic: str, prior_answer: str | None = None):
        user = f"Research request: {topic}"
        if prior_answer:
            user += f"\n\nUser's clarification: {prior_answer}"
        return await self.client.json_call(
            system=LEAD_SYSTEM_PROMPT, user=user,
            schema_hint=DECOMPOSE_SCHEMA_HINT,
        )

    def _ohll_for(self, subtopic: str):
        from backend.agents.openhands_adapter import OpenHandsConversationLLM
        from backend.agents.web_researcher import WEB_RESEARCHER_PROMPT
        from backend.agents.data_analyst import DATA_ANALYST_PROMPT
        from backend.agents.report_writer import REPORT_WRITER_PROMPT
        if subtopic in self._per_sub:
            return self._per_sub[subtopic]
        prompt = WEB_RESEARCHER_PROMPT
        if subtopic == "__data__":
            prompt = DATA_ANALYST_PROMPT
        elif subtopic == "__report__":
            prompt = REPORT_WRITER_PROMPT
        ohll = OpenHandsConversationLLM(
            system_prompt=prompt,
            model=self.client.model, api_key=self.client.api_key,
            base_url=self.client.base_url,
            tools=[
                {"name": "tavily_search",
                 "parameters": {"query": "string",
                                "max_results": "integer"}},
                {"name": "write_artifact",
                 "parameters": {"name": "string", "content": "string",
                                "kind": "string"}},
                {"name": "ask_user",
                 "parameters": {"question": "string",
                                "options": "array"}},
            ],
        )
        self._per_sub[subtopic] = ohll
        return ohll

    async def step(self, history, subtopic=None):
        ohll = self._ohll_for(subtopic or "default")
        return await ohll.step(history)
