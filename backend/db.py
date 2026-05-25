"""aiosqlite wrapper. One DB instance per process; serialized via asyncio.Lock."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import aiosqlite
from backend.schema import AgentEvent, EventType, _TYPE_TO_PAYLOAD

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TIMESTAMP NOT NULL,
    title TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    topic TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status TEXT NOT NULL,
    next_seq INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    parent_id TEXT REFERENCES nodes(id),
    role TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL,
    summary TEXT
);
CREATE TABLE IF NOT EXISTS events (
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts TIMESTAMP NOT NULL,
    node_id TEXT NOT NULL,
    parent_node_id TEXT,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_events_node ON events(run_id, node_id);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    node_id TEXT NOT NULL REFERENCES nodes(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    bytes INTEGER NOT NULL,
    path_on_disk TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_questions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id),
    node_id TEXT NOT NULL REFERENCES nodes(id),
    question TEXT NOT NULL,
    options_json TEXT,
    answer TEXT,
    asked_at TIMESTAMP NOT NULL,
    answered_at TIMESTAMP
);
"""


class DB:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("APP_DB_PATH", "./.data/app.db")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._seq_locks: dict[str, asyncio.Lock] = {}

    async def connect(self):
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()

    async def close(self):
        if self._conn:
            await self._conn.close()

    async def init_schema(self):
        async with self._lock:
            await self._conn.executescript(SCHEMA_SQL)
            await self._conn.commit()

    async def execute(self, sql: str, params=()):
        async with self._lock:
            await self._conn.execute(sql, params)
            await self._conn.commit()

    async def fetchall(self, sql: str, params=()):
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            rows = await cur.fetchall()
            await cur.close()
            return rows

    async def fetchone(self, sql: str, params=()):
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            row = await cur.fetchone()
            await cur.close()
            return row

    def _seq_lock_for(self, run_id: str) -> asyncio.Lock:
        if run_id not in self._seq_locks:
            self._seq_locks[run_id] = asyncio.Lock()
        return self._seq_locks[run_id]

    async def next_seq(self, run_id: str) -> int:
        async with self._seq_lock_for(run_id):
            async with self._lock:
                cur = await self._conn.execute(
                    "SELECT next_seq FROM runs WHERE id=?", (run_id,))
                row = await cur.fetchone()
                await cur.close()
                if row is None:
                    raise KeyError(f"unknown run {run_id}")
                n = row[0]
                await self._conn.execute(
                    "UPDATE runs SET next_seq=? WHERE id=?", (n + 1, run_id))
                await self._conn.commit()
                return n

    async def insert_event(self, ev: AgentEvent):
        async with self._lock:
            await self._conn.execute(
                "INSERT INTO events (run_id, seq, ts, node_id, parent_node_id, "
                "type, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ev.run_id, ev.seq, ev.ts, ev.node_id, ev.parent_node_id,
                 ev.type.value, ev.payload.model_dump_json()),
            )
            await self._conn.commit()

    async def fetch_events_from(
        self, run_id: str, from_seq: int = 0, limit: int = 1000
    ) -> list[AgentEvent]:
        async with self._lock:
            cur = await self._conn.execute(
                "SELECT seq, ts, node_id, parent_node_id, type, payload_json "
                "FROM events WHERE run_id=? AND seq>=? ORDER BY seq LIMIT ?",
                (run_id, from_seq, limit),
            )
            rows = await cur.fetchall()
            await cur.close()
        out: list[AgentEvent] = []
        for seq, ts, node_id, parent_node_id, type_, payload_json in rows:
            t = EventType(type_)
            payload = _TYPE_TO_PAYLOAD[t].model_validate_json(payload_json)
            out.append(AgentEvent(
                seq=seq, run_id=run_id, node_id=node_id,
                parent_node_id=parent_node_id, ts=ts,
                type=t, payload=payload,
            ))
        return out
