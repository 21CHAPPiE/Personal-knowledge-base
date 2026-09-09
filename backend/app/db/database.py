"""SQLite connection management and schema initialization."""

import sqlite3
from pathlib import Path
from typing import Iterator

from fastapi import Depends

from app.config import get_settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection() -> sqlite3.Connection:
    settings = get_settings()
    # check_same_thread=False: the FastAPI dependency that closes this connection
    # (get_db's finally block) can run on a different threadpool thread than the
    # one that opened it when @app.middleware("http") is in play (a known
    # Starlette BaseHTTPMiddleware quirk under concurrent load). The connection
    # is still only ever used by one request at a time, never shared across
    # concurrent requests, so this doesn't introduce real thread-safety risk.
    conn = sqlite3.connect(str(settings.db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create data directories and apply the schema (idempotent)."""
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    conn = get_connection()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def get_db() -> Iterator[sqlite3.Connection]:
    """Per-request DB connection (FastAPI dependency)."""
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def require_db_conn():
    return Depends(get_db)
