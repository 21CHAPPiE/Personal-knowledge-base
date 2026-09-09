#!/usr/bin/env python3
"""Nightly knowledge-base maintenance, run while the local model is idle.

Split by whether a change can alter what a piece of knowledge means:

  applied     — derived data only. A missing embedding or summary is filled in;
                nothing anyone wrote is touched.
  proposed    — anything that merges, retires, or rewrites knowledge. These are
                written as kind:proposal entries and surfaced on the homepage
                for a person to accept or dismiss.

The split exists because an LLM cannot know that a piece of knowledge went out
of date — it has no way to check reality. Let it rewrite entries unsupervised
and the knowledge base quietly becomes wrong, which is worse than stale: the
shell hook now pushes lessons at you unprompted, so a corrupted one misleads
exactly when it is most trusted.

Incremental by default: only entries touched since the last run, plus a full
sweep when --full is passed (intended weekly). Re-scanning 300 unchanged
entries every night buys nothing.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

STATE = os.path.expanduser("~/.kb_maintenance_state.json")
CREDS = os.path.expanduser("~/.claude/kb-credentials")
PROPOSAL_TAG = "kind:proposal"

# BASE is always this machine's own backend (loopback/LAN) — never route it
# through a system proxy. The systemd timer's environment is clean anyway, so
# this only matters when running by hand from an interactive shell that has
# http_proxy/all_proxy set for unrelated reasons, but it's the same fix as
# mcp/kb_mcp_server.py's and costs nothing to apply here too.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
DUPLICATE_THRESHOLD = 0.93   # near-identical text, not merely related
GPU_BUSY_PERCENT = 20


def creds():
    """Credentials file by default; env overrides so this can be pointed at a
    throwaway instance for testing without touching the real knowledge base."""
    base = os.environ.get("KB_BASE_URL", "http://127.0.0.1:8000")
    token = os.environ.get("KB_API_TOKEN", "")
    if os.environ.get("KB_BASE_URL"):
        return base.rstrip("/"), token
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


def api(method, path, json_body=None, fields=None):
    headers = {"Authorization": "Bearer " + TOKEN} if TOKEN else {}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif fields is not None:
        boundary = "----kbmaint"
        body = "".join(
            "--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)
            for k, v in fields) + "--%s--\r\n" % boundary
        data = body.encode("utf-8")
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with _opener.open(req, timeout=300) as resp:
        return json.load(resp)


def gpu_busy():
    """True when something is already using the GPU.

    The nightly window is only free if nobody happens to be working; the 27B
    chat model shares these cards and must not be competed with."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30)
        return any(int(v.strip()) > GPU_BUSY_PERCENT
                   for v in out.stdout.split("\n") if v.strip().isdigit())
    except Exception:  # noqa: BLE001 - no nvidia-smi is not a reason to skip the run
        return False


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state):
    json.dump(state, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def all_items():
    items, offset = [], 0
    while True:
        batch = api("GET", "/api/knowledge?limit=100&offset=%d" % offset)
        items += batch
        if len(batch) < 100:
            return items
        offset += 100


def existing_proposals(items):
    """Signatures of open proposals, so a nightly run does not re-raise what is
    already waiting for review."""
    seen = set()
    for it in items:
        if PROPOSAL_TAG in it["tags"]:
            for t in it["tags"]:
                if t.startswith("about:"):
                    seen.add(t)
    return seen


def propose(kind, title, body, about, dry_run):
    tags = [PROPOSAL_TAG, "proposal:" + kind] + ["about:%s" % a for a in about]
    if dry_run:
        print("    [dry-run] 提议 %s: %s" % (kind, title))
        return
    api("POST", "/api/knowledge", fields=[
        ("title", "待审 · " + title), ("content", body), ("type", "text"),
        ("source", "maintenance")] + [("tags", t) for t in tags])


# --- applied: derived data only -------------------------------------------

def fill_embeddings(log):
    result = api("POST", "/api/lessons/reindex")
    if result.get("embedded"):
        log("  向量补齐: %d 条" % result["embedded"])
    return result.get("embedded", 0)


def fill_summaries(items, log, limit, dry_run):
    """A summary is a derived field, not a claim of its own — generating one
    adds an index into the entry without altering what it says."""
    todo = [i for i in items
            if not (i.get("summary") or "").strip()
            and len((i.get("content") or "").strip()) > 200
            and PROPOSAL_TAG not in i["tags"]][:limit]
    done = 0
    for it in todo:
        if dry_run:
            done += 1
            continue
        try:
            api("POST", "/api/llm/summarize", json_body={"knowledge_id": it["id"], "fallback": False})
            done += 1
        except Exception as exc:  # noqa: BLE001
            log("  摘要失败 id=%s: %s" % (it["id"], exc))
    if done:
        log("  摘要补齐: %d 条%s" % (done, "（dry-run）" if dry_run else ""))
    return done


# --- proposed: anything that changes meaning -------------------------------

def find_duplicates(items, open_props, log, dry_run):
    """Near-identical entries, found by asking the matcher to look for each
    lesson's own signature and seeing who else answers."""
    lessons = [i for i in items if "kind:lesson" in i["tags"]]
    found = 0
    for it in lessons:
        marker = ""
        m = re.search(r"【触发签名】\s*\n(.+)", it.get("content") or "")
        if m:
            marker = m.group(1).strip()
        if not marker:
            continue
        try:
            hits = api("GET", "/api/lessons/match?" + urllib.parse.urlencode(
                {"signature": marker, "limit": 5}))
        except Exception:  # noqa: BLE001
            continue
        others = [h for h in hits if h["id"] != it["id"]]
        for other in others:
            pair = tuple(sorted([it["id"], other["id"]]))
            sig = "about:dup-%d-%d" % pair
            if sig in open_props:
                continue
            open_props.add(sig)
            found += 1
            propose("duplicate",
                    "疑似重复：#%d 与 #%d" % pair,
                    "两条教训的触发签名互相匹配，可能是同一个坑记了两次。\n\n"
                    "#%d %s\n\n#%d %s\n\n"
                    "建议：确认后保留信息更全的一条，把另一条的补充内容并进去再删除。"
                    % (it["id"], it["title"], other["id"], other["title"]),
                    ["dup-%d-%d" % pair], dry_run)
    if found:
        log("  疑似重复: %d 组" % found)
    return found


PATH_RE = re.compile(r"(/(?:home|etc|opt|usr|var)/[\w./\-]+)")


def find_stale_paths(items, open_props, log, dry_run):
    """A lesson naming a path that no longer exists is verifiably suspect —
    the one kind of staleness that can be checked rather than guessed at."""
    found = 0
    for it in items:
        if "kind:lesson" not in it["tags"]:
            continue
        if "设备:" not in " ".join(it["tags"]) and "machine:" not in " ".join(it["tags"]):
            continue  # only claims tied to this machine can be checked here
        missing = sorted({p for p in PATH_RE.findall(it.get("content") or "")
                          if not os.path.exists(p)})
        missing = [p for p in missing if len(p) > 12][:4]
        if not missing:
            continue
        sig = "about:stale-%d" % it["id"]
        if sig in open_props:
            continue
        open_props.add(sig)
        found += 1
        propose("stale",
                "路径已不存在：#%d %s" % (it["id"], it["title"][:30]),
                "这条教训引用的路径在本机已经找不到了：\n%s\n\n"
                "可能是环境变了、目录搬了，或者这条教训确实过时。\n"
                "建议：核实后更新路径，或标注这条只适用于当时的环境。"
                % "\n".join("- " + p for p in missing),
                ["stale-%d" % it["id"]], dry_run)
    if found:
        log("  路径失效: %d 条" % found)
    return found


# Tags too generic to bound a useful batch — grouping by "kind:event" would
# just hand the model the entire project. What's left after excluding these
# (人物:<name> for a book-extraction project, say) is whatever axis the data
# actually varies on, without hardcoding what that axis is for any one project.
GENERIC_TAG_PREFIXES = ("kind:", "作品:", "章节:", "设备:", "cost:", "about:",
                        "proposal:", "scope:", "machine:", "os:", "stack:", "not:")
LOGIC_GROUP_BATCH_MIN = 3
LOGIC_GROUP_BATCH_MAX = 30


def _excerpt(item, length=150):
    text = (item.get("content") or item.get("title") or "").strip()
    text = " ".join(text.split())
    return text[:length]


def _logic_group_batches(items):
    """Item batches worth sending to the model together: small enough for one
    prompt, large enough that a shared cause has more than one item to hide in.

    A whole project under LOGIC_GROUP_BATCH_MAX goes as one batch. A bigger
    project is split by whichever non-generic tags bound a mid-sized cluster —
    for a project with 人物:<name> tags this lands on "this character's
    events", which is exactly the scope a shared motive is likely to sit
    inside; for a project without such tags it contributes no batches, which
    is correct — there's nothing here to bound the prompt by.
    """
    by_project = {}
    for it in items:
        if it.get("project_id") is not None:
            by_project.setdefault(it["project_id"], []).append(it)

    for project_id, project_items in by_project.items():
        if len(project_items) < LOGIC_GROUP_BATCH_MIN:
            continue
        if len(project_items) <= LOGIC_GROUP_BATCH_MAX:
            yield project_id, project_items
            continue
        by_tag = {}
        for it in project_items:
            for tag in it["tags"]:
                if tag.startswith(GENERIC_TAG_PREFIXES):
                    continue
                by_tag.setdefault(tag, []).append(it)
        for tag, tagged_items in by_tag.items():
            if LOGIC_GROUP_BATCH_MIN <= len(tagged_items) <= LOGIC_GROUP_BATCH_MAX:
                yield project_id, tagged_items


def find_logic_groups(items, open_props, log, dry_run):
    """Ask the local model which items share a root cause/motive, not just a
    topic — the "propose don't rewrite" version of schema induction: compare
    several concrete cases at once and surface the shared structure, rather
    than matching one query against one case at a time (that's what
    lesson_service's rerank does; this is the write-time counterpart).
    """
    projects = {}
    found = 0
    for project_id, batch in _logic_group_batches(items):
        context = projects.get(project_id)
        if context is None:
            try:
                context = api("GET", "/api/projects/%d" % project_id)["name"]
            except Exception:  # noqa: BLE001
                context = None
            projects[project_id] = context
        payload = {
            "items": [{"id": it["id"], "title": it["title"], "excerpt": _excerpt(it)}
                     for it in batch],
        }
        if context:
            payload["context"] = context
        try:
            result = api("POST", "/api/llm/logic-groups", json_body=payload)
        except Exception as exc:  # noqa: BLE001
            log("  逻辑分组失败: %s" % exc)
            continue
        by_id = {it["id"]: it for it in batch}
        for group in result.get("groups", []):
            ids = group.get("item_ids") or []
            if len(ids) < 2:
                continue
            key = "about:logic-%s" % "-".join(str(i) for i in sorted(ids))
            if key in open_props:
                continue
            open_props.add(key)
            found += 1
            titles = "\n".join("#%d %s" % (i, by_id[i]["title"]) for i in ids if i in by_id)
            propose("logic-group",
                    "疑似同一底层逻辑：%s" % "、".join("#%d" % i for i in ids),
                    "模型认为下面这几条背后是同一个底层逻辑，而不只是碰巧提到同一个人/同一个场景：\n\n"
                    "%s\n\n【共同逻辑】\n%s\n\n"
                    "建议：确认后可以互相加引用，或者视情况归到同一个主题下。"
                    % (titles, group.get("shared_logic", "")),
                    [key.split(":", 1)[1]], dry_run)
    if found:
        log("  疑似同一逻辑: %d 组" % found)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="全量巡检（默认只看上次之后变动的）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="GPU 忙也照跑")
    ap.add_argument("--summary-limit", type=int, default=20)
    ap.add_argument("--logic-groups", action="store_true",
                    help="额外跑一遍\"哪几条底层逻辑相通\"分析（每次调用都要经过全部符合条件的"
                         "批次调本地模型，比其它检查贵得多；先手动跑几次确认输出质量，"
                         "再决定要不要并入默认的每夜例行）")
    args = ap.parse_args()

    started = time.time()
    lines = []

    def log(msg):
        print(msg, flush=True)
        lines.append(msg)

    log("=== 知识库维护 %s ===" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))

    if gpu_busy() and not args.force:
        log("GPU 正忙，跳过本次（--force 可强制）")
        return 0

    state = load_state()
    items = all_items()
    since = state.get("last_run")
    scope = items if (args.full or not since) else [
        i for i in items if i["updated_at"] > since]
    log("全库 %d 条，本次处理 %d 条%s" % (
        len(items), len(scope), "（全量）" if args.full or not since else "（增量，自 %s）" % since))

    open_props = existing_proposals(items)

    log("[自动执行]")
    fill_embeddings(log)
    fill_summaries(scope, log, args.summary_limit, args.dry_run)

    log("[待审提议]")
    dups = find_duplicates(scope, open_props, log, args.dry_run)
    stale = find_stale_paths(scope, open_props, log, args.dry_run)
    logic = 0
    if args.logic_groups:
        # The whole corpus, not just `scope`: a shared cause has to be found
        # against everything in a project, not only what changed since last
        # run — an old item's motive doesn't stop being relevant just because
        # it wasn't touched today.
        logic = find_logic_groups(items, open_props, log, args.dry_run)
    if not dups and not stale and not logic:
        log("  没有需要人工确认的问题")

    if not args.dry_run:
        state["last_run"] = max([i["updated_at"] for i in items] or
                                [datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
        state["last_summary"] = lines[-8:]
        save_state(state)

    log("用时 %.1f 秒" % (time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
