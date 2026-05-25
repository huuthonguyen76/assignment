"""EventBus: atomic seq, SQLite persist, in-memory pub/sub, ask_user gates.

TaggingSubscriber is added below.
"""
from __future__ import annotations
import asyncio
import json
from collections import defaultdict
from datetime import datetime
from backend.db import DB
from backend.schema import (
    AgentEvent, EventType, EventPayload,
)


class EventBus:
    def __init__(self, db: DB):
        self.db = db
        self._subscribers: dict[str, list[asyncio.Queue[AgentEvent]]] = defaultdict(list)
        self._answers: dict[str, asyncio.Future[str]] = {}
        self._lock = asyncio.Lock()

    def subscribe(self, run_id: str) -> asyncio.Queue[AgentEvent]:
        q: asyncio.Queue[AgentEvent] = asyncio.Queue()
        self._subscribers[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue):
        if q in self._subscribers[run_id]:
            self._subscribers[run_id].remove(q)

    async def emit(
        self, *, run_id: str, node_id: str, parent_node_id: str | None,
        type: EventType, payload: EventPayload,
    ) -> AgentEvent:
        async with self._lock:
            seq = await self.db.next_seq(run_id)
            ev = AgentEvent(
                seq=seq, run_id=run_id, node_id=node_id,
                parent_node_id=parent_node_id, ts=datetime.utcnow(),
                type=type, payload=payload,
            )
            await self.db.insert_event(ev)
        for q in list(self._subscribers[run_id]):
            q.put_nowait(ev)
        return ev

    async def persist_pending(
        self, *, run_id: str, node_id: str, question_id: str,
        question: str, options: list[str] | None = None,
    ):
        await self.db.execute(
            "INSERT INTO pending_questions (id, run_id, node_id, question, "
            "options_json, asked_at) VALUES (?, ?, ?, ?, ?, ?)",
            (question_id, run_id, node_id, question,
             json.dumps(options) if options else None, datetime.utcnow()),
        )
        self._answers[question_id] = asyncio.get_running_loop().create_future()

    async def await_answer(self, question_id: str) -> str:
        fut = self._answers.get(question_id)
        if fut is None:
            fut = asyncio.get_running_loop().create_future()
            self._answers[question_id] = fut
        return await fut

    async def set_answer(self, question_id: str, answer: str):
        await self.db.execute(
            "UPDATE pending_questions SET answer=?, answered_at=? WHERE id=?",
            (answer, datetime.utcnow(), question_id),
        )
        fut = self._answers.get(question_id)
        if fut and not fut.done():
            fut.set_result(answer)


from backend.schema import (
    AgentMessagePayload, ThinkingPayload,
    ToolStartedPayload, ToolFinishedPayload,
    ErrorPayload, ErrorWhere,
)


class TaggingSubscriber:
    """Adapter: holds (run_id, node_id, parent_node_id) and exposes typed
    emit_* methods. The sub-agent runner calls these as it observes OpenHands
    events. Node identity is stamped from the closure — NEVER from event content.
    """
    def __init__(self, bus: EventBus, run_id: str, node_id: str,
                 parent_node_id: str | None):
        self.bus = bus
        self.run_id = run_id
        self.node_id = node_id
        self.parent_node_id = parent_node_id

    async def emit_thinking(self, text: str, delta: bool = False):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.THINKING,
            payload=ThinkingPayload(text=text, delta=delta),
        )

    async def emit_agent_message(self, text: str):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.AGENT_MESSAGE,
            payload=AgentMessagePayload(text=text),
        )

    async def emit_tool_started(self, tool_name: str, tool_call_id: str,
                                input: dict):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.TOOL_STARTED,
            payload=ToolStartedPayload(
                tool_name=tool_name, tool_call_id=tool_call_id, input=input),
        )

    async def emit_tool_finished(self, tool_call_id: str,
                                 output_summary: str, ok: bool,
                                 output_ref: str | None = None):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.TOOL_FINISHED,
            payload=ToolFinishedPayload(
                tool_call_id=tool_call_id, output_summary=output_summary,
                ok=ok, output_ref=output_ref),
        )

    async def emit_error(self, where: ErrorWhere, message: str,
                         recoverable: bool):
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.ERROR,
            payload=ErrorPayload(
                where=where, message=message, recoverable=recoverable,
                node_id_ref=self.node_id),
        )
