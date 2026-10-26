"""Durable SQLite job claims, bounded execution, cancellation, and provenance."""

import json
import logging
import time
import uuid

from apps.api.storage import database
from envforge.agents import (
    AgentConfig,
    AgentPending,
    AgentProtocolError,
    close_agent,
    http_action,
    request_agent,
)
from envforge.protocol.integrity import digest
from envforge.protocol.types import DifficultyTier, SuiteName
from envforge.provenance import implementation_digest
from envforge.worlds.sre.environment import SREIncidentResponseEnvironment
from envforge.worlds.sre.reference.solver import SREReferenceSolver
from envforge.worlds.sre.scenarios.generator import SREScenarioGenerator
from envforge.worlds.sre.tools.dispatcher import tool_definitions
from envforge.worlds.sre.verifier.verifier import SREVerifier

logger = logging.getLogger(__name__)
LEASE_SECONDS = 120


def recover_expired_jobs() -> None:
    # A partially executed run is never silently resumed under different live state.
    with database() as conn:
        conn.execute(
            """UPDATE evaluations SET status='INFRA_FAILED', error='Worker lease expired; start a new run', updated_at=?
                        WHERE status='RUNNING' AND lease_until < ?""",
            (time.time(), time.time()),
        )


def run_evaluation_task(eval_id: str) -> bool:
    owner = uuid.uuid4().hex
    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if (
            conn.execute(
                "SELECT COUNT(*) FROM evaluations WHERE status='RUNNING'"
            ).fetchone()[0]
            >= 2
        ):
            return False
        claimed = conn.execute(
            """UPDATE evaluations SET status='RUNNING',worker_id=?,lease_until=?,updated_at=?
                                  WHERE id=? AND status='QUEUED'""",
            (owner, time.time() + LEASE_SECONDS, time.time(), eval_id),
        ).rowcount
        if not claimed:
            return False
        row = conn.execute(
            "SELECT * FROM evaluations WHERE id=?", (eval_id,)
        ).fetchone()
    env = SREIncidentResponseEnvironment()
    config = None
    try:
        manifest = json.loads(row["manifest_json"])
        expected = {
            "environment_id": env.ENVIRONMENT_ID,
            "environment_version": env.VERSION,
            "scenario_version": SREScenarioGenerator.VERSION,
            "verifier_version": SREVerifier.VERSION,
            "implementation_digest": implementation_digest(),
        }
        if any(
            manifest.get(key) != value for key, value in expected.items()
        ) or manifest.get("digest") != digest(
            {key: value for key, value in manifest.items() if key != "digest"}
        ):
            raise ValueError("Queued run does not match the installed implementation")
        config = AgentConfig.model_validate(manifest["agent_config"])
        if config.metadata.get("integration") in {"holmesgpt", "kubectl_ai"}:
            runtime = config.metadata.get("runtime")
            if not runtime:
                raise ValueError(
                    "Test the native agent connection before launching a run"
                )
            health = request_agent(config, {"operation": "health"})
            if not isinstance(health, dict) or any(
                health.get(key) != value for key, value in runtime.items()
            ):
                raise ValueError(
                    "Native agent runtime changed; test connection and start a new run"
                )
        for seed in manifest["seeds"]:
            with database() as conn:
                run = conn.execute(
                    "SELECT status FROM evaluations WHERE id=? AND worker_id=?",
                    (eval_id, owner),
                ).fetchone()
                if run is None or run["status"] != "RUNNING":
                    return True
            initial = env.reset(
                f"sre:{manifest['suite']}:{manifest['tier']}:{seed}",
                seed,
                suite=SuiteName(manifest["suite"]),
                tier=DifficultyTier(manifest["tier"]),
            )
            ep_id = next(iter(env.active_episodes))
            ep = env.active_episodes[ep_id]
            solver = (
                SREReferenceSolver(ep["task"])
                if config.adapter == "reference_solver"
                else None
            )
            started = time.monotonic()
            deadline = started + ep["task"].limits["timeout_seconds"]
            obs = env.observe(ep_id)
            calls = 0
            protocol_error = None
            while True:
                calls += 1
                if calls > ep["max_steps"] * 2:
                    protocol_error = (
                        "Agent repeatedly reused actions without making progress"
                    )
                    break
                with database() as conn:
                    run = conn.execute(
                        "SELECT status FROM evaluations WHERE id=? AND worker_id=?",
                        (eval_id, owner),
                    ).fetchone()
                    if run is None or run["status"] != "RUNNING":
                        return True
                    conn.execute(
                        "UPDATE evaluations SET lease_until=?, updated_at=? WHERE id=? AND worker_id=? AND status='RUNNING'",
                        (time.time() + LEASE_SECONDS, time.time(), eval_id, owner),
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Episode wall-clock budget exceeded")
                try:
                    action = (
                        solver.next_action(obs.tool_output)
                        if solver
                        else http_action(
                            config,
                            ep_id,
                            obs.model_dump(),
                            tool_definitions(),
                            min(20, remaining),
                        )
                    )
                except AgentPending:
                    calls -= 1
                    time.sleep(min(0.25, max(0, deadline - time.monotonic())))
                    continue
                except AgentProtocolError as exc:
                    protocol_error = str(exc)
                    break
                if action is None:
                    break
                # Test-only tampering tool must not be exposed by the control plane.
                if action.tool not in {t["name"] for t in tool_definitions()}:
                    protocol_error = "Agent selected an unavailable tool"
                    break
                try:
                    result = env.step(ep_id, action.action_id, action)
                except ValueError:
                    protocol_error = "Action ID reused with different content"
                    break
                obs = result.observation
                if result.done:
                    break
            sealed = env.seal(ep_id)
            verification = env.verify(sealed, ep["hidden_truth"])
            if protocol_error:
                verification.success = False
                verification.reward = 0
                verification.reason = protocol_error
                verification.checks["agent_protocol_valid"] = False
            trajectory = {
                "schema_version": "1",
                "environment_version": env.VERSION,
                "task": ep["task"].model_dump(mode="json"),
                "initial_observation": initial.model_dump(
                    exclude={"hidden_truth", "system_state"}
                ),
                "initial_state": initial.system_state,
                "action_history": sealed.action_history,
                "event_log": sealed.event_log,
                "final_state": sealed.final_state_snapshot,
                "state_digest": sealed.state_digest,
                "duration_seconds": round(time.monotonic() - started, 4),
            }
            with database() as conn:
                conn.execute("BEGIN IMMEDIATE")
                status = conn.execute(
                    "SELECT status FROM evaluations WHERE id=? AND worker_id=?",
                    (eval_id, owner),
                ).fetchone()
                if status is None or status["status"] != "RUNNING":
                    return True
                conn.execute(
                    "INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        ep_id,
                        eval_id,
                        ep["task"].task_id,
                        seed,
                        "COMPLETED",
                        int(verification.success),
                        verification.reward,
                        json.dumps(trajectory),
                        verification.model_dump_json(),
                        time.time(),
                    ),
                )
                conn.execute(
                    """UPDATE evaluations SET completed_episodes=completed_episodes+1,
                                success_count=success_count+?,hard_failures_count=hard_failures_count+?,updated_at=?
                                WHERE id=? AND worker_id=? AND status='RUNNING'""",
                    (
                        int(verification.success),
                        int(bool(verification.hard_failures)),
                        time.time(),
                        eval_id,
                        owner,
                    ),
                )
            close_agent(config, ep_id)
            env.close(ep_id)
        with database() as conn:
            conn.execute(
                "UPDATE evaluations SET status='COMPLETED',lease_until=NULL,updated_at=? WHERE id=? AND worker_id=? AND status='RUNNING'",
                (time.time(), eval_id, owner),
            )
    except Exception as exc:
        logger.exception("Evaluation %s failed", eval_id)
        with database() as conn:
            # Never persist arbitrary endpoint response text or credential-bearing URLs.
            conn.execute(
                "UPDATE evaluations SET status='INFRA_FAILED', error=?,updated_at=? WHERE id=? AND worker_id=? AND status='RUNNING'",
                (
                    f"{type(exc).__name__}: evaluation failed; inspect worker logs",
                    time.time(),
                    eval_id,
                    owner,
                ),
            )
    finally:
        for ep_id in list(env.active_episodes):
            if config is not None:
                close_agent(config, ep_id)
            env.close(ep_id)
    return True


def worker_once() -> bool:
    recover_expired_jobs()
    with database() as conn:
        row = conn.execute(
            "SELECT id FROM evaluations WHERE status='QUEUED' ORDER BY created_at LIMIT 1"
        ).fetchone()
    return run_evaluation_task(row["id"]) if row else False


def main() -> None:
    while True:
        if not worker_once():
            time.sleep(1)


if __name__ == "__main__":
    main()
