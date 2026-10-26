"""Reproducible release gates. This is product QA, not model calibration."""

from envforge.protocol.integrity import digest
from envforge.protocol.types import Action, DifficultyTier, FaultFamily, SuiteName
from envforge.provenance import implementation_digest
from envforge.worlds.sre.environment import SREIncidentResponseEnvironment
from envforge.worlds.sre.faults.fault_catalog import FAULT_REGISTRY
from envforge.worlds.sre.reference.solver import SREReferenceSolver
from envforge.worlds.sre.verifier.verifier import SREVerifier


def solve(seed: int, suite: SuiteName, tier: DifficultyTier) -> tuple[dict, dict]:
    env = SREIncidentResponseEnvironment()
    initial = env.reset("qa", seed, suite=suite, tier=tier)
    ep_id = next(iter(env.active_episodes))
    task = env.active_episodes[ep_id]["task"]
    system = env.active_episodes[ep_id]["system"]
    for family in (task.fault_family, task.secondary_fault):
        if family and FAULT_REGISTRY[family]().is_resolved(system):
            raise RuntimeError(f"Generated fault {family} was not active at reset")
    solver = SREReferenceSolver(env.active_episodes[ep_id]["task"])
    while (action := solver.next_action()) is not None:
        result = env.step(ep_id, action.action_id, action)
        if result.done:
            break
    sealed = env.seal(ep_id)
    verified = env.verify(sealed, initial.hidden_truth)
    canonical = sealed.model_dump(exclude={"episode_id", "state_digest"})
    env.close(ep_id)
    return canonical, verified.model_dump()


def run_qa(instances: int = 50, repeats: int = 20) -> dict:
    failures = []
    entries = []
    for suite in SuiteName:
        for tier in DifficultyTier:
            unique = set()
            for seed in range(instances):
                state, result = solve(seed, suite, tier)
                unique.add(digest(state))
                entries.append(
                    {
                        "suite": suite.value,
                        "tier": tier.value,
                        "seed": seed,
                        "digest": digest(state),
                        "success": result["success"],
                        "reward": result["reward"],
                    }
                )
                if not result["success"]:
                    failures.append(
                        {
                            "suite": suite.value,
                            "tier": tier.value,
                            "seed": seed,
                            "reason": result["reason"],
                        }
                    )
            if len(unique) != instances:
                failures.append(
                    {
                        "suite": suite.value,
                        "tier": tier.value,
                        "reason": "Duplicate instances",
                    }
                )
    expected, _ = solve(42, SuiteName.STANDARD, DifficultyTier.HARD)
    deterministic = all(
        solve(42, SuiteName.STANDARD, DifficultyTier.HARD)[0] == expected
        for _ in range(repeats)
    )
    attacks = {}
    for tool, arguments in (
        ("tamper_health_endpoint", {"service": "checkout-api"}),
        ("restart_service", {"service": "postgres-db"}),
        ("restart_healthy_worker", {"service": "payment-worker"}),
        ("rollback", {"service": "redis-cache", "target_revision": "v1.2.0"}),
        (
            "edit_config",
            {"service": "postgres-db", "key": "DB_POOL_MAX", "value": "100"},
        ),
    ):
        env = SREIncidentResponseEnvironment()
        obs = env.reset("exploit", 1, family=FaultFamily.BAD_DEPLOYMENT)
        ep_id = next(iter(env.active_episodes))
        env.step(
            ep_id,
            "attack",
            Action(
                action_id="attack",
                tool="restart_service" if tool == "restart_healthy_worker" else tool,
                arguments=arguments,
            ),
        )
        solver = SREReferenceSolver(env.active_episodes[ep_id]["task"])
        while (action := solver.next_action()) is not None:
            if env.step(ep_id, action.action_id, action).done:
                break
        result = env.verify(env.seal(ep_id), obs.hidden_truth)
        attacks[tool] = not result.success and result.reward == 0
        env.close(ep_id)
    env = SREIncidentResponseEnvironment()
    obs = env.reset("forgery", 1)
    ep_id = next(iter(env.active_episodes))
    sealed = env.seal(ep_id)
    sealed.final_state_snapshot["services"]["checkout-api"]["current_revision"] = (
        "forged"
    )
    sealed.state_digest = digest(sealed.model_dump(exclude={"state_digest"}))
    attacks["rehashed_snapshot_forgery"] = not env.verify(
        sealed, obs.hidden_truth
    ).success
    env.close(ep_id)
    passed = not failures and deterministic and all(attacks.values())
    return {
        "schema_version": "1",
        "environment_version": SREIncidentResponseEnvironment.VERSION,
        "verifier_version": SREVerifier.VERSION,
        "implementation_digest": implementation_digest(),
        "status": "PASS" if passed else "FAIL",
        "instances_per_tier_per_suite": instances,
        "instances_tested": len(entries),
        "reference_successes": sum(bool(e["success"]) for e in entries),
        "determinism_repeats": repeats,
        "determinism_passed": deterministic,
        "exploit_checks": attacks,
        "failures": failures,
        "manifest_digest": digest(entries),
        "instances": entries,
        "limitations": [
            "Reference solver uses private truth",
            "No independent model calibration",
            "No human SRE realism review",
            "Public heldout generator",
        ],
    }
