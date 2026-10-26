"""Trusted internal runtime interface for EnvForge environments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from envforge.protocol.types import (
    Action,
    AgentVisibleObservation,
    CleanupResult,
    ImmutableStateReference,
    Observation,
    StepResult,
    VerifyResult,
)


class TrustedRuntimeEnvironment(ABC):
    """Abstract base class for all EnvForge verified environments.

    Strictly enforces the trusted runtime interface defined in Section 18 of the PRD:
    1. reset -> returns full observation (internal harness extracts private truth).
    2. observe -> returns only agent-visible observation without secret ground truth.
    3. step -> applies an action to the world and returns StepResult.
    4. seal -> freezes the final state and creates an authenticated state snapshot.
    5. verify -> independent verifier grades the immutable state reference against hidden ground truth.
    6. close -> tears down simulation resources.
    """

    @abstractmethod
    def reset(
        self,
        task_id: str,
        seed: int,
        environment_digest: str | None = None,
    ) -> Observation:
        """Reset the environment for a new episode."""
        ...

    @abstractmethod
    def observe(self, episode_id: str) -> AgentVisibleObservation:
        """Produce the current agent-visible observation."""
        ...

    @abstractmethod
    def step(
        self,
        episode_id: str,
        action_id: str,
        action: Action,
    ) -> StepResult:
        """Execute one tool action in the simulation."""
        ...

    @abstractmethod
    def seal(self, episode_id: str) -> ImmutableStateReference:
        """Freeze and seal the final world state snapshot for independent verification."""
        ...

    @abstractmethod
    def verify(
        self,
        immutable_ref: ImmutableStateReference,
        private_task_truth: dict[str, Any],
        verifier_digest: str | None = None,
    ) -> VerifyResult:
        """Run independent verifier probes and checks against the sealed state."""
        ...

    @abstractmethod
    def close(self, episode_id: str) -> CleanupResult:
        """Clean up all episode resources."""
        ...
