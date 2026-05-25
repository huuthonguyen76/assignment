"""ask_user tool: blocks one coroutine until POST /answer arrives.

Per spec tenet #5: block coroutines, never streams.
"""
from __future__ import annotations
import uuid
from backend.bus import EventBus
from backend.schema import (
    EventType, AskUserPayload, AskUserAnsweredPayload, AskedBy,
)


class AskUserTool:
    name = "ask_user"
    description = (
        "Ask the human user a clarifying question. Use sparingly — only when "
        "you genuinely cannot proceed without input."
    )

    def __init__(self, bus: EventBus, run_id: str, node_id: str,
                 parent_node_id: str | None, asked_by: AskedBy):
        self.bus = bus
        self.run_id = run_id
        self.node_id = node_id
        self.parent_node_id = parent_node_id
        self.asked_by = asked_by

    async def ask(self, question: str,
                  options: list[str] | None = None) -> str:
        q_id = str(uuid.uuid4())
        await self.bus.persist_pending(
            run_id=self.run_id, node_id=self.node_id,
            question_id=q_id, question=question, options=options,
        )
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.ASK_USER,
            payload=AskUserPayload(
                question_id=q_id, question=question,
                options=options, asked_by=self.asked_by,
            ),
        )
        answer = await self.bus.await_answer(q_id)
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.ASK_USER_ANSWERED,
            payload=AskUserAnsweredPayload(question_id=q_id, answer=answer),
        )
        return answer
