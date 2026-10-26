"""Version-pinned evaluation batches backed by a durable queue."""

import json
import os
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from apps.api.runner import run_evaluation_task
from apps.api.storage import database
from envforge.protocol.integrity import digest
from envforge.protocol.types import DifficultyTier, SuiteName
from envforge.provenance import implementation_digest
from envforge.worlds.sre.environment import SREIncidentResponseEnvironment
from envforge.worlds.sre.scenarios.generator import SREScenarioGenerator
from envforge.worlds.sre.verifier.verifier import SREVerifier

router = APIRouter(prefix="/v1/evaluations", tags=["Evaluations"])


class EvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="SRE Release Gate Eval", min_length=1, max_length=160)
    environment_id: str = SREIncidentResponseEnvironment.ENVIRONMENT_ID
    environment_version: str = SREIncidentResponseEnvironment.VERSION
    suite: SuiteName = SuiteName.STANDARD
    tier: DifficultyTier = DifficultyTier.EASY
    agent_id: str
    episodes_count: int = Field(default=10, ge=1, le=500)
    base_seed: int = Field(default=42, ge=0, le=2**31 - 501)


def evaluation_row(row) -> dict:
    data = dict(row)
    data["manifest"] = json.loads(data.pop("manifest_json"))
    data.pop("worker_id", None)
    data.pop("lease_until", None)
    return data


def find_evaluation(eval_id: str) -> dict:
    with database() as conn:
        row = conn.execute(
            "SELECT * FROM evaluations WHERE id=?", (eval_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Evaluation not found")
    return evaluation_row(row)


@router.post("")
def create_evaluation(payload: EvaluationCreate, background_tasks: BackgroundTasks):
    if (
        payload.environment_id != SREIncidentResponseEnvironment.ENVIRONMENT_ID
        or payload.environment_version != SREIncidentResponseEnvironment.VERSION
    ):
        raise HTTPException(422, "Environment/version is not installed")
    now, eval_id = time.time(), "eval_" + uuid.uuid4().hex
    with database() as conn:
        # Serialize admissions to enforce a bounded durable queue even under concurrent requests.
        conn.execute("BEGIN IMMEDIATE")
        active = conn.execute(
            "SELECT COUNT(*) FROM evaluations WHERE status IN ('QUEUED','RUNNING')"
        ).fetchone()[0]
        if active >= 20:
            raise HTTPException(429, "Evaluation queue is full")
        agent = conn.execute(
            "SELECT * FROM agents WHERE id=?", (payload.agent_id,)
        ).fetchone()
        if agent is None:
            raise HTTPException(422, "Register an agent before creating an evaluation")
        manifest = {
            "schema_version": "1",
            "environment_id": payload.environment_id,
            "environment_version": payload.environment_version,
            "scenario_version": SREScenarioGenerator.VERSION,
            "verifier_version": SREVerifier.VERSION,
            "implementation_digest": implementation_digest(),
            "suite": payload.suite.value,
            "tier": payload.tier.value,
            "seeds": list(
                range(payload.base_seed, payload.base_seed + payload.episodes_count)
            ),
            "agent_config": json.loads(agent["config_json"]),
            "agent_name": agent["name"],
            "baseline_uses_private_truth": agent["adapter"] == "reference_solver",
        }
        manifest["digest"] = digest(manifest)
        conn.execute(
            """INSERT INTO evaluations
                        (id,name,environment_id,suite,tier,agent_id,status,total_episodes,completed_episodes,
                         success_count,hard_failures_count,created_at,updated_at,manifest_json)
                        VALUES (?,?,?,?,?,?,'QUEUED',?,0,0,0,?,?,?)""",
            (
                eval_id,
                payload.name,
                payload.environment_id,
                payload.suite.value,
                payload.tier.value,
                payload.agent_id,
                payload.episodes_count,
                now,
                now,
                json.dumps(manifest),
            ),
        )
        conn.execute(
            "INSERT INTO audit_events(event,resource_id,created_at) VALUES ('evaluation_queued',?,?)",
            (eval_id, now),
        )
    if os.environ.get("ENVFORGE_EXTERNAL_WORKER") != "1":
        background_tasks.add_task(run_evaluation_task, eval_id)
    return find_evaluation(eval_id)


@router.get("")
def list_evaluations(
    limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)
):
    with database() as conn:
        return [
            evaluation_row(row)
            for row in conn.execute(
                "SELECT * FROM evaluations ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        ]


@router.get("/{eval_id}")
def get_evaluation(eval_id: str):
    return find_evaluation(eval_id)


@router.post("/{eval_id}/cancel")
def cancel_evaluation(eval_id: str):
    find_evaluation(eval_id)
    with database() as conn:
        conn.execute(
            "UPDATE evaluations SET status='CANCELLED',updated_at=? WHERE id=? AND status IN ('QUEUED','RUNNING')",
            (time.time(), eval_id),
        )
        conn.execute(
            "INSERT INTO audit_events(event,resource_id,created_at) VALUES ('cancellation_requested',?,?)",
            (eval_id, time.time()),
        )
    return find_evaluation(eval_id)


@router.get("/{eval_id}/episodes")
def list_evaluation_episodes(
    eval_id: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)
):
    find_evaluation(eval_id)
    with database() as conn:
        rows = conn.execute(
            "SELECT id,task_id,seed,status,success,reward,created_at FROM episodes WHERE evaluation_id=? ORDER BY seed LIMIT ? OFFSET ?",
            (eval_id, limit, offset),
        )
        return [{**dict(row), "success": bool(row["success"])} for row in rows]
