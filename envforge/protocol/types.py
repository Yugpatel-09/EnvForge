"""Core protocol types for EnvForge runtime, agents, and verifiers."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EpisodeState(str, Enum):
    QUEUED = "QUEUED"
    PROVISIONING = "PROVISIONING"
    RUNNING = "RUNNING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    INFRA_FAILED = "INFRA_FAILED"
    CANCELLED = "CANCELLED"


class DifficultyTier(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class SuiteName(str, Enum):
    SMOKE = "smoke"
    STANDARD = "standard"
    ADVERSARIAL = "adversarial"
    HELDOUT = "heldout"


class FaultFamily(str, Enum):
    DB_POOL_EXHAUSTION = "db_pool_exhaustion"
    BAD_DEPLOYMENT = "bad_deployment"
    FAULTY_ENV_CONFIG = "faulty_env_config"
    SERVICE_DISCOVERY = "service_discovery"
    DEPENDENCY_TIMEOUT = "dependency_timeout"
    CACHE_SATURATION = "cache_saturation"
    WORKER_BACKLOG = "worker_backlog"
    RESOURCE_LIMITS = "resource_limits"
    EXPIRED_CREDENTIAL = "expired_credential"
    NETWORK_PARTITION = "network_partition"


class Action(BaseModel):
    """An action submitted by an agent."""

    model_config = ConfigDict(extra="forbid")

    action_id: str = Field(
        min_length=1, max_length=128, description="Idempotent action ID"
    )
    tool: str = Field(min_length=1, max_length=64, description="Tool name")
    arguments: dict[str, Any] = Field(
        default_factory=dict, description="Arguments for the tool"
    )


class AgentVisibleObservation(BaseModel):
    """Observation exposed to the agent. Guaranteed secret-free."""

    step: int = Field(default=0, description="Current episode step")
    prompt: str = Field(default="", description="Natural language goal or task prompt")
    tool_output: str | None = Field(
        default=None, description="Output of the last tool call"
    )
    status_summary: str = Field(
        default="operational", description="High-level public status indication"
    )
    elapsed_seconds: float = Field(
        default=0.0, description="Elapsed simulation time in seconds"
    )


class Observation(AgentVisibleObservation):
    """Full internal world observation including private simulation state."""

    hidden_truth: dict[str, Any] = Field(
        default_factory=dict, description="Private ground truth"
    )
    system_state: dict[str, Any] = Field(
        default_factory=dict, description="Detailed mock system state"
    )


class StepResult(BaseModel):
    """Result of taking a step in the environment."""

    observation: AgentVisibleObservation
    done: bool = False
    truncated: bool = False
    info: dict[str, Any] = Field(default_factory=dict)


class ImmutableStateReference(BaseModel):
    """Reference to sealed post-episode state snapshot used for independent verification."""

    episode_id: str
    state_digest: str
    final_state_snapshot: dict[str, Any]
    event_log: list[dict[str, Any]]
    action_history: list[dict[str, Any]]
    environment_version: str = "0.2.0"
    task_digest: str = ""


class VerifyResult(BaseModel):
    """Formal verification output produced by an isolated verifier."""

    episode_id: str
    success: bool
    reward: float
    reason: str = ""
    checks: dict[str, bool]
    hard_failures: list[str] = Field(default_factory=list)
    verifier_version: str
    evidence_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CleanupResult(BaseModel):
    """Result of tearing down or resetting an episode."""

    episode_id: str
    success: bool
    cleaned_resources: list[str] = Field(default_factory=list)
