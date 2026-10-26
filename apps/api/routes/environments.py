"""Installed catalog and machine-readable tool protocol."""

import json

from fastapi import APIRouter, HTTPException

from apps.api.settings import database_path
from envforge.protocol.types import DifficultyTier, FaultFamily, SuiteName
from envforge.provenance import implementation_digest
from envforge.worlds.sre.environment import SREIncidentResponseEnvironment
from envforge.worlds.sre.scenarios.generator import SREScenarioGenerator
from envforge.worlds.sre.tools.dispatcher import tool_definitions

router = APIRouter(prefix="/v1/environments", tags=["Environments"])


@router.get("/{env_id}/qa")
def get_qa(env_id: str):
    require_environment(env_id)
    path = database_path().parent / "qa-report.json"
    if not path.exists():
        return {
            "status": "NOT_RUN",
            "limitations": [
                "Run the QA command to create a report",
                "Independent model calibration and human SRE review are pending",
            ],
        }
    try:
        report = json.loads(path.read_text())
    except (ValueError, OSError):
        return {
            "status": "INVALID",
            "limitations": ["The QA artifact cannot be read; rerun QA"],
        }
    if not isinstance(report, dict):
        return {"status": "INVALID", "limitations": ["Invalid QA artifact; rerun QA"]}
    if (
        report.get("environment_version") != SREIncidentResponseEnvironment.VERSION
        or report.get("implementation_digest") != implementation_digest()
    ):
        return {
            "status": "STALE",
            "limitations": ["QA report is for another environment version; rerun QA"],
        }
    return {key: value for key, value in report.items() if key != "instances"}


def require_environment(env_id: str):
    if env_id != SREIncidentResponseEnvironment.ENVIRONMENT_ID:
        raise HTTPException(404, "Environment not installed")


@router.get("")
def list_environments():
    return [
        {
            "id": SREIncidentResponseEnvironment.ENVIRONMENT_ID,
            "name": "SRE Incident Response",
            "domain": "sre",
            "version": SREIncidentResponseEnvironment.VERSION,
            "description": "Deterministic Python simulation of checkout, payments, database and cache; typed API actions.",
            "supported_suites": [s.value for s in SuiteName],
            "supported_tiers": [t.value for t in DifficultyTier],
            "distinct_fault_mechanisms": len(FaultFamily),
            "qa_status": "AUTOMATED_QA_AVAILABLE",
            "tools": [tool["name"] for tool in tool_definitions()],
            "execution": "trusted simulation; external HTTP agent; verifier in separate interpreter",
            "limitations": [
                "No shell or browser execution",
                "No live Kubernetes/Postgres workload",
                "Heldout generator is public",
                "Independent model calibration pending",
            ],
        }
    ]


@router.get("/{env_id}/versions")
def get_environment_versions(env_id: str):
    require_environment(env_id)
    return {
        "environment_id": env_id,
        "latest": SREIncidentResponseEnvironment.VERSION,
        "versions": [
            {
                "version": SREIncidentResponseEnvironment.VERSION,
                "scenario_version": SREScenarioGenerator.VERSION,
                "status": "DEVELOPMENT",
            }
        ],
    }


@router.get("/{env_id}/suites")
def get_environment_suites(env_id: str):
    require_environment(env_id)
    descriptions = {
        "smoke": "Connection-pool sanity check",
        "standard": "Balanced ten-family distribution",
        "adversarial": "Ten-family distribution with injected untrusted log instructions",
        "heldout": "Separate seeded parameter distribution (public generator, not a secret benchmark)",
    }
    return {
        "environment_id": env_id,
        "suites": [
            {"id": s.value, "description": descriptions[s.value]} for s in SuiteName
        ],
        "tiers": [
            {
                "id": t.value,
                "description": {
                    "easy": "Single fault",
                    "medium": "Single fault with distracting logs",
                    "hard": "Two faults with distracting logs",
                }[t.value],
            }
            for t in DifficultyTier
        ],
    }


@router.get("/{env_id}/tools")
def get_tools(env_id: str):
    require_environment(env_id)
    return tool_definitions()
