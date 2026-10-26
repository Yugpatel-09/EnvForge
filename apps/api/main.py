"""Single-workspace control plane with explicit authentication and local defaults."""

import os
import secrets
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.routes import (
    agents,
    comparisons,
    environments,
    episodes,
    evaluations,
    reports,
)
from apps.api.runner import recover_expired_jobs, worker_once
from apps.api.settings import allowed_origins, api_token
from apps.api.storage import init_db


def _worker(stop: threading.Event) -> None:
    while not stop.is_set():
        if not worker_once():
            stop.wait(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    recover_expired_jobs()
    stop = threading.Event()
    if os.environ.get("ENVFORGE_EXTERNAL_WORKER") != "1":
        for _ in range(2):
            threading.Thread(target=_worker, args=(stop,), daemon=True).start()
    yield
    stop.set()


app = FastAPI(title="EnvForge Control Plane", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def access_control(request: Request, call_next):
    if request.url.path.startswith("/v1"):
        # Browser preflights do not carry a bearer token; CORS evaluates their origin.
        if request.method == "OPTIONS":
            return await call_next(request)
        token = api_token()
        if token and not secrets.compare_digest(
            request.headers.get("Authorization", ""), "Bearer " + token
        ):
            return JSONResponse({"detail": "Valid API token required"}, status_code=401)
        if (
            not token
            and request.client
            and request.client.host
            not in {"127.0.0.1", "::1", "localhost", "testclient"}
        ):
            return JSONResponse(
                {"detail": "Configure ENVFORGE_API_TOKEN for remote access"},
                status_code=403,
            )
        if not token and request.url.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        }:
            return JSONResponse(
                {"detail": "Local access requires a loopback host"}, status_code=403
            )
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 262144:
                return JSONResponse(
                    {"detail": "Request body exceeds 256 KiB"}, status_code=413
                )
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


for module in (environments, agents, evaluations, episodes, comparisons, reports):
    app.include_router(module.router)


@app.get("/health")
def health_check():
    init_db()
    return {
        "status": "healthy",
        "service": "envforge-control-plane",
        "version": "0.2.0",
    }


def main() -> None:
    import uvicorn

    uvicorn.run("apps.api.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
