"""Base fault definition for SRE simulation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Protocol

from envforge.protocol.types import DifficultyTier, FaultFamily
from envforge.worlds.sre.system import SRESystemState


class FaultFactory(Protocol):
    def __call__(self, tier: DifficultyTier = DifficultyTier.EASY) -> BaseFault: ...


class BaseFault(ABC):
    """Abstract base class for all SRE fault injectors."""

    def __init__(self, family: FaultFamily, tier: DifficultyTier = DifficultyTier.EASY):
        self.family = family
        self.tier = tier

    @abstractmethod
    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        """Inject the fault into the simulation system and return hidden ground truth."""
        ...

    @abstractmethod
    def is_resolved(self, system: SRESystemState) -> bool:
        """Evaluate whether the underlying root cause has been remediated."""
        ...

    @abstractmethod
    def get_canonical_solution_action(self) -> dict[str, Any]:
        """Returns the canonical tool action that resolves this fault."""
        ...
