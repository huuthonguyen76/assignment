"""RunOrchestrator: lead decompose → parallel researchers →
sequential data-analyst → sequential report-writer."""
from __future__ import annotations
import asyncio
import uuid
from datetime import datetime
from backend.db import DB
from backend.bus import EventBus, TaggingSubscriber
from backend.schema import (
    EventType, RunStartedPayload, NodeCreatedPayload,
    NodeStatusChangedPayload, AskUserPayload, AskUserAnsweredPayload,
    SubagentCompletedPayload, RunCompletedPayload, ErrorPayload,
)
from backend.tools.write_artifact import WriteArtifactTool
from backend.agents.sub_agent import run_research_subagent


class RunOrchestrator:
    def __init__(self, db: DB, bus: EventBus, llm, tavily):
        self.db = db
        self.bus = bus
        self.llm = llm
        self.tavily = tavily
        self._tasks: dict[str, asyncio.Task] = {}

    async def start_run(self, *, session_id: str, topic: str) -> str:
        # Ensure session exists
        row = await self.db.fetchone(
            "SELECT id FROM sessions WHERE id=?", (session_id,))
        if row is None:
            await self.db.execute(
                "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                (session_id, datetime.utcnow()))
        run_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO runs (id, session_id, topic, started_at, status, "
            "next_seq) VALUES (?, ?, ?, ?, ?, 0)",
            (run_id, session_id, topic, datetime.utcnow(), "running"))
        self._tasks[run_id] = asyncio.create_task(self._run(run_id, topic))
        return run_id

    async def wait(self, run_id: str):
        if run_id in self._tasks:
            await self._tasks[run_id]

    async def _create_node(self, run_id, node_id, parent_id, role, title,
                           status):
        await self.db.execute(
            "INSERT INTO nodes (id, run_id, parent_id, role, title, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (node_id, run_id, parent_id, role, title, status))
        await self.bus.emit(
            run_id=run_id, node_id=node_id, parent_node_id=parent_id,
            type=EventType.NODE_CREATED,
            payload=NodeCreatedPayload(role=role, title=title,
                                       status=status),
        )

    async def _set_status(self, run_id, node_id, parent_id, status,
                          reason=None):
        await self.db.execute(
            "UPDATE nodes SET status=? WHERE id=?", (status, node_id))
        await self.bus.emit(
            run_id=run_id, node_id=node_id, parent_node_id=parent_id,
            type=EventType.NODE_STATUS_CHANGED,
            payload=NodeStatusChangedPayload(status=status, reason=reason),
        )

    async def _run(self, run_id: str, topic: str):
        root = "root"
        try:
            # Root node + run_started
            await self.db.execute(
                "INSERT INTO nodes (id, run_id, parent_id, role, title, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (root, run_id, None, "root", topic, "running"))
            await self.bus.emit(
                run_id=run_id, node_id=root, parent_node_id=None,
                type=EventType.RUN_STARTED,
                payload=RunStartedPayload(topic=topic))

            # Lead node
            lead_id = "lead"
            await self._create_node(run_id, lead_id, root, "lead-analyst",
                                    None, "running")

            # Lead decompose (may ask_user, possibly multiple times)
            prior_answer = None
            while True:
                decision = await self.llm.decompose(topic, prior_answer)
                if decision["action"] == "ask_user":
                    q_id = str(uuid.uuid4())
                    await self.bus.persist_pending(
                        run_id=run_id, node_id=lead_id, question_id=q_id,
                        question=decision["question"],
                        options=decision.get("options"))
                    await self.bus.emit(
                        run_id=run_id, node_id=lead_id, parent_node_id=root,
                        type=EventType.ASK_USER,
                        payload=AskUserPayload(
                            question_id=q_id, question=decision["question"],
                            options=decision.get("options"), asked_by="lead"))
                    await self._set_status(run_id, lead_id, root,
                                           "awaiting_user")
                    answer = await self.bus.await_answer(q_id)
                    await self.bus.emit(
                        run_id=run_id, node_id=lead_id, parent_node_id=root,
                        type=EventType.ASK_USER_ANSWERED,
                        payload=AskUserAnsweredPayload(
                            question_id=q_id, answer=answer))
                    await self._set_status(run_id, lead_id, root, "running")
                    prior_answer = answer
                    continue
                if decision["action"] == "decompose":
                    subtopics = decision["subtopics"]
                    break
                raise ValueError(
                    f"unknown lead action: {decision['action']}")

            # Pre-create researcher nodes (all queued) BEFORE any starts
            researcher_nodes = []
            for st in subtopics:
                nid = f"r_{uuid.uuid4().hex[:8]}"
                await self._create_node(run_id, nid, lead_id,
                                        "web-researcher", st, "queued")
                researcher_nodes.append((nid, st))

            # Parallel fan-out
            results = await asyncio.gather(
                *[self._run_researcher(run_id, nid, st, lead_id)
                  for nid, st in researcher_nodes],
                return_exceptions=True,
            )
            successful_research_ids = []
            for (nid, st), res in zip(researcher_nodes, results):
                if isinstance(res, Exception):
                    await self.bus.emit(
                        run_id=run_id, node_id=nid, parent_node_id=lead_id,
                        type=EventType.ERROR,
                        payload=ErrorPayload(
                            where="conversation", message=str(res),
                            recoverable=False, node_id_ref=nid))
                    await self._set_status(run_id, nid, lead_id, "failed")
                else:
                    successful_research_ids.append(nid)

            # Sequential data-analyst
            data_id = "data"
            await self._create_node(run_id, data_id, lead_id, "data-analyst",
                                    None, "running")
            data_sub = TaggingSubscriber(self.bus, run_id, data_id, lead_id)
            data_summary, _ = await run_research_subagent(
                subtopic="__data__", subscriber=data_sub,
                llm=_ScopedLLM(self.llm, "__data__"),
                tavily=self.tavily, bus=self.bus)
            await self.bus.emit(
                run_id=run_id, node_id=data_id, parent_node_id=lead_id,
                type=EventType.SUBAGENT_COMPLETED,
                payload=SubagentCompletedPayload(summary=data_summary))
            await self._set_status(run_id, data_id, lead_id, "completed")

            # Sequential report-writer
            report_id = "report"
            await self._create_node(run_id, report_id, lead_id,
                                    "report-writer", None, "running")
            report_sub = TaggingSubscriber(self.bus, run_id, report_id, lead_id)
            report_summary, report_artifacts = await run_research_subagent(
                subtopic="__report__", subscriber=report_sub,
                llm=_ScopedLLM(self.llm, "__report__"),
                tavily=self.tavily, bus=self.bus)
            await self.bus.emit(
                run_id=run_id, node_id=report_id, parent_node_id=lead_id,
                type=EventType.SUBAGENT_COMPLETED,
                payload=SubagentCompletedPayload(
                    summary=report_summary, artifact_ids=report_artifacts))
            await self._set_status(run_id, report_id, lead_id, "completed")
            await self._set_status(run_id, lead_id, root, "completed")

            # Run completed
            final = report_artifacts[0] if report_artifacts else ""
            await self.db.execute(
                "UPDATE runs SET status=?, finished_at=? WHERE id=?",
                ("completed", datetime.utcnow(), run_id))
            await self.bus.emit(
                run_id=run_id, node_id=root, parent_node_id=None,
                type=EventType.RUN_COMPLETED,
                payload=RunCompletedPayload(final_artifact_id=final))

        except Exception as e:
            await self.db.execute(
                "UPDATE runs SET status=?, finished_at=? WHERE id=?",
                ("failed", datetime.utcnow(), run_id))
            await self.bus.emit(
                run_id=run_id, node_id=root, parent_node_id=None,
                type=EventType.ERROR,
                payload=ErrorPayload(
                    where="orchestrator", message=str(e),
                    recoverable=False, node_id_ref=root))

    async def _run_researcher(self, run_id, node_id, subtopic, parent_id):
        await self._set_status(run_id, node_id, parent_id, "running")
        sub = TaggingSubscriber(self.bus, run_id, node_id, parent_id)
        summary, art_ids = await run_research_subagent(
            subtopic=subtopic, subscriber=sub,
            llm=_ScopedLLM(self.llm, subtopic),
            tavily=self.tavily, bus=self.bus,
        )
        await self.bus.emit(
            run_id=run_id, node_id=node_id, parent_node_id=parent_id,
            type=EventType.SUBAGENT_COMPLETED,
            payload=SubagentCompletedPayload(summary=summary,
                                             artifact_ids=art_ids))
        await self._set_status(run_id, node_id, parent_id, "completed")


class _ScopedLLM:
    """Adapter that turns a multi-subtopic FakeLLM (used in tests) or real
    LLM into the single-step API expected by run_research_subagent.
    """
    def __init__(self, llm, subtopic):
        self.llm = llm
        self.subtopic = subtopic

    async def step(self, history):
        if hasattr(self.llm, "step"):
            try:
                return await self.llm.step(history, self.subtopic)
            except TypeError:
                return await self.llm.step(history)
        raise AttributeError("LLM must expose .step()")
