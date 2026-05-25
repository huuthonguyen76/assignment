"""OpenCode Zen client. OpenAI-compatible chat completions endpoint."""
from __future__ import annotations
import asyncio
import json
import os
import re
from typing import Any
import httpx


class LLMError(Exception):
    pass


class OpenCodeZenClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        max_retries: int = 3,
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.getenv("OPENCODE_ZEN_API_KEY", "")
        self.base_url = (
            base_url or os.getenv("OPENCODE_ZEN_BASE_URL",
                                  "https://opencode.ai/zen/v1")
        ).rstrip("/")
        self.model = model or os.getenv("OPENCODE_ZEN_MODEL",
                                        "grok-code-fast-1")
        self.max_retries = max_retries
        self.timeout = timeout

    async def chat_call(
        self, *, system: str, user: str, temperature: float = 0.2,
        tools: list[dict] | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        headers = {"Authorization": f"Bearer {self.api_key}"}

        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    r = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload, headers=headers,
                    )
                if r.status_code == 429 or r.status_code >= 500:
                    raise LLMError(f"{r.status_code}: {r.text[:200]}")
                r.raise_for_status()
                return r.json()
            except (httpx.TransportError, LLMError) as e:
                last_err = e
                if attempt >= self.max_retries:
                    raise
                await asyncio.sleep(0.5 * (2 ** attempt))
        raise last_err  # unreachable

    async def json_call(
        self, *, system: str, user: str,
        schema_hint: dict | None = None,
    ) -> dict:
        """Calls the model and parses JSON from the response.

        Strategy: append explicit JSON-only instruction; on parse failure,
        one corrective retry with the failed text echoed back.
        """
        sys = system + (
            "\n\nRespond with ONLY a JSON object matching this schema, no prose: "
            + json.dumps(schema_hint or {})
        )
        for attempt in range(2):
            resp = await self.chat_call(system=sys, user=user, temperature=0.1)
            content = resp["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            if parsed is not None:
                return parsed
            user = (
                "Your previous response could not be parsed as JSON. "
                "Output ONLY a JSON object."
            )
        raise LLMError("model failed to produce valid JSON after retry")


_JSON_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    # strip code fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None
