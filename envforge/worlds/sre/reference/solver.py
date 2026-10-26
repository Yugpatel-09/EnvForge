"""Canonical reference solver verifying 100% solvability for SRE scenarios."""

from __future__ import annotations

from envforge.protocol.types import Action
from envforge.worlds.sre.faults.fault_catalog import FAULT_REGISTRY, FaultFamily
from envforge.worlds.sre.scenarios.generator import SRETask


class SREReferenceSolver:
    """Automated golden reference agent capable of solving any generated SRE task."""

    def __init__(self, task: SRETask):
        self.task = task
        self.step_idx = 0
        self.resolved_action_taken = False
        self.report_submitted = False
        self.remaining_faults = [task.fault_family] + (
            [task.secondary_fault] if task.secondary_fault else []
        )

    def next_action(self, last_observation: str | None = None) -> Action | None:
        """Determines the next optimal action in the reference sequence."""
        self.step_idx += 1
        component = (
            "payment-worker"
            if self.task.fault_family
            in (FaultFamily.WORKER_BACKLOG, FaultFamily.NETWORK_PARTITION)
            else "checkout-api"
        )

        # Step 1: Read logs to diagnose the system
        if self.step_idx == 1:
            return Action(
                action_id=f"ref_act_{self.step_idx}",
                tool="read_logs",
                arguments={"service": component, "lines": 20},
            )

        # Step 2: Inspect deployment / query metrics
        if self.step_idx == 2:
            return Action(
                action_id=f"ref_act_{self.step_idx}",
                tool="inspect_deploy",
                arguments={"service": component},
            )

        # Step 3: Execute canonical remediation
        if self.remaining_faults:
            fault_cls = FAULT_REGISTRY.get(self.remaining_faults.pop(0))
            if fault_cls:
                fault_inst = fault_cls(self.task.tier)
                solution = fault_inst.get_canonical_solution_action()
                self.resolved_action_taken = True
                return Action(
                    action_id=f"ref_act_{self.step_idx}",
                    tool=solution["tool"],
                    arguments=solution["arguments"],
                )

        # Step 4: Submit formal incident report
        if not self.report_submitted:
            self.report_submitted = True
            root_causes = {
                FaultFamily.DB_POOL_EXHAUSTION: "checkout-api database connection pool exhausted due to connection leak",
                FaultFamily.BAD_DEPLOYMENT: "faulty deployment v1.2.1-buggy introduced NullPointerExceptions",
                FaultFamily.FAULTY_ENV_CONFIG: "invalid database host wrong-db-host configured in checkout-api",
                FaultFamily.DEPENDENCY_TIMEOUT: "payment gateway timeout set too low causing upstream drops",
                FaultFamily.CACHE_SATURATION: "redis cache saturated causing key eviction and excessive DB query load",
                FaultFamily.SERVICE_DISCOVERY: "auth service url pointing to unreachable internal dns domain",
                FaultFamily.WORKER_BACKLOG: "payment-worker concurrency misconfigured causing order queue backlog",
                FaultFamily.RESOURCE_LIMITS: "pod memory limit too low causing oomkill on start",
                FaultFamily.EXPIRED_CREDENTIAL: "database authentication failure due to expired credential token",
                FaultFamily.NETWORK_PARTITION: "subnet route misconfigured blocking worker db traffic",
            }
            cause = root_causes.get(
                self.task.fault_family, f"issue in {self.task.fault_family.value}"
            )
            return Action(
                action_id=f"ref_act_{self.step_idx}",
                tool="submit_incident_report",
                arguments={
                    "root_cause": cause,
                    "mitigation": "Applied targeted config remediation and verified service health",
                    "primary_fault": self.task.fault_family.value,
                    "component": "payment-worker"
                    if self.task.fault_family
                    in (FaultFamily.WORKER_BACKLOG, FaultFamily.NETWORK_PARTITION)
                    else "checkout-api",
                    "evidence_action_ids": ["ref_act_1", "ref_act_2"],
                },
            )

        # Finished
        return None
