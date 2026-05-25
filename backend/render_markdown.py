"""Text-only tree renderer for golden-file tests. Not used by the Streamlit UI."""
from __future__ import annotations
from backend.decoder import Node


_ICON = {"queued": "◯", "running": "◐", "awaiting_user": "⏸",
         "completed": "✓", "failed": "✗", "skipped": "—"}


def render_tree_to_markdown(root: Node, depth: int = 0) -> str:
    if root is None:
        return "(empty)"
    indent = "  " * depth
    label = f"{indent}{_ICON.get(root.status, '?')} {root.role}"
    if root.title:
        label += f" — {root.title}"
    out = [label]
    for ev in root.events:
        t = ev.type.value
        if t == "thinking":
            out.append(f"{indent}  ▸ thinking: {ev.payload.text}")
        elif t == "tool_started":
            out.append(f"{indent}  ▸ tool: {ev.payload.tool_name}")
        elif t == "tool_finished":
            ok = "ok" if ev.payload.ok else "fail"
            out.append(f"{indent}  ▸ tool→{ok}: "
                       f"{ev.payload.output_summary[:60]}")
    for c in root.children:
        out.append(render_tree_to_markdown(c, depth + 1))
    return "\n".join(out)
