"""Write artifact to disk + DB row + artifact_created event."""
from __future__ import annotations
import os
import uuid
from pathlib import Path
from backend.bus import EventBus
from backend.schema import (
    EventType, ArtifactCreatedPayload, ArtifactKind,
)


class WriteArtifactTool:
    name = "write_artifact"
    description = "Write a file the user should see. kind: markdown|sql|yaml|json|image|text"

    def __init__(self, bus: EventBus, run_id: str, node_id: str,
                 parent_node_id: str | None):
        self.bus = bus
        self.run_id = run_id
        self.node_id = node_id
        self.parent_node_id = parent_node_id

    async def write(self, name: str, content: str,
                    kind: ArtifactKind = "text") -> str:
        base = Path(os.environ.get("APP_ARTIFACTS_DIR", "./.data/artifacts"))
        dirpath = base / self.run_id / self.node_id
        dirpath.mkdir(parents=True, exist_ok=True)
        safe = name.replace("..", "_").replace("/", "_")
        path = dirpath / safe
        path.write_text(content)
        size = len(content.encode("utf-8"))
        art_id = str(uuid.uuid4())
        await self.bus.db.execute(
            "INSERT INTO artifacts (id, run_id, node_id, name, kind, bytes, "
            "path_on_disk) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (art_id, self.run_id, self.node_id, safe, kind, size, str(path)),
        )
        await self.bus.emit(
            run_id=self.run_id, node_id=self.node_id,
            parent_node_id=self.parent_node_id,
            type=EventType.ARTIFACT_CREATED,
            payload=ArtifactCreatedPayload(
                artifact_id=art_id, name=safe,
                artifact_kind=kind, bytes=size,
            ),
        )
        return art_id
