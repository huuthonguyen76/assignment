"""Direct tool-calling LLM adapter — drives the researcher loop without
openhands-sdk by using OpenCodeZenClient's native tool-call support."""
from __future__ import annotations
import json
import uuid
from backend.llm import OpenCodeZenClient

_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "tavily_search",
            "description": "Search the web for current information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_artifact",
            "description": "Save a markdown note as an artifact.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "content": {"type": "string"},
                    "kind": {"type": "string", "default": "markdown"},
                },
                "required": ["name", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_artifact",
            "description": "Read the content of a previously written artifact file by its name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The artifact filename (e.g. redis-overview.md)",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": "Signal research is complete with a one-sentence summary.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                },
                "required": ["summary"],
            },
        },
    },
]


class DirectResearcherLLM:
    """OpenAI-tool-calling loop adapter compatible with run_research_subagent.

    Maintains its own message history including DeepSeek's reasoning_content,
    which must be echoed back in multi-turn requests.
    """

    def __init__(self, *, system_prompt: str, client: OpenCodeZenClient):
        self._system = system_prompt
        self._client = client
        self._messages: list[dict] = [{"role": "system", "content": system_prompt}]
        self._step_count = 0
        # DeepSeek requires a tool result for every tool_call_id on the
        # preceding assistant message. Models may emit several tool_calls at
        # once; we queue extras and return them before the next API call.
        self._pending_tools: list[dict] = []

    def _sync(self, history: list[dict]) -> None:
        if not history:
            return
        last = history[-1]
        role = last.get("role")

        if role == "user":
            content = last.get("content", "")
            if (not self._messages
                    or self._messages[-1].get("role") != "user"
                    or self._messages[-1].get("content") != content):
                self._messages.append({"role": "user", "content": content})

        elif role == "tool":
            # Only add if the last message in _messages isn't already this tool result
            msg = {
                "role": "tool",
                "tool_call_id": last["tool_call_id"],
                "content": last.get("content", ""),
            }
            if not self._messages or self._messages[-1] != msg:
                self._messages.append(msg)

    def _build_assistant_msg(self, message: dict, tool_calls: list) -> dict:
        """Build an assistant message, preserving reasoning_content for DeepSeek."""
        msg: dict = {"role": "assistant"}
        content = message.get("content") or None
        if content is not None:
            msg["content"] = content
        reasoning = message.get("reasoning_content")
        if reasoning:
            msg["reasoning_content"] = reasoning
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return msg

    def _parse_tool_call(self, tc: dict) -> dict:
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"].get("arguments", "{}"))
        except Exception:
            args = {}
        return {
            "name": name,
            "args": args,
            "tool_call_id": tc.get("id") or str(uuid.uuid4()),
        }

    def _return_tool(self, tool: dict) -> tuple[str, object]:
        if tool["name"] == "finish":
            return ("finish", {"summary": tool["args"].get("summary", "")})
        return ("tool", tool)

    async def step(self, history: list[dict]) -> tuple[str, object]:
        self._sync(history)

        if self._pending_tools:
            return self._return_tool(self._pending_tools.pop(0))

        self._step_count += 1

        if self._step_count > 25:
            return ("finish", {"summary": "Research loop limit reached."})

        resp = await self._client.messages_call(
            messages=self._messages,
            tools=_TOOLS,
            temperature=0.2,
        )

        choice = resp["choices"][0]
        message = choice["message"]
        finish_reason = choice.get("finish_reason", "stop")
        tool_calls = message.get("tool_calls") or []

        if tool_calls:
            self._messages.append(self._build_assistant_msg(message, tool_calls))
            parsed = [self._parse_tool_call(tc) for tc in tool_calls]
            self._pending_tools = parsed[1:]
            return self._return_tool(parsed[0])

        text = message.get("content") or ""
        self._messages.append(self._build_assistant_msg(message, []))

        if finish_reason == "stop":
            return ("finish", {"summary": text[:500]})

        return ("think", text)
