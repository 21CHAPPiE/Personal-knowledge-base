#!/usr/bin/env python3
"""Name the relationship between two people, from the events they share.

Co-occurrence is not a relationship. "These two appear in 43 of the same
scenes" is the only thing the graph could say before this, which draws a
thick line and leaves the reader to guess whether it means creditor,
accomplice or adversary. Reading the events they share and naming what holds
them together is what makes an edge worth drawing.

The result is written as one derived item rather than scattered across the
people it describes: it is inferred, it will be regenerated when the corpus
changes, and keeping it in a single place means it can be replaced or thrown
away without touching anything anyone wrote.

Usage:
    python scripts/kb_relations.py --project 天幕红尘 --min-shared 2
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

CREDS = os.path.expanduser("~/.claude/kb-credentials")
BACKEND_ENV = os.path.expanduser("~/.kb_backend.env")
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
RELATIONS_TAG = "kind:relations"
# Each pair now carries full event bodies rather than five titles, so the
# batch shrinks to keep a call inside the model's context.
BATCH = 3
EVENTS_PER_PAIR = 10
EVENT_CHARS = 240


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
    headers = {"X-KB-Agent": "kb-relations"}
    if TOKEN:
        headers["Authorization"] = "Bearer " + TOKEN
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif fields is not None:
        boundary = "----kbrel"
        body = "".join(
            "--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)
            for k, v in fields) + "--%s--\r\n" % boundary
        data = body.encode("utf-8")
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    req = urllib.request.Request(KB + path, data=data, headers=headers, method=method)
    with _opener.open(req, timeout=600) as resp:
        return json.load(resp)


def chat(prompt, max_tokens=2000):
    payload = {
        "model": cfg("QWEN_MODEL"),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": False},  # kb lesson id=21
    }
    headers = {"Content-Type": "application/json"}
    if cfg("QWEN_API_KEY"):
        headers["Authorization"] = "Bearer " + cfg("QWEN_API_KEY")
    req = urllib.request.Request(cfg("QWEN_BASE_URL").rstrip("/") + "/chat/completions",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    with _opener.open(req, timeout=600) as resp:
        return json.load(resp)["choices"][0]["message"]["content"].strip()


PROMPT = """下面每一组是两个人物，以及他们**确实发生了互动**的全部事件（按章节先后排列，含动机与利害）。

请判断每组两人之间的关系。三条要求：

**一、必须解释大多数事件，不能拿一件事当整段关系的标签。**
如果十件事里九件是债务往来、一件涉及情感，那关系是债务往来，不是情感。
问自己：我给的这个标签，能不能解释下面列出的多数事件？不能就换一个。

**二、关系会变，变了就写出来。**
按章节顺序看，如果两人的关系在过程中发生了实质变化（从对立到默契、从合作到反目），
kind 写**贯穿始终的那层关系**或**最终稳定下来的关系**，arc 写清它怎么变的。
没有实质变化就把 arc 留空。

**三、拿不准就说拿不准**，kind 写"关联不明"，不要硬编。

字段：
- kind: 2-6 字，如 债权人／合伙人／利用与被利用／上下级／对手／同僚
- directed: 是否有方向。"债权人""利用"有方向，"合伙人""同僚"对等
- from/to: directed 为 true 时写清方向（from 是主动方/债权方/利用方）
- arc: 关系如何演变，一句话；没变化就空字符串
- why: 判断依据，一句话，要点出是哪几件事支撑的

严格输出 JSON 数组，不要其他文字：
[{{"a":"甲","b":"乙","kind":"...","directed":true,"from":"甲","to":"乙","arc":"","why":"..."}}]

{pairs}"""


def narrative(item):
    """The event as told, without the cast list.

    出场人物 names everyone present, so both people are in it by construction —
    testing against it would say every co-tagged pair interacts, which is the
    thing that has to be ruled out.
    """
    text = item.get("content") or ""
    return re.split(r"【出场人物】", text)[0]


def interacts(item, a, b):
    """Both people actually appear in what happened, not just in the cast.

    Being tagged on the same event means being in the same room; a
    relationship needs them to do something to each other. Before this filter,
    a pair's evidence included events like "戴梦岩要求调查叶子农背景" where the
    second person is discussed rather than present — and a relationship
    inferred from those is inferred from nothing.
    """
    body = narrative(item)
    return a in body and b in body


CN = {"一":1,"二":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}


def chapter_num(label):
    """第五十一章 -> 51, for putting a pair's events in story order."""
    text = label.strip().strip("第章")
    if text.isdigit():
        return int(text)
    total = 0
    for ch in text:
        if ch == "十":
            total = (total or 1) * 10
        elif ch in CN:
            total += CN[ch]
    return total or 999


def chapter_of(item):
    return next((t.split(":", 1)[1] for t in item["tags"] if t.startswith("章节:")), "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--min-shared", type=int, default=2, help="共现至少多少次才抽")
    ap.add_argument("--since", default="", help="只用这个时间之后创建的条目")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    project = next((p for p in api("GET", "/api/projects")
                    if p["name"].lower() == args.project.lower()), None)
    if project is None:
        print("找不到项目 %s" % args.project, file=sys.stderr)
        return 1

    items, offset = [], 0
    while True:
        batch = api("GET", "/api/knowledge?project_id=%d&limit=100&offset=%d" % (project["id"], offset))
        items += batch
        if len(batch) < 100:
            break
        offset += 100
    if args.since:
        items = [i for i in items if i["created_at"] > args.since]

    shared = defaultdict(list)
    tagged_only = 0
    for it in items:
        people = sorted({t.split(":", 1)[1] for t in it["tags"] if t.startswith("人物:")})
        for i in range(len(people)):
            for j in range(i + 1, len(people)):
                if interacts(it, people[i], people[j]):
                    shared[(people[i], people[j])].append(it)
                else:
                    tagged_only += 1
    pairs = [(k, v) for k, v in shared.items() if len(v) >= args.min_shared]
    pairs.sort(key=lambda kv: -len(kv[1]))
    print("条目 %d 条；丢弃「同时被标注但正文里没有互动」的组合 %d 处；达标人物对 %d 组"
          % (len(items), tagged_only, len(pairs)))

    out, started = [], time.time()
    for start in range(0, len(pairs), BATCH):
        chunk = pairs[start:start + BATCH]
        blocks = []
        for (a, b), evs in chunk:
            # In chapter order and with the body, not just titles: judging a
            # relationship from five truncated headlines was how the first
            # version decided a widow chasing a debt was a love interest.
            ordered = sorted(evs, key=lambda e: chapter_num(chapter_of(e)))[:EVENTS_PER_PAIR]
            lines = "\n".join(
                "  [%s] %s\n      %s" % (chapter_of(e), e["title"],
                                         " ".join(narrative(e).split())[:EVENT_CHARS])
                for e in ordered)
            blocks.append("【%s 与 %s】互动事件 %d 件%s\n%s"
                          % (a, b, len(evs),
                             "（下列为其中最早的 %d 件）" % EVENTS_PER_PAIR
                             if len(evs) > EVENTS_PER_PAIR else "", lines))
        try:
            raw = chat(PROMPT.format(pairs="\n\n".join(blocks)))
        except Exception as exc:  # noqa: BLE001
            print("  批次失败: %s" % exc)
            continue
        match = re.search(r"\[.*\]", raw, re.S)
        if not match:
            continue
        try:
            data = json.loads(match.group(0))
        except ValueError:
            continue
        valid = {(a, b) for (a, b), _ in chunk}
        for r in data if isinstance(data, list) else []:
            key = tuple(sorted([str(r.get("a", "")).strip(), str(r.get("b", "")).strip()]))
            kind = str(r.get("kind", "")).strip()
            if key not in valid or not kind or kind == "关联不明":
                continue
            out.append({
                "a": key[0], "b": key[1], "kind": kind[:12],
                "directed": bool(r.get("directed")),
                "from": str(r.get("from", "")).strip(),
                "to": str(r.get("to", "")).strip(),
                "arc": str(r.get("arc", "")).strip()[:140],
                "why": str(r.get("why", "")).strip()[:140],
                "shared": len(shared[key]),
            })
        print("  %d/%d 组已处理，累计 %d 条关系 (%.0f 秒)"
              % (min(start + BATCH, len(pairs)), len(pairs), len(out), time.time() - started))

    if args.dry_run:
        for r in out[:20]:
            arrow = "→" if r["directed"] else "—"
            print("  %s %s %s  [%s] (%d件) %s" % (r["from"] or r["a"], arrow,
                  r["to"] or r["b"], r["kind"], r["shared"], r["why"][:56]))
            if r["arc"]:
                print("        演变：%s" % r["arc"][:70])
        return 0

    body = ("这是从《%s》的事件里推断出的人物关系，供知识图谱渲染有类型的边。\n"
            "推断产物，不是原文陈述；语料变化后应重新生成。\n\n```json\n%s\n```\n"
            % (project["name"], json.dumps(out, ensure_ascii=False, indent=1)))
    existing = [i for i in items if RELATIONS_TAG in i["tags"]]
    for old in existing:
        api("DELETE", "/api/knowledge/%d" % old["id"])
    created = api("POST", "/api/knowledge", fields=[
        ("title", "%s · 人物关系（推断）" % project["name"]), ("content", body),
        ("type", "text"), ("project_id", str(project["id"])), ("source", "relations"),
        ("tags", RELATIONS_TAG), ("tags", "作品:%s" % project["name"])])
    print("写入 #%d，共 %d 条关系，用时 %.0f 秒"
          % (created["id"], len(out), time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
