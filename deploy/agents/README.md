# Native agents

EnvForge supports **HolmesGPT 0.45.0** and **kubectl-ai 0.0.31** through their native MCP clients. Each episode starts a fresh Docker container. The agent receives the public incident observation, calls EnvForge tools through MCP, and submits an incident report. EnvForge executes, records, and independently scores those actions.

These integrations evaluate agents against the SRE simulator. They do not provision a real Kubernetes cluster. kagent is not included.

## Setup

Run these commands from the repository root with Docker running:

```sh
docker build -f deploy/agents/Dockerfile.holmesgpt -t envforge-holmesgpt:0.45.0 .
docker build -f deploy/agents/Dockerfile.kubectl-ai -t envforge-kubectl-ai:0.0.31 .
```

Set `ENVFORGE_BRIDGE_TOKEN` to the same randomly generated secret in the bridge, API, and worker environments. Set a model provider key in the bridge environment only: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY`, as required by the selected agent/provider. No keys are stored in registration forms or committed files.

Start each bridge in its own terminal, replacing the model placeholders with model IDs supported by your provider:

```sh
uv run --project apps/api python -m envforge.integrations.bridge --agent holmesgpt --model YOUR_HOLMES_MODEL
uv run --project apps/api python -m envforge.integrations.bridge --agent kubectl_ai --provider openai --model YOUR_KUBECTL_MODEL
```

HolmesGPT uses its native LiteLLM model naming. kubectl-ai uses its native provider and model flags. Both invoke the upstream CLI; EnvForge does not replace the agent's decision loop with scripted decisions.

In the dashboard's **Register an agent** form, select HolmesGPT or kubectl-ai. The form supplies the endpoint and credential variable. Register, select **Test connection**, then launch a small smoke run. Connection testing confirms the bridge and Docker image are available and records the model, provider, and image identity; it does **not** validate model credentials. A real run requires provider access and incurs provider usage.

Default endpoints are `http://127.0.0.1:9002/agent` and `http://127.0.0.1:9003/agent`. Run the API and worker on the host for these URLs. A containerized API cannot reach host services through its own `127.0.0.1`; use an HTTPS reverse proxy and add its exact hostname to `ENVFORGE_AGENT_HOSTS` for that deployment.

## Lifecycle and boundaries

- The worker polls while the native agent reasons, within the existing episode deadline. Pending responses do not consume environment steps.
- Tool arguments use the existing EnvForge schemas. Responses include action IDs for incident-report evidence. Only public observations are forwarded.
- Normal completion, cancellation, and failure close native sessions. The bridge expires abandoned sessions after 650 seconds and allows at most four concurrent sessions.
- Agent containers have no repository mount, kubeconfig, production credentials, or Docker socket. They run as a non-root user with a read-only filesystem, temporary writable storage, resource limits, and dropped capabilities.
- Containers retain outbound networking for model providers and the session bridge. This is process/filesystem isolation, not an outbound network firewall. Upstream agents may expose built-in shell tools; those commands do not operate the EnvForge simulator. Use dedicated model credentials.
- The bridge listens on all host interfaces so containers can reach it. Its control endpoint requires the shared token; tool endpoints require an independent per-session token. Keep the bridge on a trusted host/network.
- Native CLI failures fail the evaluation; they never fall back to the reference oracle. Check provider credentials, model ID, and image availability if a run fails. Restarting a bridge cannot resume an active native session.

The HTTP extension returns `{"pending": true}` while waiting and accepts `{"operation": "close", "episode_id": "..."}` for cleanup. Registrations use `adapter: "http_endpoint"` and `metadata.integration: "holmesgpt"` or `"kubectl_ai"`. Test connection before launching so the run manifest includes runtime identity. The worker rejects a changed runtime identity at run start.

## Upstream projects

- [HolmesGPT](https://github.com/HolmesGPT/holmesgpt) and its [MCP configuration](https://github.com/HolmesGPT/holmesgpt/blob/0.45.0/docs/data-sources/remote-mcp-servers.md).
- [kubectl-ai](https://github.com/GoogleCloudPlatform/kubectl-ai) and its [MCP client](https://github.com/GoogleCloudPlatform/kubectl-ai/blob/v0.0.31/docs/mcp-client.md).
