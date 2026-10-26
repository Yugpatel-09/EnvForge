"""SRE Fault Injectors and Catalog."""

from envforge.worlds.sre.faults.base import BaseFault
from envforge.worlds.sre.faults.fault_catalog import (
    FAULT_REGISTRY,
    BadDeploymentFault,
    CacheSaturationFault,
    DBPoolExhaustionFault,
    DependencyTimeoutFault,
    ExpiredCredentialFault,
    FaultyEnvConfigFault,
    NetworkPartitionFault,
    ResourceLimitsFault,
    ServiceDiscoveryFault,
    WorkerBacklogFault,
)

__all__ = [
    "FAULT_REGISTRY",
    "BadDeploymentFault",
    "BaseFault",
    "CacheSaturationFault",
    "DBPoolExhaustionFault",
    "DependencyTimeoutFault",
    "ExpiredCredentialFault",
    "FaultyEnvConfigFault",
    "NetworkPartitionFault",
    "ResourceLimitsFault",
    "ServiceDiscoveryFault",
    "WorkerBacklogFault",
]
