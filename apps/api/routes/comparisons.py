"""Paired comparisons require identical, complete evaluation distributions."""

import math

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.api.routes.evaluations import find_evaluation
from apps.api.storage import database

router = APIRouter(prefix="/v1/comparisons", tags=["Comparisons"])


class ComparisonRequest(BaseModel):
    baseline_eval_id: str
    candidate_eval_id: str


@router.post("")
def compare_evaluations(req: ComparisonRequest):
    if req.baseline_eval_id == req.candidate_eval_id:
        raise HTTPException(422, "Select two different evaluations")
    base, candidate = (
        find_evaluation(key) for key in (req.baseline_eval_id, req.candidate_eval_id)
    )
    if any(run["status"] != "COMPLETED" for run in (base, candidate)):
        raise HTTPException(409, "Both evaluations must be completed")
    keys = (
        "environment_id",
        "environment_version",
        "scenario_version",
        "verifier_version",
        "implementation_digest",
        "suite",
        "tier",
        "seeds",
    )
    if any(
        key not in run["manifest"] for key in keys for run in (base, candidate)
    ) or any(
        base["manifest"].get(key) != candidate["manifest"].get(key) for key in keys
    ):
        raise HTTPException(
            422, "Comparisons require matching versions, suite, tier and seeds"
        )
    with database() as conn:
        rows = [
            conn.execute(
                "SELECT seed,reward,success FROM episodes WHERE evaluation_id=? ORDER BY seed",
                (run["id"],),
            ).fetchall()
            for run in (base, candidate)
        ]
    if (
        len(rows[0]) != base["total_episodes"]
        or len(rows[1]) != candidate["total_episodes"]
    ):
        raise HTTPException(409, "Incomplete episode evidence")
    expected_seeds = sorted(base["manifest"]["seeds"])
    if any([row["seed"] for row in group] != expected_seeds for group in rows):
        raise HTTPException(409, "Recorded episodes do not match the run manifest")
    deltas = [c["reward"] - b["reward"] for b, c in zip(*rows)]
    mean = sum(deltas) / len(deltas)
    standard_error = (
        math.sqrt(
            sum((d - mean) ** 2 for d in deltas) / (len(deltas) - 1) / len(deltas)
        )
        if len(deltas) > 1
        else None
    )
    interval = (
        [round(mean - 1.96 * standard_error, 4), round(mean + 1.96 * standard_error, 4)]
        if standard_error is not None
        else None
    )
    oracle = base["manifest"].get("baseline_uses_private_truth") or candidate[
        "manifest"
    ].get("baseline_uses_private_truth")
    recommendation = "BASELINE_ONLY" if oracle else "REVIEW"
    if not oracle and (candidate["hard_failures_count"] or mean < 0):
        recommendation = "BLOCK"
    elif not oracle and interval and interval[0] > 0 and len(deltas) >= 30:
        recommendation = "PROMOTE"
    return {
        "baseline_id": base["id"],
        "candidate_id": candidate["id"],
        "matched_episodes": len(deltas),
        "wins": sum(d > 0.05 for d in deltas),
        "losses": sum(d < -0.05 for d in deltas),
        "ties": sum(abs(d) <= 0.05 for d in deltas),
        "average_reward_delta": round(mean, 4),
        "reward_delta_95_ci": interval,
        "interval_method": "paired normal approximation",
        "baseline_success_rate": base["success_count"] / base["total_episodes"],
        "candidate_success_rate": candidate["success_count"]
        / candidate["total_episodes"],
        "safety_violations_diff": candidate["hard_failures_count"]
        - base["hard_failures_count"],
        "recommendation": recommendation,
    }
