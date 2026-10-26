"""Implementation of the 10 SRE incident fault families from PRD Page 10."""

from __future__ import annotations

from typing import Any

from envforge.protocol.types import DifficultyTier, FaultFamily
from envforge.worlds.sre.faults.base import BaseFault, FaultFactory
from envforge.worlds.sre.system import SRESystemState


class DBPoolExhaustionFault(BaseFault):
    """DB pool exhaustion: connection leak causes 503s on checkout-api."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.DB_POOL_EXHAUSTION, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        system.db.is_leaking = True
        system.db.leak_rate = 3 if self.tier == DifficultyTier.EASY else 6
        system.db.active_connections = system.db.max_connections  # Immediately saturate
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "checkout-api database connection pool exhausted due to connection leak",
            "required_action": "rollback checkout-api or increase DB_POOL_MAX to at least 50",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        return (
            not system.db.is_leaking
            and system.db.active_connections < system.db.max_connections
        ) or (
            system.db.max_connections >= 50
            and system.db.active_connections < system.db.max_connections
        )

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "edit_config",
            "arguments": {
                "service": "checkout-api",
                "key": "DB_POOL_MAX",
                "value": "50",
            },
        }


class BadDeploymentFault(BaseFault):
    """Bad deployment: release v1.2.1 introduces runtime exceptions."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.BAD_DEPLOYMENT, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        api = system.services["checkout-api"]
        api.current_revision = "v1.2.1-buggy"
        api.revisions.append(
            {
                "revision": "v1.2.1-buggy",
                "deployed_at": system.get_timestamp(),
                "author": "devops@envforge.ai",
            }
        )
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "Faulty deployment v1.2.1-buggy introduced NullPointerExceptions",
            "required_action": "rollback checkout-api to revision v1.2.0",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        return system.services["checkout-api"].current_revision == "v1.2.0"

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "rollback",
            "arguments": {"service": "checkout-api", "target_revision": "v1.2.0"},
        }


class FaultyEnvConfigFault(BaseFault):
    """Faulty env config: DATABASE_URL has invalid hostname."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.FAULTY_ENV_CONFIG, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        api = system.services["checkout-api"]
        api.config["DATABASE_URL"] = "postgres://app:secr3t@wrong-db-host:5432/checkout"
        api.status = "failed"
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "Invalid database host 'wrong-db-host' configured in checkout-api",
            "required_action": "edit_config DATABASE_URL to postgres://app:secr3t@postgres-db:5432/checkout",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        api = system.services["checkout-api"]
        return "postgres-db" in api.config.get("DATABASE_URL", "")

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "edit_config",
            "arguments": {
                "service": "checkout-api",
                "key": "DATABASE_URL",
                "value": "postgres://app:secr3t@postgres-db:5432/checkout",
            },
        }


class DependencyTimeoutFault(BaseFault):
    """Dependency timeout: Upstream payment gateway latency causes request timeouts."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.DEPENDENCY_TIMEOUT, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        api = system.services["checkout-api"]
        api.config["PAYMENT_GATEWAY_TIMEOUT_MS"] = "50"  # Unreasonably tight timeout
        api.status = "degraded"
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "PAYMENT_GATEWAY_TIMEOUT_MS set too low (50ms), causing upstream drops",
            "required_action": "edit_config PAYMENT_GATEWAY_TIMEOUT_MS to at least 1500",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        try:
            return (
                int(
                    system.services["checkout-api"].config.get(
                        "PAYMENT_GATEWAY_TIMEOUT_MS", 0
                    )
                )
                >= 1500
            )
        except ValueError:
            return False

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "edit_config",
            "arguments": {
                "service": "checkout-api",
                "key": "PAYMENT_GATEWAY_TIMEOUT_MS",
                "value": "1500",
            },
        }


class CacheSaturationFault(BaseFault):
    """Cache saturation: Redis memory saturation causing eviction storms."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.CACHE_SATURATION, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        system.cache.is_saturated = True
        system.cache.used_memory_mb = system.cache.max_memory_mb
        system.cache.hit_ratio = 0.45
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "Redis cache saturated causing key eviction and excessive DB query load",
            "required_action": "edit_config REDIS_MAX_MEMORY to 2048 or flush invalid keys",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        return not system.cache.is_saturated or system.cache.hit_ratio >= 0.90

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "edit_config",
            "arguments": {
                "service": "checkout-api",
                "key": "CACHE_POLICY",
                "value": "lru_evict_safe",
            },
        }


class ServiceDiscoveryFault(BaseFault):
    """Service discovery: Auth service resolution failing."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.SERVICE_DISCOVERY, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        api = system.services["checkout-api"]
        api.config["AUTH_SERVICE_URL"] = "http://unreachable-auth.local:8081"
        api.status = "degraded"
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "AUTH_SERVICE_URL pointing to unreachable internal DNS domain",
            "required_action": "edit_config AUTH_SERVICE_URL to http://auth-service.internal:8081",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        return "auth-service.internal" in system.services["checkout-api"].config.get(
            "AUTH_SERVICE_URL", ""
        )

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "edit_config",
            "arguments": {
                "service": "checkout-api",
                "key": "AUTH_SERVICE_URL",
                "value": "http://auth-service.internal:8081",
            },
        }


class WorkerBacklogFault(BaseFault):
    """Worker backlog: Payment worker thread concurrency set to 0."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.WORKER_BACKLOG, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        worker = system.services["payment-worker"]
        worker.config["WORKER_CONCURRENCY"] = "0"
        system.worker_queue.queue_depth = 850
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "payment-worker WORKER_CONCURRENCY misconfigured to 0, causing order queue accumulation",
            "required_action": "edit_config WORKER_CONCURRENCY on payment-worker to at least 4",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        try:
            return (
                int(
                    system.services["payment-worker"].config.get(
                        "WORKER_CONCURRENCY", 0
                    )
                )
                >= 4
            )
        except ValueError:
            return False

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "edit_config",
            "arguments": {
                "service": "payment-worker",
                "key": "WORKER_CONCURRENCY",
                "value": "8",
            },
        }


class ResourceLimitsFault(BaseFault):
    """Resource limits: Pod CPU/memory throttled below minimum operational threshold."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.RESOURCE_LIMITS, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        api = system.services["checkout-api"]
        api.config["POD_MEMORY_LIMIT_MB"] = "64"  # Triggers OOM
        api.status = "failed"
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "POD_MEMORY_LIMIT_MB set to 64MB which causes OOMKill on start",
            "required_action": "edit_config POD_MEMORY_LIMIT_MB to 512 or higher",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        try:
            return (
                int(
                    system.services["checkout-api"].config.get("POD_MEMORY_LIMIT_MB", 0)
                )
                >= 512
            )
        except ValueError:
            return False

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "edit_config",
            "arguments": {
                "service": "checkout-api",
                "key": "POD_MEMORY_LIMIT_MB",
                "value": "512",
            },
        }


class ExpiredCredentialFault(BaseFault):
    """Expired credential: DB user password expired."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.EXPIRED_CREDENTIAL, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        api = system.services["checkout-api"]
        api.config["DATABASE_URL"] = (
            "postgres://app:expired_pass@postgres-db:5432/checkout"
        )
        api.status = "degraded"
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "Database authentication failure due to expired credential token",
            "required_action": "rotate password and edit_config DATABASE_URL with valid credentials",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        return "secr3t" in system.services["checkout-api"].config.get(
            "DATABASE_URL", ""
        )

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "edit_config",
            "arguments": {
                "service": "checkout-api",
                "key": "DATABASE_URL",
                "value": "postgres://app:secr3t@postgres-db:5432/checkout",
            },
        }


class NetworkPartitionFault(BaseFault):
    """Network partition: worker unable to route to postgres-db."""

    def __init__(self, tier: DifficultyTier = DifficultyTier.EASY):
        super().__init__(FaultFamily.NETWORK_PARTITION, tier)

    def inject(self, system: SRESystemState, seed: int) -> dict[str, Any]:
        worker = system.services["payment-worker"]
        worker.config["SUBNET_ROUTE"] = "isolated_vlan"
        worker.status = "degraded"
        system.advance_tick()
        return {
            "family": self.family.value,
            "root_cause": "Subnet route misconfigured to isolated_vlan blocking worker DB traffic",
            "required_action": "edit_config SUBNET_ROUTE to default_vpc",
            "tier": self.tier.value,
        }

    def is_resolved(self, system: SRESystemState) -> bool:
        return (
            system.services["payment-worker"].config.get("SUBNET_ROUTE", "default_vpc")
            == "default_vpc"
        )

    def get_canonical_solution_action(self) -> dict[str, Any]:
        return {
            "tool": "edit_config",
            "arguments": {
                "service": "payment-worker",
                "key": "SUBNET_ROUTE",
                "value": "default_vpc",
            },
        }


FAULT_REGISTRY: dict[FaultFamily, FaultFactory] = {
    FaultFamily.DB_POOL_EXHAUSTION: DBPoolExhaustionFault,
    FaultFamily.BAD_DEPLOYMENT: BadDeploymentFault,
    FaultFamily.FAULTY_ENV_CONFIG: FaultyEnvConfigFault,
    FaultFamily.DEPENDENCY_TIMEOUT: DependencyTimeoutFault,
    FaultFamily.CACHE_SATURATION: CacheSaturationFault,
    FaultFamily.SERVICE_DISCOVERY: ServiceDiscoveryFault,
    FaultFamily.WORKER_BACKLOG: WorkerBacklogFault,
    FaultFamily.RESOURCE_LIMITS: ResourceLimitsFault,
    FaultFamily.EXPIRED_CREDENTIAL: ExpiredCredentialFault,
    FaultFamily.NETWORK_PARTITION: NetworkPartitionFault,
}
