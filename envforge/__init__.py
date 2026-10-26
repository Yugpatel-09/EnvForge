"""EnvForge: The Proving Ground for AI Agents.

Evaluation-first, RL-ready simulation environments and verified benchmarks for AI agents.
"""

__version__ = "0.2.0"


def load_env(environment_id: str = "sre.incident-response", version: str = __version__):
    from envforge.worlds.sre.environment import SREIncidentResponseEnvironment

    if (
        environment_id != SREIncidentResponseEnvironment.ENVIRONMENT_ID
        or version != __version__
    ):
        raise ValueError("Environment/version is not installed")
    return SREIncidentResponseEnvironment()
