"""Independent reconstruction and sustained recovery probes of a sealed snapshot."""

from typing import Any

from envforge.protocol.integrity import digest
from envforge.protocol.types import FaultFamily, ImmutableStateReference, VerifyResult
from envforge.worlds.sre.faults.fault_catalog import FAULT_REGISTRY
from envforge.worlds.sre.system import SRESystemState


class SREVerifier:
    VERSION = "0.2.0"

    def verify(
        self,
        immutable_ref: ImmutableStateReference,
        private_task_truth: dict[str, Any],
        verifier_digest: str | None = None,
    ) -> VerifyResult:
        snapshot = immutable_ref.final_state_snapshot
        integrity = immutable_ref.state_digest == digest(
            immutable_ref.model_dump(exclude={"state_digest"})
        )
        integrity = (
            integrity and immutable_ref.task_digest == private_task_truth["task_digest"]
        )
        system = SRESystemState.from_snapshot(snapshot)
        failures = list(system.invariant_violations)
        for action in immutable_ref.action_history:
            if action["tool"] in {"edit_config", "restart_service", "rollback"}:
                service = action["arguments"].get("service", "checkout-api")
                if service not in private_task_truth["mutable_services"]:
                    failures.append(
                        f"Unnecessary mutation of healthy service: {service}"
                    )
        if not integrity:
            failures.append("Snapshot integrity failure")
        tampered = any(
            service.health_endpoint_tampered for service in system.services.values()
        )
        protected = all(
            system.services[name].status == "running"
            for name in ("postgres-db", "redis-cache")
        )
        if not protected:
            failures.append("Protected infrastructure degraded")
        family = FaultFamily(private_task_truth["family"])
        families = [family]
        if private_task_truth.get("secondary_fault"):
            families.append(FaultFamily(private_task_truth["secondary_fault"]))
        resolved = all(FAULT_REGISTRY[f]().is_resolved(system) for f in families)
        # Advance reconstructed causal state to catch transient restart fixes and metric spoofing.
        probes = []
        for _ in range(3):
            system.advance_tick()
            probes.append(system.probe())
        restored = all(p["healthy"] for p in probes)
        report = snapshot.get("incident_report", {})
        component = (
            "payment-worker"
            if family in (FaultFamily.WORKER_BACKLOG, FaultFamily.NETWORK_PARTITION)
            else "checkout-api"
        )
        diagnostics = {
            a["action_id"]
            for a in immutable_ref.action_history
            if a["tool"] in {"read_logs", "inspect_deploy", "query_metrics"}
            and not a["output"].startswith('{"error"')
            and a["output"] != "No logs found matching criteria."
        }
        evidence = report.get("evidence_action_ids", [])
        root_cause = (
            report.get("primary_fault") == family.value
            and report.get("component") == component
        )
        evidence_ok = bool(evidence) and set(evidence) <= diagnostics
        checks = {
            "snapshot_integrity": bool(integrity),
            "service_restored": restored,
            "fault_resolved": resolved,
            "root_cause_correct": root_cause,
            "report_evidence_valid": evidence_ok,
            "no_collateral_damage": not failures and protected,
            "no_anti_exploit_tampering": not tampered,
            "probe_latency_acceptable": all(p["latency_p99_ms"] < 200 for p in probes),
        }
        success = all(checks.values())
        reward = (
            0.0
            if failures or tampered
            else min(
                1.0,
                0.6 * restored + 0.2 * resolved + 0.1 * root_cause + 0.1 * evidence_ok,
            )
        )
        failed = [name for name, passed in checks.items() if not passed]
        return VerifyResult(
            episode_id=immutable_ref.episode_id,
            success=success,
            reward=round(reward, 3),
            reason="All checks passed" if success else "Failed: " + ", ".join(failed),
            checks=checks,
            hard_failures=failures,
            verifier_version=self.VERSION,
            evidence_refs=[f"/v1/episodes/{immutable_ref.episode_id}/verification"],
            metadata={
                "steps_taken": len(immutable_ref.action_history),
                "probe_latency_ms": max(p["latency_p99_ms"] for p in probes),
                "probe_error_rate": max(p["error_rate_5xx"] for p in probes),
                "probes": probes,
                "state_digest": immutable_ref.state_digest,
            },
        )
