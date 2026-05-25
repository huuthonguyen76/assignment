import json
import pytest
import respx
import httpx
from backend.llm import OpenCodeZenClient, LLMError


@pytest.fixture
def client():
    return OpenCodeZenClient(
        api_key="test", base_url="https://opencode.test/v1",
        model="grok-code-fast-1", max_retries=2,
    )


@respx.mock
async def test_json_call_returns_parsed_dict(client):
    respx.post("https://opencode.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content":
                '{"action":"decompose","subtopics":["a","b","c"]}'}}]},
        )
    )
    out = await client.json_call(
        system="be helpful", user="decompose: X",
        schema_hint={"action": "decompose|ask_user"},
    )
    assert out == {"action": "decompose", "subtopics": ["a", "b", "c"]}


@respx.mock
async def test_malformed_json_triggers_one_retry_then_raises(client):
    respx.post("https://opencode.test/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": "not json {"}}]},
        )
    )
    with pytest.raises(LLMError):
        await client.json_call(system="s", user="u", schema_hint={})


@respx.mock
async def test_429_retries_then_succeeds(client):
    calls = {"n": 0}
    def respond(request):
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, text="rate limit")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})
    respx.post("https://opencode.test/v1/chat/completions").mock(side_effect=respond)
    out = await client.json_call(system="s", user="u", schema_hint={})
    assert out == {"ok": True}
    assert calls["n"] == 2
