import pytest
from backend.tools.tavily_search import TavilySearchTool, SearchResult


@pytest.fixture
def fake_tavily(monkeypatch):
    calls = []
    class FakeClient:
        def search(self, query, max_results=5, **kwargs):
            calls.append((query, max_results))
            return {
                "results": [
                    {"url": "https://a.com", "title": "A",
                     "content": "hello", "score": 0.9},
                    {"url": "https://b.com", "title": "B",
                     "content": "world", "score": 0.8},
                ]
            }
    monkeypatch.setattr(
        "backend.tools.tavily_search.TavilyClient",
        lambda api_key: FakeClient(),
    )
    return calls


async def test_tool_returns_normalized_results(fake_tavily, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "k")
    tool = TavilySearchTool()
    res = await tool.search(query="anthropic agents", max_results=2)
    assert len(res) == 2
    assert res[0].url == "https://a.com"
    assert fake_tavily[0] == ("anthropic agents", 2)


async def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        TavilySearchTool()
