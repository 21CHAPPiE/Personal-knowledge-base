#!/usr/bin/env python3
"""Link events to the events they caused.

Every extracted event already records 【因果】 — what forced it and what it led
to — but as prose about unnamed circumstances, which connects nothing. Reading
neighbouring events together and asking which of them the prose is pointing at
turns that text into edges, so a chain can be followed instead of reconstructed
by rereading.

Causality is local in a narrative: what caused chapter 30 is almost never in
chapter 3. Events are offered to the model in a sliding window of chapters,
which keeps each call small and keeps the model from inventing long-range
links it cannot check.

Usage:
    python scripts/kb_causality.py --project 天幕红尘 --dry-run
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request

CREDS = os.path.expanduser("~/.claude/kb-credentials")
BACKEND_ENV = os.path.expanduser("~/.kb_backend.env")
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
CAUSALITY_TAG = "kind:causality"
WINDOW_CHAPTERS = 4
STEP_CHAPTERS = 3
EVENT_CHARS = 220


def _env(path):
    out = {}
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


_E, _C = _env(BACKEND_ENV), _env(CREDS)


def cfg(key, default=""):
    return os.environ.get(key) or _E.get(key) or _C.get(key) or default


KB = cfg("KB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = cfg("KB_API_TOKEN")


def api(method, path, json_body=None, fields=None):
    headers = {"X-KB-Agent": "kb-causality"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif fields is not None:
        boundary = "----kbcause"
        body = "".join(
            "--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)
            for k, v in fields) + "--%s--\r\n" % boundary
        data = body.encode("utf-8")
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    req = urllib.request.Request(KB + path, data=data, headers=headers, method=method)
    with _opener.open(req, timeout=600) as resp:
        return json.load(resp)


def chat(prompt, max_tokens=2000):
    payload = {"model": cfg("QWEN_MODEL"),
               "messages": [{"role": "user", "content": prompt}],
               "max_tokens": max_tokens, "temperature": 0.2,
               "chat_template_kwargs": {"enable_thinking": False}}  # kb lesson id=21
    headers = {"Content-Type": "application/json"}
    if cfg("QWEN_API_KEY"):
        headers["Authorization"] = "Bearer " + cfg("QWEN_API_KEY")
    req = urllib.request.Request(cfg("QWEN_BASE_URL").rstrip("/") + "/chat/completions",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with _opener.open(req, timeout=600) as resp:
        return json.load(resp)["choices"][0]["message"]["content"].strip()


PROMPT = """下面是按章节顺序排列的一批事件，每条含经过、动机、因果。

找出其中**一件事直接导致另一件事**的配对。注意"直接"：

- 要的是 A 不发生 B 就不会发生（或会变成另一回事）这种关系
- **先后顺序不等于因果**。同一章里接连发生的两件事，多数只是先后，不是因果
- 一件事的【因果】里写的"前因"，如果指的正是这批里的某一条，那就是一条边
- 宁可少给。找不出确凿的因果就输出 []

kind 只能用这三种：
- 导致：A 直接促成了 B 的发生
- 触发：A 是 B 的导火索，B 的规模/性质超出 A 本身
- 受阻：A 使 B 无法进行或被迫改变

严格输出 JSON 数组，不要其他文字：
[{{"from":编号,"to":编号,"kind":"导致|触发|受阻","why":"一句话说清这条因果"}}]

{events}"""

CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def chapter_num(item):
    label = next((t.split(":", 1)[1] for t in item["tags"] if t.startswith("章节:")), "")
    text = label.strip().strip("第章")
    if text.isdigit():
        return int(text)
    total = 0
    for ch in text:
        if ch == "十":
            total = (total or 1) * 10
        elif ch in CN:
            total += CN[ch]
    return total or 0


def narrative(item):
    text = item.get("content") or ""
    return " ".join(re.split(r"【出场人物】", text)[0].split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--since", default="")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project = next((p for p in api("GET", "/api/projects")
                    if p["name"].lower() == args.project.lower()), None)
    if project is None:
        print("找不到项目 %s" % args.project, file=sys.stderr)
        return 1

    items, offset = [], 0
    while True:
        batch = api("GET", "/api/knowledge?project_id=%d&limit=100&offset=%d"
                    % (project["id"], offset))
        items += batch
        if len(batch) < 100:
            break
        offset += 100
    events = [i for i in items if "kind:event" in i["tags"]]
    if args.since:
        events = [i for i in events if i["created_at"] > args.since]
    events.sort(key=chapter_num)
    if not events:
        print("没有事件条目", file=sys.stderr)
        return 1
    last = chapter_num(events[-1])
    print("事件 %d 条，覆盖到第 %d 章" % (len(events), last))

    seen, out, started = set(), [], time.time()
    for start in range(1, last + 1, STEP_CHAPTERS):
        window = [e for e in events if start <= chapter_num(e) < start + WINDOW_CHAPTERS]
        if len(window) < 2:
            continue
        listing = "\n\n".join(
            "#%d [第%d章] %s\n  %s" % (e["id"], chapter_num(e), e["title"],
                                       narrative(e)[:EVENT_CHARS]) for e in window)
        try:
            raw = chat(PROMPT.format(events=listing))
        except Exception as exc:  # noqa: BLE001
            print("  第 %d-%d 章失败: %s" % (start, start + WINDOW_CHAPTERS - 1, exc))
            continue
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            continue
        try:
            data = json.loads(match.group(0))
        except ValueError:
            continue
        valid = {e["id"] for e in window}
        added = 0
        for r in data if isinstance(data, list) else []:
            try:
                src, dst = int(r.get("from")), int(r.get("to"))
            except (TypeError, ValueError):
                continue
            kind = str(r.get("kind", "")).strip()
            if src not in valid or dst not in valid or src == dst:
                continue
            if kind not in ("导致", "触发", "受阻") or (src, dst) in seen:
                continue
            seen.add((src, dst))
            out.append({"from": src, "to": dst, "kind": kind,
                        "why": str(r.get("why", "")).strip()[:140]})
            added += 1
        print("  第 %d-%d 章：%d 条事件 → %d 条因果（累计 %d，%.0f 秒）"
              % (start, start + WINDOW_CHAPTERS - 1, len(window), added, len(out),
                 time.time() - started))

    if args.dry_run:
        by_id = {e["id"]: e for e in events}
        for r in out[:25]:
            print("  #%d %s\n     --%s--> #%d %s\n     %s"
                  % (r["from"], by_id[r["from"]]["title"][:40], r["kind"],
                     r["to"], by_id[r["to"]]["title"][:40], r["why"][:70]))
        return 0

    body = ("这是从《%s》的事件里推断出的因果链，供知识图谱把事件连成边。\n"
            "推断产物，不是原文陈述；语料变化后应重新生成。\n\n```json\n%s\n```\n"
            % (project["name"], json.dumps(out, ensure_ascii=False, indent=1)))
    for old in [i for i in items if CAUSALITY_TAG in i["tags"]]:
        api("DELETE", "/api/knowledge/%d" % old["id"])
    created = api("POST", "/api/knowledge", fields=[
        ("title", "%s · 事件因果链（推断）" % project["name"]), ("content", body),
        ("type", "text"), ("project_id", str(project["id"])), ("source", "causality"),
        ("tags", CAUSALITY_TAG), ("tags", "作品:%s" % project["name"])])
    print("写入 #%d，共 %d 条因果，用时 %.0f 秒"
          % (created["id"], len(out), time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
