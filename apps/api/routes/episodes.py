"""Episode trajectory and verification drilldown endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from apps.api.storage import get_db_connection

router = APIRouter(prefix="/v1/episodes", tags=["Episodes"])


@router.get("/{episode_id}/trajectory")
def get_episode_trajectory(episode_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    row = cursor.execute(
        "SELECT id, task_id, seed, trajectory_json FROM episodes WHERE id = ?",
        (episode_id,),
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Episode not found")

    traj_data = json.loads(row["trajectory_json"])
    return {
        "episode_id": row["id"],
        "task_id": row["task_id"],
        "seed": row["seed"],
        "action_history": traj_data.get("action_history", []),
        "event_log": traj_data.get("event_log", []),
        "final_state": traj_data.get("final_state", {}),
        "initial_state": traj_data.get("initial_state", {}),
        "initial_observation": traj_data.get("initial_observation", {}),
        "task": traj_data.get("task", {}),
        "state_digest": traj_data.get("state_digest"),
        "duration_seconds": traj_data.get("duration_seconds"),
    }


@router.get("/{episode_id}/verification")
def get_episode_verification(episode_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    row = cursor.execute(
        "SELECT id, verification_json FROM episodes WHERE id = ?", (episode_id,)
    ).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Episode not found")

    return json.loads(row["verification_json"])
