#!/usr/bin/env python3
"""Personal Knowledge Base — MCP server (zero third-party dependencies).

Stdio JSON-RPC 2.0 (newline-delimited) implementing the MCP tool protocol
for Claude Code / Codex. All state lives in the backend REST API; this
server is a thin translator so there is a single source of truth.

Usage:
    python kb_mcp_server.py
Environment:
    KB_BASE_URL   backend base URL (default http://127.0.0.1:8000)
    KB_API_TOKEN  bearer token, only needed if the backend has KB_API_TOKEN set

Claude Code registration:
    claude mcp add kb -- python /path/to/mcp/kb_mcp_server.py
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
DEFAULT_PROTOCOL = "2025-03-26"
SERVER_NAME = "kb"
SERVER_VERSION = "0.1.0"

# KB_BASE_URL is always a URL the user configured for their own personal
# backend (loopback or LAN) — there's never a legitimate reason to route it
# through a system HTTP/SOCKS proxy meant for reaching the outside internet.
# Confirmed to fail for real: a machine-wide proxy silently intercepted
# 127.0.0.1 and returned an empty response instead of connecting, with no
# error a caller could act on. Building an opener with an empty ProxyHandler
# makes every request from this process bypass proxy env vars unconditionally
# — correct regardless of whether the user's system proxy happens to be on or
# off, since this client's traffic should never touch it either way.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _base_url() -> str:
    return os.environ.get("KB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _api_token() -> str:
    return os.environ.get("KB_API_TOKEN", "").strip()


def log(msg: str) -> None:
    print(f"[kb-mcp] {msg}", file=sys.stderr, flush=True)


def http_request(method: str, path: str, json_body=None,
                 multipart=None) -> dict:
    """Perform one REST call against the backend. Returns parsed JSON.

    multipart: list of (name, value) string fields plus (name, filename,
    mime, bytes) file fields — encoded by the helper below.
    """
    url = _base_url() + path
    headers = {}
    token = _api_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if multipart is not None:
        body, ctype = _encode_multipart(multipart)
        data = body
        headers["Content-Type"] = ctype
    elif json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _opener.open(req, timeout=30) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except ValueError:
            parsed = {"detail": raw.decode("utf-8", "replace")}
        if exc.code == 200:
            return parsed
        raise MCPHttpError(exc.code, parsed)
    return json.loads(raw.decode("utf-8"))


class MCPHttpError(Exception):
    def __init__(self, status: int, body):
        super().__init__(f"backend HTTP {status}")
        self.status = status
        self.body = body


def _encode_multipart(fields) -> tuple:
    boundary = "----kbmcpboundary"
    out = bytearray()
    for item in fields:
        if len(item) == 2:
            name, value = item
            out += (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            ).encode("utf-8")
            out += str(value).encode("utf-8") + b"\r\n"
        else:
            name, filename, mime, data = item
            out += (
                f"--{boundary}\r\n"
                f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
                f"Content-Type: {mime}\r\n\r\n"
            ).encode("utf-8")
            out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode("utf-8")
    return bytes(out), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------------------
# Tool implementations (each returns a dict; text() wraps it for MCP output)
# ---------------------------------------------------------------------------


def _text(payload) -> dict:
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = str(payload)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _error(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def tool_kb_search(args: dict):
    params = {"q": str(args.get("query") or "")}
    if args.get("project_id") is not None:
        params["project_id"] = args["project_id"]
    if args.get("type"):
        params["type"] = args["type"]
    if args.get("limit") is not None:
        params["limit"] = args["limit"]
    qs = urllib.parse.urlencode(params)
    return _text(http_request("GET", f"/api/search?{qs}"))


def tool_kb_get(args: dict):
    return _text(http_request("GET", f"/api/knowledge/{int(args['id'])}"))


def tool_kb_add(args: dict):
    fields = [
        ("title", str(args.get("title") or "")),
        ("content", str(args.get("content") or "")),
        ("type", str(args.get("type") or "text")),
    ]
    if args.get("project_id") is not None:
        fields.append(("project_id", str(args["project_id"])))
    for tag in args.get("tags") or []:
        fields.append(("tags", str(tag)))
    if args.get("source"):
        fields.append(("source", str(args["source"])))
    else:
        fields.append(("source", "agent"))
    return _text(http_request("POST", "/api/knowledge", multipart=fields))


def tool_kb_recent(args: dict):
    limit = int(args.get("limit") or 10)
    return _text(http_request("GET", f"/api/knowledge/recent?limit={limit}"))


def _resolve_project(ref) -> dict:
    """Resolve a project reference (numeric id string or name) to a project dict."""
    ref = str(ref).strip()
    if ref.isdigit():
        pid = int(ref)
        try:
            return http_request("GET", f"/api/projects/{pid}")
        except MCPHttpError as exc:
            if exc.status == 404:
                raise KeyError(f"project id {pid} not found")
            raise
    projects = http_request("GET", "/api/projects")
    for p in projects:
        if str(p["name"]).casefold() == ref.casefold():
            return p
    raise KeyError(f"project '{ref}' not found")


def tool_project_get_context(args: dict):
    project = _resolve_project(args["project"])
    ctx = http_request("GET", f"/api/projects/{project['id']}/context")
    return _render_context(ctx)


def _render_context(ctx: dict) -> dict:
    project = ctx["project"]
    stats = ctx["statistics"]
    lines = []
    lines.append(f"# {project['name']}")
    lines.append(f"status: {project['status']}")
    if project.get("description"):
        lines.append(f"description: {project['description']}")
    lines.append("")
    lines.append(f"total_items: {stats['total_items']}")
    if stats.get("by_type"):
        lines.append("by_type: " + ", ".join(f"{k}={v}" for k, v in stats["by_type"].items()))
    if stats.get("first_activity"):
        lines.append(f"first_activity: {stats['first_activity']}")
    if stats.get("last_activity"):
        lines.append(f"last_activity: {stats['last_activity']}")
    lines.append("")
    lines.append("recent_items (newest first):")
    if not ctx.get("recent_items"):
        lines.append("(none)")
    for k in ctx["recent_items"]:
        lines.append(f"- [{k['updated_at']}] ({k['type']}) {k['title']}")
        preview = (k.get("content_preview") or "").strip().replace("\n", " ")
        if preview:
            lines.append(f"    {preview[:200]}")
    return {"content": [{"type": "text", "text": "\n".join(lines)}], "isError": False}


def tool_project_append_context(args: dict):
    project = _resolve_project(args["project"])
    body = {"content": str(args["content"]), "source": "agent"}
    if args.get("title"):
        body["title"] = str(args["title"])
    return _text(http_request("POST", f"/api/projects/{project['id']}/context/append", json_body=body))


def tool_kb_lesson_match(args: dict):
    params = {"signature": str(args.get("signature") or "")}
    for key in ("os", "machine", "stack"):
        if args.get(key):
            params[key] = str(args[key])
    if args.get("project"):
        params["project_id"] = _resolve_project(args["project"])["id"]
    if args.get("limit") is not None:
        params["limit"] = args["limit"]
    qs = urllib.parse.urlencode(params)
    return _text(http_request("GET", f"/api/lessons/match?{qs}"))


def _lesson_body(args: dict) -> str:
    return (
        "【触发签名】\n{signature}\n\n"
        "【根因】\n{root_cause}\n\n"
        "【解法】\n{resolution}\n\n"
        "【不适用】\n{not_applicable}\n\n"
        "【验证】\n{verified}"
    ).format(
        signature=str(args.get("signature") or "").strip(),
        root_cause=str(args.get("root_cause") or "").strip(),
        resolution=str(args.get("resolution") or "").strip(),
        not_applicable=str(args.get("not_applicable") or "暂无").strip(),
        verified=str(args.get("verified") or "未单独验证").strip(),
    )


def tool_kb_lesson_add(args: dict):
    scope = str(args.get("scope") or "").strip()
    if scope not in ("machine", "project", "stack", "universal"):
        return _error("scope must be one of: machine, project, stack, universal")

    tags = ["kind:lesson", f"scope:{scope}"]
    if args.get("machine"):
        tags.append("machine:" + str(args["machine"]))
    elif scope == "machine":
        return _error("scope=machine requires a machine tag (run scripts/machine_id.py)")
    if args.get("os"):
        tags.append("os:" + str(args["os"]))
    for stack in args.get("stack") or []:
        tags.append("stack:" + str(stack))
    for blocked in args.get("not_os") or []:
        tags.append("not:os:" + str(blocked))
    # A comma inside a tag value is silently split into two tags server-side.
    tags = [t.replace(",", "/") for t in tags]

    fields = [
        ("title", str(args.get("title") or "")[:200]),
        ("content", _lesson_body(args)),
        ("type", "project_note"),
        ("source", "agent"),
    ]
    if args.get("project"):
        fields.append(("project_id", str(_resolve_project(args["project"])["id"])))
    for tag in tags:
        fields.append(("tags", tag))
    return _text(http_request("POST", "/api/knowledge", multipart=fields))


TOOLS = [
    {
        "name": "kb_search",
        "description": "Full-text search across knowledge items (title/content/tags). Supports Chinese substrings. Optional project_id/type filters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "search text"},
                "project_id": {"type": "integer", "description": "filter to one project"},
                "type": {"type": "string", "enum": ["text", "voice", "screenshot", "project_note"]},
                "limit": {"type": "integer", "description": "max results (default 20)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_get",
        "description": "Get one knowledge item by id, including attachments.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "integer"}},
            "required": ["id"],
        },
    },
    {
        "name": "kb_add",
        "description": "Add a knowledge item. type: text|voice|screenshot|project_note. project_id optional; tags optional list.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "type": {"type": "string", "enum": ["text", "voice", "screenshot", "project_note"]},
                "project_id": {"type": "integer"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "source": {"type": "string"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "kb_recent",
        "description": "List the most recently created knowledge items.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "default 10"}},
        },
    },
    {
        "name": "project_get_context",
        "description": "Get a project's context: overview, statistics, and recent knowledge as compact text. project = name or id.",
        "inputSchema": {
            "type": "object",
            "properties": {"project": {"type": "string", "description": "project name or numeric id"}},
            "required": ["project"],
        },
    },
    {
        "name": "project_append_context",
        "description": "Append a progress note to a project (stored as a project_note knowledge item). project = name or id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "project name or numeric id"},
                "content": {"type": "string"},
                "title": {"type": "string"},
            },
            "required": ["project", "content"],
        },
    },
    {
        "name": "kb_lesson_match",
        "description": (
            "Check whether this situation has been hit before. Pass the verbatim error string, "
            "failing command, or symptom as `signature`. Call this BEFORE doing something in a "
            "category that has burned time before (unfamiliar commands, new service/framework "
            "setup, systemd/network/permission changes) — not before every action."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "signature": {"type": "string", "description": "verbatim error text / command / symptom"},
                "os": {"type": "string", "description": "linux|windows|macos — lessons that contradict it are excluded"},
                "machine": {"type": "string", "description": "output of scripts/machine_id.py, e.g. X99/b3c9c3"},
                "stack": {"type": "string", "description": "comma-separated, e.g. vite,fastapi"},
                "project": {"type": "string", "description": "project name or numeric id"},
                "limit": {"type": "integer", "description": "default 10"},
            },
            "required": ["signature"],
        },
    },
    {
        "name": "kb_lesson_add",
        "description": (
            "Record a lesson so it is not re-learned later. Run kb_lesson_match first: if an "
            "equivalent lesson exists, update that one instead of adding a duplicate. "
            "Pick `scope` by asking what still holds elsewhere: machine (this box only), "
            "project (this repo only), stack (any project on this framework), universal."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "signature": {"type": "string", "description": "verbatim error/command/symptom — copy it exactly, do not paraphrase"},
                "root_cause": {"type": "string", "description": "the mechanism, not the symptom"},
                "resolution": {"type": "string"},
                "scope": {"type": "string", "enum": ["machine", "project", "stack", "universal"]},
                "machine": {"type": "string", "description": "required when scope=machine"},
                "os": {"type": "string"},
                "stack": {"type": "array", "items": {"type": "string"}},
                "not_os": {"type": "array", "items": {"type": "string"}, "description": "OSes this explicitly does NOT apply to"},
                "not_applicable": {"type": "string"},
                "verified": {"type": "string"},
                "project": {"type": "string"},
            },
            "required": ["title", "signature", "root_cause", "resolution", "scope"],
        },
    },
]

TOOL_HANDLERS = {
    "kb_search": tool_kb_search,
    "kb_get": tool_kb_get,
    "kb_add": tool_kb_add,
    "kb_recent": tool_kb_recent,
    "kb_lesson_match": tool_kb_lesson_match,
    "kb_lesson_add": tool_kb_lesson_add,
    "project_get_context": tool_project_get_context,
    "project_append_context": tool_project_append_context,
}


# ---------------------------------------------------------------------------
# JSON-RPC / MCP protocol
# ---------------------------------------------------------------------------


def handle_request(request: dict):
    """Process one JSON-RPC request; returns a response dict or None for
    notifications. Pure enough to unit test without a real backend."""
    method = request.get("method")
    rid = request.get("id")
    params = request.get("params") or {}

    def reply(result):
        if rid is None:
            return None
        return {"jsonrpc": "2.0", "id": rid, "result": result}

    def fail(code, message, data=None):
        err = {"code": code, "message": message}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": rid, "error": err}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in PROTOCOL_VERSIONS else DEFAULT_PROTOCOL
        return reply({
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return reply(None)

    if method == "tools/list":
        return reply({"tools": TOOLS})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return reply(_error(f"unknown tool: {name}"))
        try:
            return reply(handler(args))
        except KeyError as exc:
            return reply(_error(f"missing/invalid argument: {exc}"))
        except MCPHttpError as exc:
            detail = exc.body.get("detail") if isinstance(exc.body, dict) else exc.body
            return reply(_error(f"backend error HTTP {exc.status}: {detail}"))
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            return reply(_error(f"tool {name} failed: {exc}"))

    if method == "ping":
        return reply({})

    if method == "shutdown":
        return reply({})

    if rid is None:
        return None
    return fail(-32601, f"unknown method: {method}")


def main() -> int:
    # Windows console: keep UTF-8 for any stderr output
    # Force UTF-8 on all stdio. On Windows the default pipe encoding is the
    # locale ANSI codec (e.g. cp950), which mis-decodes the UTF-8 JSON-RPC a
    # client such as Claude Code writes and turns CJK text into lone surrogates.
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
    log(f"starting (KB_BASE_URL={_base_url()})")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            resp = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue
        try:
            resp = handle_request(request)
        except Exception as exc:  # noqa: BLE001
            resp = {"jsonrpc": "2.0", "id": request.get("id"),
                    "error": {"code": -32603, "message": f"server error: {exc}"}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
