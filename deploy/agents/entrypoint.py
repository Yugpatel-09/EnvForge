"""Configure a fresh native CLI process inside an ephemeral agent container."""

import json
import os
import signal
from pathlib import Path

home = Path("/tmp/agent")
home.mkdir(parents=True, exist_ok=True)
os.environ["HOME"] = str(home)
os.environ["XDG_CONFIG_HOME"] = str(home / ".config")
os.environ["KUBECONFIG"] = str(home / "empty-kubeconfig")
Path(os.environ["KUBECONFIG"]).write_text(
    "apiVersion: v1\nkind: Config\nclusters: []\ncontexts: []\nusers: []\n"
)
os.chdir(home)
transport = {
    "command": "uv",
    "args": [
        "run",
        "--no-project",
        "--no-sync",
        "--python",
        "/opt/mcp/bin/python",
        "python",
        "/opt/bridge/mcp_proxy.py",
    ],
}
prompt = os.environ.pop("ENVFORGE_PROMPT")
model = os.environ["ENVFORGE_MODEL"]

if os.environ["ENVFORGE_AGENT"] == "holmesgpt":
    config = home / ".holmes" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        json.dumps(
            {
                "mcp_servers": {
                    "envforge": {
                        "description": "EnvForge simulated incident tools",
                        "config": {"mode": "stdio", **transport},
                        "llm_instructions": "Use these tools exclusively for this incident. Finish with submit_incident_report.",
                    }
                }
            }
        )
    )
    command = [
        "/opt/holmes/bin/holmes",
        "ask",
        "--no-interactive",
        "--bash-always-deny",
        "--max-steps",
        "40",
        "--model",
        model,
        prompt,
    ]
else:
    config = home / ".config" / "kubectl-ai" / "mcp.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"servers": [{"name": "envforge", **transport}]}))
    command = [
        "/usr/local/bin/kubectl-ai",
        "--mcp-client",
        "--quiet",
        "--skip-permissions",
        "--max-iterations",
        "40",
        "--llm-provider",
        os.environ["ENVFORGE_PROVIDER"],
        "--model",
        model,
        prompt,
    ]

signal.alarm(650)
os.execv(command[0], command)
