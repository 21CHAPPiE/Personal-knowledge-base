"""Who touched the knowledge base, when, and what they changed.

An agent that says it recorded a lesson, or read one before acting, should be
checkable against something other than its own account of itself. Every
request lands here as one line, so "did that actually happen" has an answer
that does not depend on trusting the answer.

Two honest limits, stated here rather than discovered later:

The caller names itself. X-KB-Agent and X-KB-Machine are self-reported and
unverified — a client could put anything there. This log proves that a
request happened and what it did; it does not prove who made it. Against the
threat it exists for (an agent overstating what it did) that is enough,
because the agent has to actually issue the request to get a line written.

It is a file, not a table. The schema is CHECK-constrained and this project
has no migration path, so an append-only file next to the database is what
keeps the log out of the knowledge itself — a few thousand request records
per day would bury the few hundred things anyone actually wrote.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import List, Optional

from app.config import get_settings

LOG_NAME = "access.jsonl"
MAX_BYTES = 8 * 1024 * 1024
# Health checks are uptime noise, and the audit endpoint reading its own log
# would make every read of the log a new entry in it.
SKIP_PATHS = ("/health", "/api/audit")


def log_path():
    return get_settings().data_dir / LOG_NAME


def _rotate_if_needed(path):
    try:
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(path.with_suffix(".jsonl.1"))
    except OSError:
        pass


def record(entry: dict) -> None:
    """Append one line. Never raises: an unwritable log must not fail a request
    — losing an audit line is bad, refusing to serve the knowledge base
    because of it is worse."""
    path = log_path()
    try:
        _rotate_if_needed(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read(limit: int = 200, agent: Optional[str] = None,
         writes_only: bool = False) -> List[dict]:
    """Most recent first. Reads the tail rather than the whole file so a long
    history stays cheap to look at."""
    path = log_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-5000:]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if writes_only and entry.get("method") in ("GET", "HEAD", "OPTIONS"):
            continue
        if agent and agent.lower() not in (entry.get("agent") or "").lower():
            continue
        out.append(entry)
        if len(out) >= limit:
            break
    return out


class AuditMiddleware:
    """Pure ASGI, deliberately.

    Starlette's BaseHTTPMiddleware (what @app.middleware("http") builds) can
    resume a request's teardown on a different threadpool thread under load;
    that cost this project a day of 500s once already (kb lesson id=298).
    This layer only reads scope and watches the response start, which the raw
    ASGI interface does without any of that machinery.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").startswith(SKIP_PATHS):
            await self.app(scope, receive, send)
            return

        # Header values are latin-1 per the spec, but clients that put a
        # non-ASCII agent name in one send UTF-8 bytes anyway — decoded as
        # latin-1 those come out as mojibake, which makes the log unreadable
        # exactly for the callers a person named themselves.
        headers = {k.decode("latin-1").lower(): v.decode("utf-8", "replace")
                   for k, v in scope.get("headers", [])}
        started = time.time()
        status = {"code": 0}

        async def watched_send(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, watched_send)
        finally:
            query = scope.get("query_string", b"").decode("latin-1")
            record({
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "method": scope.get("method", ""),
                "path": scope.get("path", ""),
                "query": query[:200],
                "status": status["code"],
                "ms": int((time.time() - started) * 1000),
                # Self-reported; see the module docstring on what that is and
                # is not worth.
                "agent": headers.get("x-kb-agent", "")[:60] or "未声明",
                "machine": headers.get("x-kb-machine", "")[:60] or "",
                "ip": (scope.get("client") or ("", 0))[0],
            })
