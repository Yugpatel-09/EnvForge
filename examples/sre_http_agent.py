"""Minimal customer-style HTTP adapter for the smoke suite (no private truth)."""

from fastapi import FastAPI

app = FastAPI(title="Example smoke agent")


@app.post("/agent")
def agent(request: dict):
    if request.get("operation") == "health":
        return {"status": "healthy"}
    step = request["observation"]["step"]
    if step == 0:
        tool, arguments = "read_logs", {"service": "checkout-api"}
    elif step == 1:
        tool, arguments = (
            "edit_config",
            {"service": "checkout-api", "key": "DB_POOL_MAX", "value": "50"},
        )
    elif step == 2:
        tool, arguments = (
            "submit_incident_report",
            {
                "root_cause": "Database pool connection leak",
                "primary_fault": "db_pool_exhaustion",
                "component": "checkout-api",
                "mitigation": "Increase pool limit within budget",
                "evidence_action_ids": ["example_0"],
            },
        )
    else:
        return {"action": None}
    return {
        "action": {"action_id": f"example_{step}", "tool": tool, "arguments": arguments}
    }
