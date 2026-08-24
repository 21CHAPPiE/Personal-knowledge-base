#!/usr/bin/env python3
"""End-to-end verification against a RUNNING backend (default http://127.0.0.1:8000).

Exercises the real HTTP surface: health, project CRUD, knowledge create with an
attachment upload, Chinese full-text search, project context, and context append.
Zero third-party dependencies. Exit code 0 = all checks passed.

Usage:
    python -m uvicorn app.main:app --port 8000   # terminal 1
    python scripts/e2e_verify.py                 # terminal 2
"""

import io
import json
import os
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib

BASE = os.environ.get("KB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
CHECKS = []


def check(name: str, ok: bool, detail: str = ""):
    CHECKS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))
    return ok


def http(method: str, path: str, json_body=None, data=None, headers=None) -> tuple:
    req = urllib.request.Request(BASE + path, method=method, headers=headers or {})
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except ValueError:
            return exc.code, {"detail": raw.decode("utf-8", "replace")}


def png_bytes() -> bytes:
    """Build a 1x1 red PNG in memory."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\x00\x00"
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def upload_multipart(path: str, fields: list, file_field=None) -> tuple:
    boundary = "----e2eboundary"
    out = io.BytesIO()
    for name, value in fields:
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode("utf-8"))
        out.write(str(value).encode("utf-8") + b"\r\n")
    if file_field is not None:
        name, filename, mime, data = file_field
        out.write(
            (f"--{boundary}\r\n"
             f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
             f"Content-Type: {mime}\r\n\r\n").encode("utf-8")
        )
        out.write(data + b"\r\n")
    out.write(f"--{boundary}--\r\n".encode("utf-8"))
    req = urllib.request.Request(
        BASE + path, data=out.getvalue(), method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def main() -> int:
    print(f"e2e verify against {BASE}")

    # 1. health
    status, body = http("GET", "/health")
    check("health", status == 200 and body.get("status") == "ok" and body.get("db") == "ok",
          json.dumps(body, ensure_ascii=False))

    # 2. create project
    status, project = http("POST", "/api/projects", json_body={"name": "E2E 集成项目", "description": "自动验证"})
    check("create project", status == 201 and project.get("id"), json.dumps(project, ensure_ascii=False))
    pid = project.get("id")

    status, dup = http("POST", "/api/projects", json_body={"name": "e2e 集成项目"})
    check("duplicate project name rejected (case-insensitive)", status == 409, str(dup))

    # 3. text knowledge linked to project (POST /api/knowledge is multipart)
    marker = "集成验证唯一短语 alpha-7"
    code, item = upload_multipart(
        "/api/knowledge",
        [("title", "E2E 文本知识"), ("content", marker), ("type", "text"),
         ("project_id", str(pid)), ("tags", "e2e")],
        None,
    )
    check("create text knowledge", code == 201 and item.get("id"), json.dumps(item, ensure_ascii=False))

    # 4. knowledge with attachment (multipart upload)
    code, shot = upload_multipart(
        "/api/knowledge",
        [("title", "E2E 截图知识"), ("content", "带附件的截图"), ("type", "screenshot"),
         ("project_id", str(pid)), ("source", "e2e")],
        ("file", "shot.png", "image/png", png_bytes()),
    )
    check("create knowledge with attachment", code == 201 and shot.get("id"), json.dumps(shot, ensure_ascii=False))
    atts = shot.get("attachments") or []
    check("attachment registered", len(atts) == 1 and atts[0].get("filename", "").endswith(".png"),
          json.dumps(atts, ensure_ascii=False))
    if atts:
        att = atts[0]
        with urllib.request.urlopen(BASE + att["url"], timeout=30) as resp:
            blob = resp.read()
        check("attachment bytes round-trip", blob == png_bytes())

    # 5. search: just-written Chinese + unique marker
    qs = urllib.parse.urlencode({"q": "alpha-7"})
    status, hits = http("GET", f"/api/search?{qs}")
    check("search finds just-written English marker", status == 200 and any(k["id"] == item["id"] for k in hits),
          json.dumps(hits, ensure_ascii=False)[:200])
    qs = urllib.parse.urlencode({"q": "短语"})
    status, hits = http("GET", f"/api/search?{qs}")
    check("search finds just-written Chinese substring", status == 200 and any(k["id"] == item["id"] for k in hits),
          json.dumps(hits, ensure_ascii=False)[:200])
    qs = urllib.parse.urlencode({"q": "alpha-7", "project_id": pid, "type": "text"})
    status, hits = http("GET", f"/api/search?{qs}")
    check("search with project+type filters", status == 200 and len(hits) == 1 and hits[0]["id"] == item["id"])

    # 6. project context
    status, ctx = http("GET", f"/api/projects/{pid}/context")
    check("project context", status == 200 and ctx.get("statistics", {}).get("total_items", 0) >= 2,
          json.dumps(ctx, ensure_ascii=False)[:200])

    # 7. append context
    status, note = http("POST", f"/api/projects/{pid}/context/append",
                        json_body={"content": "E2E 追加的进展条目", "title": "e2e 进展"})
    check("append project context", status == 201 and note.get("type") == "project_note")

    # 8. stats
    status, stats = http("GET", "/api/stats")
    check("stats endpoint", status == 200 and stats.get("today_count", 0) >= 3,
          json.dumps(stats, ensure_ascii=False))

    failed = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
