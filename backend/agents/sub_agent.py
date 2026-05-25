"""Sub-agent runner. In production the `llm` argument is an OpenHands
Conversation; in tests it's a FakeLLM. Both expose `.step(history)` returning
(kind, payload). Supported kinds: "think" | "tool" | "finish".

This pattern lets us evolve the orchestration without coupling to a specific
OpenHands SDK release. When wiring the real SDK (production), create a thin
adapter class that wraps a Conversation and yields these tuples.
"""
from __future__ import annotations
import uuid
from typing import Any
from backend.bus import EventBus, TaggingSubscriber
from backend.tools.write_artifact import WriteArtifactTool
from backend.tools.ask_user import AskUserTool


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
            tcid = str(uuid.uuid4())
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
                elif name == "ask_user":
                    answer = await asker.ask(
                        question=args["question"], options=args.get("options"))
                    await subscriber.emit_tool_finished(
                        tcid, output_summary="user answered", ok=True)
                    history.append(
                        {"role": "tool", "tool_call_id": tcid, "content": answer})
                else:
                    await subscriber.emit_tool_finished(
                        tcid, output_summary=f"unknown tool {name}", ok=False)
                    await subscriber.emit_error(
                        where="tool", message=f"unknown tool {name}",
                        recoverable=False)
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
