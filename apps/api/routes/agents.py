"""Agent registry: real handshake, explicit adapters, server-side credentials."""

import json
import time
import uuid

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import Field

from apps.api.storage import database
from envforge.agents import AgentConfig, request_agent

router = APIRouter(prefix="/v1/agents", tags=["Agents"])


class AgentCreate(AgentConfig):
    name: str = Field(min_length=1, max_length=160)


def agent_row(row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "adapter": row["adapter"],
        "config": json.loads(row["config_json"]),
        "created_at": row["created_at"],
    }


@router.post("")
def register_agent(payload: AgentCreate):
    agent_id, now = "agent_" + uuid.uuid4().hex, time.time()
    config = payload.model_dump(exclude={"name"})
    with database() as conn:
        conn.execute(
            "INSERT INTO agents VALUES (?, ?, ?, ?, ?)",
            (agent_id, payload.name, payload.adapter, json.dumps(config), now),
        )
        conn.execute(
            "INSERT INTO audit_events(event,resource_id,created_at) VALUES ('agent_registered',?,?)",
            (agent_id, now),
        )
    return {
        "id": agent_id,
        "name": payload.name,
        "adapter": payload.adapter,
        "config": config,
        "created_at": now,
    }


@router.get("")
def list_agents(limit: int = 100, offset: int = 0):
    if not 1 <= limit <= 200 or offset < 0:
        raise HTTPException(422, "Invalid pagination")
    with database() as conn:
        return [
            agent_row(row)
            for row in conn.execute(
                "SELECT * FROM agents ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        ]


@router.post("/{agent_id}/test-connection")
def test_agent_connection(agent_id: str):
    with database() as conn:
        row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Agent not found")
    config = AgentConfig.model_validate_json(row["config_json"])
    start = time.monotonic()
    if config.adapter == "http_endpoint":
        try:
            result = request_agent(
                config, {"protocol_version": "1", "operation": "health"}
            )
            if not isinstance(result, dict) or result.get("status") != "healthy":
                raise ValueError("Expected status=healthy")
            integration = config.metadata.get("integration")
            if integration in {"holmesgpt", "kubectl_ai"}:
                if result.get("integration") != integration:
                    raise ValueError("Connected to the wrong native agent bridge")
                runtime = {
                    key: result.get(key)
                    for key in ("integration", "model", "provider", "image_id")
                }
                if not all(
                    isinstance(value, str) and value for value in runtime.values()
                ):
                    raise ValueError("Bridge did not report its runtime identity")
                config.metadata["runtime"] = runtime
                with database() as conn:
                    conn.execute(
                        "UPDATE agents SET config_json=? WHERE id=?",
                        (config.model_dump_json(), agent_id),
                    )
        except (httpx.HTTPError, ValueError, RuntimeError, TimeoutError):
            raise HTTPException(
                502, "Agent handshake failed; check endpoint availability and protocol"
            ) from None
    return {
        "agent_id": agent_id,
        "status": "healthy",
        "adapter": config.adapter,
        "roundtrip_latency_ms": round((time.monotonic() - start) * 1000, 2),
    }
