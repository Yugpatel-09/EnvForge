"""Authenticated action bridge for per-episode Docker-isolated native agents."""

import argparse
import asyncio
import json
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import uvicorn
from fastapi import FastAPI, Header, HTTPException

from envforge.protocol.types import Action, AgentVisibleObservation
from envforge.worlds.sre.tools.dispatcher import TOOL_MODELS, tool_definitions

PROVIDER_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
)
IMAGES = {
    "holmesgpt": "envforge-holmesgpt:0.45.0",
    "kubectl_ai": "envforge-kubectl-ai:0.0.31",
}


@dataclass
class Session:
    episode_id: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    container: str = field(default_factory=lambda: f"envforge-agent-{uuid.uuid4().hex}")
    created: float = field(default_factory=time.monotonic)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tool_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    available: asyncio.Event = field(default_factory=asyncio.Event)
    action: dict | None = None
    answer: asyncio.Future | None = None
    step: int = 0
    process: asyncio.subprocess.Process | None = None
    closed: bool = False


async def docker(*args: str) -> bytes:
    process = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 15)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError("Docker command failed; check Docker and the agent image")
    return output


async def close(session: Session) -> None:
    session.closed = True
    session.available.set()
    if session.answer and not session.answer.done():
        session.answer.cancel()
    try:
        await docker("rm", "-f", session.container)
    finally:
        if session.process and session.process.returncode is None:
            session.process.kill()
            await session.process.wait()


def create_app(agent: str, model: str, provider: str, port: int) -> FastAPI:
    secret = os.environ.get("ENVFORGE_BRIDGE_TOKEN")
    if not secret:
        raise ValueError("Set ENVFORGE_BRIDGE_TOKEN on the bridge and API worker")
    image = IMAGES[agent]
    resolved_image: str | None = None
    sessions: dict[str, Session] = {}
    registry_lock = asyncio.Lock()

    async def resolve_image() -> str:
        nonlocal resolved_image
        if resolved_image is None:
            resolved_image = (
                (await docker("image", "inspect", "--format", "{{.Id}}", image))
                .decode()
                .strip()
            )
        return resolved_image

    async def discard(session: Session) -> None:
        try:
            await close(session)
        finally:
            sessions.pop(session.episode_id, None)

    async def reap() -> None:
        while True:
            await asyncio.sleep(5)
            for session in list(sessions.values()):
                if time.monotonic() - session.created > 650:
                    try:
                        await discard(session)
                    except (RuntimeError, TimeoutError):
                        pass

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        reaper = asyncio.create_task(reap())
        yield
        reaper.cancel()
        await asyncio.gather(reaper, return_exceptions=True)
        await asyncio.gather(
            *(discard(s) for s in list(sessions.values())), return_exceptions=True
        )

    app = FastAPI(title=f"EnvForge {agent} bridge", lifespan=lifespan)

    def authorize(header: str | None, token: str) -> None:
        if not secrets.compare_digest(header or "", f"Bearer {token}"):
            raise HTTPException(401, "Invalid bridge credential")

    async def start(session: Session, observation: AgentVisibleObservation) -> None:
        # No workspace mounts, kubeconfig, Docker socket or inherited host credentials.
        prompt = (
            "You are responding to an incident in EnvForge's simulated environment. "
            "Use only the envforge MCP tools. Local shell and kubectl do not access this environment. "
            "Investigate, mitigate, then call submit_incident_report with evidence_action_ids "
            "from the action_id values returned by tools. Do not invent evidence.\n"
            + json.dumps(observation.model_dump())
        )
        environment = {
            "ENVFORGE_SESSION_TOKEN": session.token,
            "ENVFORGE_SESSION_URL": f"http://host.docker.internal:{port}/sessions/{session.episode_id}",
            "ENVFORGE_PROMPT": prompt,
            "ENVFORGE_MODEL": model,
            "ENVFORGE_PROVIDER": provider,
        }
        args = [
            "docker",
            "run",
            "--rm",
            "--name",
            session.container,
            "--init",
            "--read-only",
            "--user",
            "10001:10001",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=128",
            "--memory=2g",
            "--cpus=2",
            "--tmpfs",
            "/tmp:rw,nosuid,size=512m,mode=1777",
            "--add-host=host.docker.internal:host-gateway",
        ]
        for key in (*PROVIDER_KEYS, *environment):
            if key in environment or os.environ.get(key):
                args.extend(["--env", key])
        session.process = await asyncio.create_subprocess_exec(
            *args,
            await resolve_image(),
            env={**os.environ, **environment},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

    @app.post("/agent")
    async def agent_request(
        payload: dict, authorization: str | None = Header(default=None)
    ):
        authorize(authorization, secret)
        operation = payload.get("operation")
        if operation == "health":
            return {
                "status": "healthy",
                "integration": agent,
                "model": model,
                "provider": provider,
                "image_id": await resolve_image(),
            }
        episode_id = payload.get("episode_id", "")
        if (
            not isinstance(episode_id, str)
            or not episode_id
            or len(episode_id) > 128
            or any(
                c
                not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for c in episode_id
            )
        ):
            raise HTTPException(400, "Invalid episode ID")
        if operation == "close":
            if session := sessions.get(episode_id):
                await discard(session)
            return {"status": "closed"}
        if operation != "act" or payload.get("protocol_version") != "1":
            raise HTTPException(400, "Unsupported operation or protocol")
        try:
            observation = AgentVisibleObservation.model_validate(
                payload.get("observation")
            )
        except ValueError:
            raise HTTPException(400, "Invalid observation") from None
        async with registry_lock:
            session = sessions.get(episode_id)
            if session is None:
                if len(sessions) >= 4:
                    raise HTTPException(429, "Bridge session capacity reached")
                if observation.step != 0:
                    raise HTTPException(409, "Cannot resume a missing native session")
                session = Session(episode_id)
                sessions[episode_id] = session
                try:
                    await start(session, observation)
                except Exception:
                    await discard(session)
                    raise
        async with session.lock:
            if session.closed:
                raise HTTPException(410, "Session closed")
            if (
                observation.step == session.step + 1
                and session.action
                and session.answer
            ):
                session.answer.set_result(
                    {
                        "action_id": session.action["action_id"],
                        "observation": observation.model_dump(),
                    }
                )
                session.action = None
                session.step = observation.step
                session.available.clear()
            elif observation.step != session.step:
                raise HTTPException(409, "Unexpected observation step")
            if session.action:
                return {"action": session.action}
            try:
                await asyncio.wait_for(session.available.wait(), 1)
            except TimeoutError:
                pass
            if session.action:
                return {"action": session.action}
            if session.process and session.process.returncode is not None:
                if session.process.returncode:
                    raise HTTPException(
                        502,
                        "Native agent exited unsuccessfully; check model configuration",
                    )
                return {"action": None}
            return {"pending": True}

    def get_session(episode_id: str, authorization: str | None) -> Session:
        session = sessions.get(episode_id)
        if session is None or session.closed:
            raise HTTPException(410, "Session expired")
        authorize(authorization, session.token)
        return session

    @app.get("/sessions/{episode_id}/tools")
    async def tools(episode_id: str, authorization: str | None = Header(default=None)):
        get_session(episode_id, authorization)
        return tool_definitions()

    @app.post("/sessions/{episode_id}/call")
    async def call(
        episode_id: str, payload: dict, authorization: str | None = Header(default=None)
    ):
        session = get_session(episode_id, authorization)
        name = payload.get("name")
        if not isinstance(name, str) or name not in TOOL_MODELS:
            raise HTTPException(400, "Unknown tool")
        try:
            arguments = (
                TOOL_MODELS[name]
                .model_validate(payload.get("arguments", {}))
                .model_dump()
            )
        except ValueError:
            raise HTTPException(400, "Invalid tool arguments") from None
        async with session.tool_lock:
            if session.closed:
                raise HTTPException(410, "Session closed")
            session.answer = asyncio.get_running_loop().create_future()
            session.action = Action(
                action_id=uuid.uuid4().hex, tool=name, arguments=arguments
            ).model_dump()
            session.available.set()
            try:
                return await asyncio.wait_for(asyncio.shield(session.answer), 650)
            except TimeoutError:
                raise HTTPException(504, "Episode expired") from None

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=IMAGES)
    parser.add_argument("--model", required=True)
    parser.add_argument("--provider", default="openai", help="kubectl-ai provider name")
    args = parser.parse_args()
    port = 9002 if args.agent == "holmesgpt" else 9003
    uvicorn.run(
        create_app(args.agent, args.model, args.provider, port),
        host="0.0.0.0",
        port=port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
