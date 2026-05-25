"""OpenHands SDK adapter. Maps an OpenHands Conversation to the
(think|tool|finish) step API our runner expects.

NOTE: This adapter depends on openhands-sdk. If the SDK is not installed or
event class names differ between versions, adjust imports below. The rest of
the system speaks only the normalized AgentEvent schema.
"""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

try:
    from openhands.sdk import Conversation, LLM, Agent
    from openhands.sdk.event import (
        MessageEvent, ActionEvent, ObservationEvent, AgentFinishEvent,
    )
    _OPENHANDS_AVAILABLE = True
except ImportError:
    _OPENHANDS_AVAILABLE = False
    logger.warning(
        "openhands-sdk not installed. OpenHandsConversationLLM will raise "
        "RuntimeError when instantiated. Install openhands-sdk to enable "
        "production agent execution."
    )


class OpenHandsConversationLLM:
    """One Conversation per sub-agent role/subtopic."""

    def __init__(self, *, system_prompt: str, model: str, api_key: str,
                 base_url: str, tools: list):
        if not _OPENHANDS_AVAILABLE:
            raise RuntimeError(
                "openhands-sdk is not installed. Run: pip install openhands-sdk"
            )
        self.llm = LLM(model=model, api_key=api_key, base_url=base_url)
        self.agent = Agent(llm=self.llm, system_prompt=system_prompt,
                           tools=tools)
        self.conv = Conversation(agent=self.agent)
        self._consumed_event_ids: set[str] = set()

    async def step(self, history):
        """Run one assistant turn; convert its emitted events to a tuple."""
        last = history[-1] if history else None
        if last and last["role"] == "user":
            await self.conv.send_message(last["content"])
        elif last and last["role"] == "tool":
            await self.conv.add_tool_result(
                tool_call_id=last["tool_call_id"], content=last["content"])

        async for ev in self.conv.step():
            if ev.id in self._consumed_event_ids:
                continue
            self._consumed_event_ids.add(ev.id)
            if isinstance(ev, MessageEvent):
                return ("think", ev.content)
            if isinstance(ev, ActionEvent):
                return ("tool",
                        {"name": ev.tool_name, "args": ev.tool_input,
                         "tool_call_id": ev.tool_call_id})
            if isinstance(ev, AgentFinishEvent):
                return ("finish", {"summary": ev.final_message or ""})
        return ("finish", {"summary": "(no output)"})
