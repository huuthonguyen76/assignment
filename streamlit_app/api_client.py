"""Thin httpx wrappers around the FastAPI endpoints."""
from __future__ import annotations
import os
import httpx
from backend.schema import AgentEvent, _TYPE_TO_PAYLOAD, EventType

API_BASE = os.getenv("APP_API_BASE", "http://localhost:8000")


def start_run(session_id: str, topic: str) -> str:
    r = httpx.post(f"{API_BASE}/runs",
                   json={"session_id": session_id, "topic": topic},
                   timeout=10.0)
    r.raise_for_status()
    return r.json()["run_id"]


def fetch_events(run_id: str, from_seq: int = 0,
                 limit: int = 200) -> list[AgentEvent]:
    r = httpx.get(f"{API_BASE}/runs/{run_id}/events",
                  params={"from": from_seq, "limit": limit}, timeout=10.0)
    r.raise_for_status()
    out: list[AgentEvent] = []
    for raw in r.json():
        out.append(AgentEvent.model_validate(raw))
    return out


def submit_answer(run_id: str, question_id: str, answer: str):
    r = httpx.post(f"{API_BASE}/runs/{run_id}/answer",
                   json={"question_id": question_id, "answer": answer},
                   timeout=10.0)
    r.raise_for_status()


def retry_node(run_id: str, node_id: str) -> str:
    r = httpx.post(f"{API_BASE}/runs/{run_id}/retry",
                   params={"node_id": node_id}, timeout=10.0)
    r.raise_for_status()
    return r.json()["new_node_id"]


def list_artifacts(run_id: str) -> list[dict]:
    r = httpx.get(f"{API_BASE}/runs/{run_id}/artifacts", timeout=10.0)
    r.raise_for_status()
    return r.json()


def get_artifact_bytes(run_id: str, artifact_id: str) -> bytes:
    r = httpx.get(f"{API_BASE}/runs/{run_id}/artifacts/{artifact_id}",
                  timeout=10.0)
    r.raise_for_status()
    return r.content


def list_sessions() -> list[dict]:
    r = httpx.get(f"{API_BASE}/sessions", timeout=10.0)
    r.raise_for_status()
    return r.json()


def list_session_runs(session_id: str) -> list[dict]:
    r = httpx.get(f"{API_BASE}/sessions/{session_id}/runs", timeout=10.0)
    r.raise_for_status()
    return r.json()
