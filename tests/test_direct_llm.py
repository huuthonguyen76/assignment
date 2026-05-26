"""DirectResearcherLLM: multi tool_call queueing for DeepSeek compatibility."""
import pytest
from backend.agents.direct_llm import DirectResearcherLLM


class _MultiToolClient:
    """Returns three parallel tool_calls on the first API call."""

    def __init__(self):
        self.calls = 0

    async def messages_call(self, *, messages, temperature=0.2, tools=None):
        self.calls += 1
        if self.calls == 1:
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "reasoning_content": "search in parallel",
                        "tool_calls": [
                            {
                                "id": "call_a",
                                "type": "function",
                                "function": {
                                    "name": "tavily_search",
                                    "arguments": '{"query": "a"}',
                                },
                            },
                            {
                                "id": "call_b",
                                "type": "function",
                                "function": {
                                    "name": "tavily_search",
                                    "arguments": '{"query": "b"}',
                                },
                            },
                            {
                                "id": "call_c",
                                "type": "function",
                                "function": {
                                    "name": "finish",
                                    "arguments": '{"summary": "done"}',
                                },
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }],
            }
        return {
            "choices": [{
                "message": {"role": "assistant", "content": "all tools answered"},
                "finish_reason": "stop",
            }],
        }


@pytest.mark.asyncio
async def test_queues_parallel_tool_calls_before_next_api_call():
    llm = DirectResearcherLLM(system_prompt="research", client=_MultiToolClient())
    history = [{"role": "user", "content": "subtopic: test"}]

    k1, p1 = await llm.step(history)
    assert k1 == "tool" and p1["tool_call_id"] == "call_a"
    assert llm._pending_tools == [
        {"name": "tavily_search", "args": {"query": "b"}, "tool_call_id": "call_b"},
        {"name": "finish", "args": {"summary": "done"}, "tool_call_id": "call_c"},
    ]
    assert len(llm._messages) == 3  # system, user, assistant (3 tool_calls)

    history.append({"role": "tool", "tool_call_id": "call_a", "content": "r1"})
    k2, p2 = await llm.step(history)
    assert k2 == "tool" and p2["tool_call_id"] == "call_b"
    assert llm._client.calls == 1

    history.append({"role": "tool", "tool_call_id": "call_b", "content": "r2"})
    k3, p3 = await llm.step(history)
    assert k3 == "finish" and p3["summary"] == "done"
    assert llm._client.calls == 1

    history.append({"role": "tool", "tool_call_id": "call_c", "content": "r3"})
    k4, _ = await llm.step(history)
    assert k4 == "finish"
    assert llm._client.calls == 2
    assert [m.get("tool_call_id") for m in llm._messages if m["role"] == "tool"] == [
        "call_a", "call_b", "call_c",
    ]
