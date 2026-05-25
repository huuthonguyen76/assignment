"""Tavily search wrapped as a callable; OpenHands Tool binding added in Task 12."""
from __future__ import annotations
import os
from dataclasses import dataclass
from tavily import TavilyClient


@dataclass
class SearchResult:
    url: str
    title: str
    content: str
    score: float


class TavilySearchTool:
    name = "tavily_search"
    description = "Search the web for current information. Returns top results."

    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY not set")
        self._client = TavilyClient(api_key=key)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        raw = self._client.search(query=query, max_results=max_results,
                                  search_depth="basic")
        return [
            SearchResult(
                url=r["url"], title=r["title"],
                content=r.get("content", ""),
                score=r.get("score", 0.0),
            )
            for r in raw.get("results", [])
        ]
