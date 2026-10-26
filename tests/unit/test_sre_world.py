"""Unit and solvability tests for EnvForge SRE Incident-Response World."""

import pytest

from envforge.protocol.types import Action, DifficultyTier, FaultFamily, SuiteName
from envforge.worlds.sre.environment import SREIncidentResponseEnvironment
from envforge.worlds.sre.reference.solver import SREReferenceSolver


class TestSRESimulationWorld:
    """Validates SRE world mechanics, fault injection, and the trusted runtime protocol."""

    def test_environment_reset_and_observe(self):
        env = SREIncidentResponseEnvironment()
        obs = env.reset(
            task_id="task_sre_001",
            seed=101,
            suite=SuiteName.SMOKE,
            tier=DifficultyTier.EASY,
            family=FaultFamily.DB_POOL_EXHAUSTION,
        )

        assert obs.step == 0
        assert "503" in obs.prompt or "Checkout" in obs.prompt
        assert obs.hidden_truth["family"] == "db_pool_exhaustion"

        # Check that agent-visible observation does NOT contain hidden_truth
        agent_obs = env.observe(next(iter(env.active_episodes)))
        assert not hasattr(agent_obs, "hidden_truth")
        assert agent_obs.step == 0

    def test_tool_dispatch_and_step(self):
        env = SREIncidentResponseEnvironment()
        env.reset(
            task_id="task_sre_002",
            seed=102,
            suite=SuiteName.STANDARD,
            tier=DifficultyTier.EASY,
            family=FaultFamily.DB_POOL_EXHAUSTION,
        )
        ep_id = next(iter(env.active_episodes))

        # Step 1: Read logs
        step_res = env.step(
            episode_id=ep_id,
            action_id="act_1",
            action=Action(action_id="act_1", tool="read_logs", arguments={"lines": 10}),
        )
        assert not step_res.done
        assert "DB pool exhausted" in (step_res.observation.tool_output or "")

        # Step 2: Query metrics
        step_res = env.step(
            episode_id=ep_id,
            action_id="act_2",
            action=Action(
                action_id="act_2",
                tool="query_metrics",
                arguments={"metric_name": "error_rate_5xx"},
            ),
        )
        assert not step_res.done
        assert "error_rate_5xx" in (step_res.observation.tool_output or "")

    @pytest.mark.parametrize("fault_family", list(FaultFamily))
    def test_all_10_fault_families_solvable_by_reference_solver(
        self, fault_family: FaultFamily
    ):
        """Release Gate 1 (Solvability): Reference solver must achieve 100% success on all 10 fault families."""
        env = SREIncidentResponseEnvironment()
        env.reset(
            task_id=f"solvability_test_{fault_family.value}",
            seed=200,
            suite=SuiteName.STANDARD,
            tier=DifficultyTier.EASY,
            family=fault_family,
        )
        ep_id = next(iter(env.active_episodes))
        ep_data = env.active_episodes[ep_id]
        task = ep_data["task"]

        solver = SREReferenceSolver(task)

        # Run reference solver
        last_tool_output = None
        while True:
            action = solver.next_action(last_tool_output)
            if not action:
                break
            step_res = env.step(
                episode_id=ep_id, action_id=action.action_id, action=action
            )
            last_tool_output = step_res.observation.tool_output

        # Seal state and verify
        sealed_ref = env.seal(ep_id)
        verify_res = env.verify(sealed_ref, ep_data["hidden_truth"])

        assert verify_res.success, (
            f"Reference solver failed on {fault_family}: {verify_res.checks}, failures: {verify_res.hard_failures}"
        )
        assert verify_res.reward >= 0.85
        assert verify_res.checks["service_restored"]
        assert verify_res.checks["no_collateral_damage"]
        assert len(verify_res.hard_failures) == 0

        cleanup = env.close(ep_id)
        assert cleanup.success
