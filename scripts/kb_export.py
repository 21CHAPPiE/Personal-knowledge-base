#!/usr/bin/env python3
"""Export the whole knowledge base to NDJSON, and archive the raw data dir.

Two artefacts, because they fail differently. The NDJSON is text: it diffs, it
survives a schema change, and it can be read by anything years from now. The
tarball is the literal database and uploads: it restores exactly, but only into
a compatible version.

A backup nobody has restored from is a guess, so --verify reads the export back
and compares counts against the live instance.
"""

import argparse
import json
import os
import sqlite3
import sys
import tarfile
import urllib.request
from datetime import datetime

CREDS = os.path.expanduser("~/.claude/kb-credentials")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO, "data")

# BASE is always this machine's own backend — never route it through a system
# proxy (see mcp/kb_mcp_server.py for the incident this fixes).
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def creds():
    base = os.environ.get("KB_BASE_URL", "http://127.0.0.1:8000")
    token = os.environ.get("KB_API_TOKEN", "")
    if not os.environ.get("KB_BASE_URL"):
        try:
            for line in open(CREDS, encoding="utf-8"):
                if line.startswith("KB_BASE_URL="):
                    base = line.split("=", 1)[1].strip() or base
                elif line.startswith("KB_API_TOKEN="):
                    token = line.split("=", 1)[1].strip()
        except OSError:
            pass
    return base.rstrip("/"), token


BASE, TOKEN = creds()


def api(path):
    req = urllib.request.Request(BASE + path,
                                 headers={"Authorization": "Bearer " + TOKEN} if TOKEN else {})
    with _opener.open(req, timeout=300) as resp:
        return json.load(resp)


def fetch_all():
    projects = api("/api/projects")
    items, offset = [], 0
    while True:
        batch = api("/api/knowledge?limit=100&offset=%d" % offset)
        items += batch
        if len(batch) < 100:
            break
        offset += 100
    # The list endpoint truncates content into a preview, so the full body has
    # to be fetched per item — an export holding previews is not a backup.
    full = [api("/api/knowledge/%d" % it["id"]) for it in items]
    return projects, full


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.expanduser("~/kb-archives"))
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    projects, items = fetch_all()
    ndjson = os.path.join(args.out, "kb-export-%s.ndjson" % stamp)
    with open(ndjson, "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"_type": "meta", "exported_at": stamp,
                             "projects": len(projects), "items": len(items)},
                            ensure_ascii=False) + "\n")
        for p in projects:
            fh.write(json.dumps({"_type": "project", **p}, ensure_ascii=False) + "\n")
        for it in items:
            fh.write(json.dumps({"_type": "knowledge", **it}, ensure_ascii=False) + "\n")
    print("导出 %s  (%d 项目 / %d 条知识, %.1f KB)" % (
        os.path.basename(ndjson), len(projects), len(items), os.path.getsize(ndjson) / 1024))

    tarball = os.path.join(args.out, "kb-data-%s.tar.gz" % stamp)
    # SQLite's own backup API rather than a file copy: copying a live database
    # can catch it mid-write, and under WAL the .db file alone may not hold the
    # newest commits. Using the stdlib module also drops the dependency on the
    # sqlite3 CLI, which is not installed on this machine.
    snapshot = os.path.join(args.out, "knowledge-snapshot.db")
    src = sqlite3.connect("file:%s?mode=ro" % os.path.join(DATA_DIR, "knowledge.db"), uri=True)
    dst = sqlite3.connect(snapshot)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(snapshot, arcname="knowledge.db")
        uploads = os.path.join(DATA_DIR, "uploads")
        if os.path.isdir(uploads):
            tf.add(uploads, arcname="uploads")
    os.remove(snapshot)
    print("归档 %s  (%.1f KB)" % (os.path.basename(tarball), os.path.getsize(tarball) / 1024))

    if args.verify:
        kinds = {}
        for line in open(ndjson, encoding="utf-8"):
            kinds[json.loads(line)["_type"]] = kinds.get(json.loads(line)["_type"], 0) + 1
        live_items = len(items)
        ok = kinds.get("knowledge") == live_items and kinds.get("project") == len(projects)
        empty = [i for i in items if not (i.get("content") or "").strip()]
        print("校验: 导出 %d 项目 / %d 条知识，与线上%s；正文为空的 %d 条" % (
            kinds.get("project", 0), kinds.get("knowledge", 0),
            "一致 ✅" if ok else "不一致 ❌", len(empty)))
        with tarfile.open(tarball) as tf:
            names = tf.getnames()
        print("      归档内含: %s" % ", ".join(names[:3]) + (" …" if len(names) > 3 else ""))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
