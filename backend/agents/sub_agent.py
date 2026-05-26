"""Sub-agent runner. In production the `llm` argument is an OpenHands
Conversation; in tests it's a FakeLLM. Both expose `.step(history)` returning
(kind, payload). Supported kinds: "think" | "tool" | "finish".

This pattern lets us evolve the orchestration without coupling to a specific
OpenHands SDK release. When wiring the real SDK (production), create a thin
adapter class that wraps a Conversation and yields these tuples.
"""
from __future__ import annotations
import os
import uuid
from pathlib import Path
from typing import Any
from backend.bus import EventBus, TaggingSubscriber
from backend.tools.write_artifact import WriteArtifactTool
from backend.tools.ask_user import AskUserTool


def _read_artifact_content(run_id: str, name: str) -> str:
    """Search all node subdirs under the run's artifact directory for `name`."""
    base = Path(os.getenv("APP_ARTIFACTS_DIR", "./.data/artifacts")) / run_id
    if not base.exists():
        return f"(no artifacts directory for run {run_id})"
    for f in base.rglob(name):
        try:
            return f.read_text(encoding="utf-8")
        except Exception as e:
            return f"(error reading {name}: {e})"
    return f"(artifact '{name}' not found)"


async def run_research_subagent(
    *, subtopic: str, subscriber: TaggingSubscriber, llm,
    tavily, bus: EventBus,
) -> tuple[str, list[str]]:
    """Drive a web-researcher loop until the LLM emits "finish".

    Returns (summary, list_of_artifact_ids).
    """
    history: list[dict] = [{"role": "user", "content": f"subtopic: {subtopic}"}]
    artifact_ids: list[str] = []
    writer = WriteArtifactTool(
        bus=bus, run_id=subscriber.run_id, node_id=subscriber.node_id,
        parent_node_id=subscriber.parent_node_id,
    )
    asker = AskUserTool(
        bus=bus, run_id=subscriber.run_id, node_id=subscriber.node_id,
        parent_node_id=subscriber.parent_node_id, asked_by="subagent",
    )

    while True:
        kind, payload = await llm.step(history)

        if kind == "think":
            await subscriber.emit_thinking(payload)
            history.append({"role": "assistant", "content": payload})

        elif kind == "tool":
            name = payload["name"]
            args = payload.get("args", {})
            # Use the LLM's tool_call_id if provided (required for DeepSeek multi-turn)
            tcid = payload.get("tool_call_id") or str(uuid.uuid4())
            await subscriber.emit_tool_started(name, tcid, args)
            try:
                if name == "tavily_search":
                    results = await tavily.search(
                        args["query"], max_results=args.get("max_results", 5))
                    summary = f"{len(results)} results: " + ", ".join(
                        r.title for r in results[:3])
                    out = {"results": [r.__dict__ for r in results]}
                    await subscriber.emit_tool_finished(
                        tcid, output_summary=summary, ok=True)
                    history.append(
                        {"role": "tool", "tool_call_id": tcid, "content": str(out)})
                elif name == "write_artifact":
                    art_id = await writer.write(
                        name=args["name"], content=args["content"],
                        kind=args.get("kind", "markdown"),
                    )
                    artifact_ids.append(art_id)
                    await subscriber.emit_tool_finished(
                        tcid, output_summary=f"wrote {args['name']}",
                        ok=True, output_ref=art_id)
                    history.append(
                        {"role": "tool", "tool_call_id": tcid,
                         "content": f"saved {art_id}"})
                elif name == "read_artifact":
                    content = _read_artifact_content(
                        subscriber.run_id, args.get("name", ""))
                    preview = content[:120]
                    await subscriber.emit_tool_finished(
                        tcid, output_summary=f"read {args.get('name')}: {preview}",
                        ok=True)
                    history.append(
                        {"role": "tool", "tool_call_id": tcid, "content": content})
                elif name == "ask_user":
                    answer = await asker.ask(
                        question=args["question"], options=args.get("options"))
                    await subscriber.emit_tool_finished(
                        tcid, output_summary="user answered", ok=True)
                    history.append(
                        {"role": "tool", "tool_call_id": tcid, "content": answer})
                else:
                    msg = f"unknown tool '{name}' — available: tavily_search, write_artifact, read_artifact, finish"
                    await subscriber.emit_tool_finished(
                        tcid, output_summary=msg, ok=False)
                    history.append(
                        {"role": "tool", "tool_call_id": tcid, "content": msg})
            except Exception as e:
                await subscriber.emit_tool_finished(
                    tcid, output_summary=str(e), ok=False)
                await subscriber.emit_error(
                    where="tool", message=str(e), recoverable=True)
                history.append(
                    {"role": "tool", "tool_call_id": tcid,
                     "content": f"ERROR: {e}"})

        elif kind == "finish":
            return payload["summary"], artifact_ids

        else:
            raise ValueError(f"unknown LLM step kind: {kind}")
