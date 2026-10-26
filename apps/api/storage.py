"""Portable SQLite storage with idempotent schema migrations and durable jobs."""

import sqlite3
import threading
from contextlib import contextmanager

from apps.api.settings import database_path

_migration_lock = threading.Lock()
_initialized: set[str] = set()


def _connect() -> sqlite3.Connection:
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db() -> None:
    key = str(database_path())
    with _migration_lock:
        if key in _initialized:
            return
        conn = _connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:
                conn.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE IF NOT EXISTS agents (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL, adapter TEXT NOT NULL,
                        config_json TEXT NOT NULL, created_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS evaluations (
                        id TEXT PRIMARY KEY, name TEXT NOT NULL, environment_id TEXT NOT NULL,
                        suite TEXT NOT NULL, tier TEXT NOT NULL, agent_id TEXT NOT NULL,
                        status TEXT NOT NULL, total_episodes INTEGER NOT NULL,
                        completed_episodes INTEGER NOT NULL, success_count INTEGER NOT NULL,
                        hard_failures_count INTEGER NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS episodes (
                        id TEXT PRIMARY KEY, evaluation_id TEXT NOT NULL REFERENCES evaluations(id),
                        task_id TEXT NOT NULL, seed INTEGER NOT NULL, status TEXT NOT NULL,
                        success INTEGER NOT NULL, reward REAL NOT NULL, trajectory_json TEXT NOT NULL,
                        verification_json TEXT NOT NULL, created_at REAL NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS episodes_evaluation ON episodes(evaluation_id);
                    CREATE TABLE IF NOT EXISTS audit_events (
                        id INTEGER PRIMARY KEY, event TEXT NOT NULL, resource_id TEXT NOT NULL, created_at REAL NOT NULL
                    );
                """)
                columns = {r[1] for r in conn.execute("PRAGMA table_info(evaluations)")}
                for name, definition in {
                    "manifest_json": "TEXT NOT NULL DEFAULT '{}'",
                    "error": "TEXT",
                    "worker_id": "TEXT",
                    "lease_until": "REAL",
                }.items():
                    if name not in columns:
                        conn.execute(
                            f"ALTER TABLE evaluations ADD COLUMN {name} {definition}"
                        )
                conn.execute("PRAGMA user_version=1")
                conn.execute("""UPDATE evaluations SET status='INFRA_FAILED', error='Run has no worker lease; start a new evaluation'
                                WHERE status='RUNNING' AND lease_until IS NULL""")
        finally:
            conn.close()
        _initialized.add(key)


def get_db_connection() -> sqlite3.Connection:
    init_db()
    return _connect()


@contextmanager
def database():
    conn = get_db_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()
