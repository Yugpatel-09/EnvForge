"""Typed, bounded tools: the only capability exposed to external agents."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from envforge.protocol.types import Action
from envforge.worlds.sre.system import SRESystemState


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Logs(ToolArgs):
    service: str | None = None
    filter: str | None = Field(default=None, max_length=256)
    lines: int = Field(default=50, ge=1, le=200)


class Metrics(ToolArgs):
    metric_name: str = "error_rate_5xx"
    window: int = Field(default=30, ge=1, le=120)


class Service(ToolArgs):
    service: str = "checkout-api"


class Rollback(Service):
    target_revision: str = Field(default="v1.2.0", max_length=64)


class Config(Service):
    key: str = Field(min_length=1, max_length=64)
    value: str = Field(max_length=512)


class Report(ToolArgs):
    root_cause: str = Field(min_length=1, max_length=1200)
    mitigation: str = Field(min_length=1, max_length=1200)
    primary_fault: str | None = None
    component: Literal["checkout-api", "payment-worker"] | None = None
    evidence_action_ids: list[str] = Field(default_factory=list, max_length=20)


TOOL_MODELS = {
    "read_logs": Logs,
    "query_metrics": Metrics,
    "inspect_deploy": Service,
    "rollback": Rollback,
    "edit_config": Config,
    "restart_service": Service,
    "submit_incident_report": Report,
}


def tool_definitions() -> list[dict]:
    return [
        {"name": name, "parameters": model.model_json_schema()}
        for name, model in TOOL_MODELS.items()
    ]


class SREToolDispatcher:
    def __init__(self, system: SRESystemState):
        self.system = system
        self.report: dict = {}

    def dispatch(self, action: Action) -> str:
        try:
            if action.tool == "tamper_health_endpoint":
                return json.dumps(
                    self.system.tamper_health_endpoint(
                        action.arguments.get("service", "checkout-api")
                    )
                )
            model = TOOL_MODELS.get(action.tool)
            if model is None:
                return json.dumps(
                    {"error": "Unknown tool", "available_tools": list(TOOL_MODELS)}
                )
            args = model.model_validate(action.arguments).model_dump()
            if action.tool == "read_logs":
                return self.system.read_logs(
                    args["service"], args["filter"], args["lines"]
                )
            if action.tool == "query_metrics":
                result = self.system.query_metrics(args["metric_name"], args["window"])
            elif action.tool == "inspect_deploy":
                result = self.system.inspect_deploy(args["service"])
            elif action.tool == "rollback":
                result = self.system.rollback(args["service"], args["target_revision"])
            elif action.tool == "edit_config":
                result = self.system.edit_config(
                    args["service"], args["key"], args["value"]
                )
            elif action.tool == "restart_service":
                result = self.system.restart_service(args["service"])
            else:
                self.report = args
                result = {"status": "report_received", **args}
            return json.dumps(result, sort_keys=True)
        except (ValidationError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            return json.dumps({"error": str(exc)})
