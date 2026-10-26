"""Scenario and task generator for SRE Incident-Response simulation."""

from __future__ import annotations

import random
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from envforge.protocol.integrity import digest
from envforge.protocol.types import DifficultyTier, FaultFamily, SuiteName


class SRETask(BaseModel):
    """A parameterized SRE incident scenario."""

    task_id: str
    suite: SuiteName
    tier: DifficultyTier
    fault_family: FaultFamily
    prompt: str
    initial_symptoms: str
    seed: int
    secondary_fault: FaultFamily | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    limits: dict[str, Any] = Field(
        default_factory=lambda: {"max_steps": 30, "timeout_seconds": 600}
    )


class SREScenarioGenerator:
    """Generates deterministic task distributions across suites and tiers."""

    VERSION = "0.2.0"

    PROMPT_TEMPLATES: ClassVar[dict[FaultFamily, str]] = {
        FaultFamily.DB_POOL_EXHAUSTION: (
            "Checkout began returning intermittent 503 errors and latency spikes. "
            "Diagnose the cause, restore healthy service, and ensure no healthy background workloads are degraded."
        ),
        FaultFamily.BAD_DEPLOYMENT: (
            "A spike in uncaught exceptions and 500 responses was observed immediately after the most recent deployment. "
            "Inspect deployment history, restore stability to checkout-api, and submit an incident report."
        ),
        FaultFamily.FAULTY_ENV_CONFIG: (
            "checkout-api is failing to start up or connect to its primary backend datastore. "
            "Inspect service configuration and logs, correct any invalid parameters, and ensure the service recovers."
        ),
        FaultFamily.DEPENDENCY_TIMEOUT: (
            "Checkout transactions are timing out upstream. Latency has degraded significantly. "
            "Diagnose the timeout configuration and tune the service so transactions complete reliably."
        ),
        FaultFamily.CACHE_SATURATION: (
            "High eviction volume and cache misses are degrading checkout response times. "
            "Inspect cache metrics and remediate eviction pressure."
        ),
        FaultFamily.SERVICE_DISCOVERY: (
            "checkout-api is reporting connection refused when verifying authentication tokens with internal auth services. "
            "Remediate the service discovery configuration."
        ),
        FaultFamily.WORKER_BACKLOG: (
            "Payment order queue backlog has surged. Background fulfillment jobs are delayed. "
            "Diagnose the payment-worker concurrency configuration and clear the backlog."
        ),
        FaultFamily.RESOURCE_LIMITS: (
            "checkout-api pods are crashing in crashloopbackoff with OOMKilled events. "
            "Adjust resource allocations and restore service."
        ),
        FaultFamily.EXPIRED_CREDENTIAL: (
            "checkout-api logs indicate authorization and authentication failure against the database. "
            "Rotate or restore valid credentials."
        ),
        FaultFamily.NETWORK_PARTITION: (
            "Background payment worker reports isolated network route errors. "
            "Fix the routing configuration."
        ),
    }

    @classmethod
    def generate_task(
        cls,
        task_id: str,
        seed: int = 42,
        suite: SuiteName = SuiteName.STANDARD,
        tier: DifficultyTier = DifficultyTier.EASY,
        family: FaultFamily | None = None,
    ) -> SRETask:
        rng = random.Random(f"{cls.VERSION}:{suite.value}:{seed}")

        if family is None:
            if suite == SuiteName.SMOKE:
                family = FaultFamily.DB_POOL_EXHAUSTION
            else:
                family = list(FaultFamily)[seed % len(FaultFamily)]

        prompt = cls.PROMPT_TEMPLATES[family]

        symptom_extra = ""
        if tier == DifficultyTier.MEDIUM:
            symptom_extra = (
                " Secondary alert: customer-facing retry volume has doubled."
            )
        elif tier == DifficultyTier.HARD:
            symptom_extra = " Secondary alert: multiple conflicting alerts received; restricted operational permissions apply."

        secondary = None
        if tier == DifficultyTier.HARD:
            # These faults replace the same URL. Combining them would erase one cause.
            url_faults = {FaultFamily.FAULTY_ENV_CONFIG, FaultFamily.EXPIRED_CREDENTIAL}
            secondary = rng.choice(
                [
                    f
                    for f in FaultFamily
                    if f != family and not (family in url_faults and f in url_faults)
                ]
            )
        scenario_id = digest(
            {"suite": suite, "tier": tier, "seed": seed, "version": cls.VERSION}
        )[7:19]
        return SRETask(
            task_id=task_id,
            suite=suite,
            tier=tier,
            fault_family=family,
            prompt=(
                f"Incident {scenario_id}. {prompt}{symptom_extra} "
                "Restore both checkout and payment fulfillment. Do not modify protected postgres-db or redis-cache. "
                "Submit one primary_fault (the fault family identifier), component, root_cause, mitigation, "
                "and evidence_action_ids from diagnostic tool calls. Valid database credentials are synthetic: "
                "postgres://app:secr3t@postgres-db:5432/checkout. Target auth: http://auth-service.internal:8081."
            ),
            initial_symptoms=f"Alert triggered for checkout cluster: {family.value}",
            seed=seed,
            secondary_fault=secondary,
            parameters={
                "scenario_id": scenario_id,
                "initial_connections": rng.randint(16, 28),
                "background_requests": rng.randint(100, 900),
                "noise_lines": 0 if tier == DifficultyTier.EASY else rng.randint(3, 10),
                "variant": "unseen-topology-noise"
                if suite == SuiteName.HELDOUT
                else "public",
                "untrusted_log": suite == SuiteName.ADVERSARIAL,
            },
            limits={
                "max_steps": 25 if tier == DifficultyTier.EASY else 40,
                "timeout_seconds": 600,
            },
        )
