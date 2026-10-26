"""Small customer client for agent registration and reproducible evaluations."""

import time
from urllib.parse import urlparse

import httpx


def evaluate_http_agent(
    api_url: str,
    agent_url: str,
    token: str = "",
    *,
    suite: str = "smoke",
    tier: str = "easy",
    episodes: int = 10,
    seed: int = 42,
    timeout: float = 600,
) -> dict:
    parsed = urlparse(api_url)
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.scheme not in {"http", "https"}
    ):
        raise ValueError(
            "API URL must be HTTP(S) without credentials, query, or fragment"
        )
    if parsed.scheme != "https" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        raise ValueError("Remote control planes require HTTPS")
    with httpx.Client(
        base_url=api_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"} if token else {},
        timeout=30,
        trust_env=False,
        follow_redirects=False,
    ) as client:

        def post(path: str, payload: dict) -> dict:
            response = client.post(path, json=payload)
            response.raise_for_status()
            return response.json()

        agent = post(
            "/v1/agents",
            {
                "name": "HTTP agent",
                "adapter": "http_endpoint",
                "endpoint_url": agent_url,
            },
        )
        post(f"/v1/agents/{agent['id']}/test-connection", {})
        run = post(
            "/v1/evaluations",
            {
                "agent_id": agent["id"],
                "suite": suite,
                "tier": tier,
                "episodes_count": episodes,
                "base_seed": seed,
            },
        )
        deadline = time.monotonic() + timeout
        try:
            while run["status"] in {"QUEUED", "RUNNING"}:
                if time.monotonic() >= deadline:
                    post(f"/v1/evaluations/{run['id']}/cancel", {})
                    raise TimeoutError("Evaluation timed out; cancellation requested")
                time.sleep(0.25)
                response = client.get(f"/v1/evaluations/{run['id']}")
                response.raise_for_status()
                run = response.json()
        except KeyboardInterrupt:
            post(f"/v1/evaluations/{run['id']}/cancel", {})
            raise
        response = client.get(f"/v1/reports/{run['id']}/export")
        response.raise_for_status()
        return response.json()
