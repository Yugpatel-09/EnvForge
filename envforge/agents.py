"""Explicit reference baseline and bounded HTTP action adapters."""

import logging
import os
import time
from typing import Literal
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from envforge.protocol.types import Action


class AgentProtocolError(ValueError):
    """An endpoint responded, but did not follow the action protocol."""


class AgentPending(Exception):
    """The native agent is still reasoning; poll within the episode deadline."""


class AgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    adapter: Literal["reference_solver", "http_endpoint"] = "reference_solver"
    endpoint_url: str | None = Field(default=None, max_length=2048)
    token_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,100}$")
    metadata: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_endpoint(self):
        if self.adapter == "http_endpoint":
            validate_endpoint(self.endpoint_url or "")
        elif self.endpoint_url or self.token_env:
            raise ValueError("Reference baseline does not use an endpoint or token")
        return self


def validate_endpoint(url: str) -> None:
    parsed = urlparse(url)
    hosts = {
        h.strip().lower()
        for h in os.environ.get(
            "ENVFORGE_AGENT_HOSTS", "localhost,127.0.0.1,::1"
        ).split(",")
    }
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in hosts
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError(
            "Agent URL must use HTTP(S), have no embedded credentials, and match ENVFORGE_AGENT_HOSTS"
        )
    if parsed.scheme != "https" and parsed.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
        "example-agent",
    }:
        raise ValueError("Remote agents require HTTPS")


def request_agent(config: AgentConfig, payload: dict, timeout: float = 20) -> dict:
    validate_endpoint(config.endpoint_url or "")
    headers = {}
    deadline = time.monotonic() + timeout
    if config.token_env:
        token = os.environ.get(config.token_env)
        if not token:
            raise RuntimeError(
                f"Agent credential variable {config.token_env} is not configured"
            )
        headers["Authorization"] = f"Bearer {token}"
    with (
        httpx.Client(
            timeout=timeout, follow_redirects=False, trust_env=False
        ) as client,
        client.stream(
            "POST", config.endpoint_url or "", json=payload, headers=headers
        ) as response,
    ):
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_bytes():
            if time.monotonic() > deadline:
                raise TimeoutError("Agent response exceeded its time budget")
            body.extend(chunk)
            if len(body) > 65536:
                raise AgentProtocolError("Agent response exceeds 64 KiB")
        try:
            return httpx.Response(200, content=bytes(body)).json()
        except ValueError:
            raise AgentProtocolError("Agent response is not valid JSON") from None


def http_action(
    config: AgentConfig,
    episode_id: str,
    observation: dict,
    tools: list[dict],
    timeout: float = 20,
) -> Action | None:
    data = request_agent(
        config,
        {
            "protocol_version": "1",
            "operation": "act",
            "episode_id": episode_id,
            "observation": observation,
            "tools": tools,
        },
        timeout,
    )
    if isinstance(data, dict) and data == {"pending": True}:
        raise AgentPending
    if not isinstance(data, dict) or "action" not in data:
        raise AgentProtocolError(
            "Agent must return an object containing action (or null)"
        )
    try:
        return (
            Action.model_validate(data["action"])
            if data["action"] is not None
            else None
        )
    except ValueError:
        raise AgentProtocolError(
            "Agent action does not match the documented schema"
        ) from None


def close_agent(config: AgentConfig, episode_id: str) -> None:
    """Release native integration resources without changing the episode result."""
    if config.metadata.get("integration") in {"holmesgpt", "kubectl_ai"}:
        try:
            request_agent(config, {"operation": "close", "episode_id": episode_id}, 10)
        except (httpx.HTTPError, ValueError, RuntimeError, TimeoutError):
            # The bridge also expires abandoned sessions after the episode budget.
            logging.getLogger(__name__).warning(
                "Native agent cleanup failed; bridge expiry will retry"
            )
