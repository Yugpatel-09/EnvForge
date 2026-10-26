"""Environment-based configuration, shared by API and worker."""

import os
from pathlib import Path


def database_path() -> Path:
    return (
        Path(os.environ.get("ENVFORGE_DB_PATH", "data/envforge.sqlite3"))
        .expanduser()
        .resolve()
    )


def api_token() -> str:
    return os.environ.get("ENVFORGE_API_TOKEN", "")


def allowed_origins() -> list[str]:
    return [
        x.strip()
        for x in os.environ.get(
            "ENVFORGE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if x.strip()
    ]
