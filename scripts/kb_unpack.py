#!/usr/bin/env python3
"""Break one long knowledge item into the claims it actually makes.

A pasted lecture transcript or meeting note sits in the base as a single
blob: searchable as a whole, but nothing inside it can be matched, linked or
argued with. This pulls out one unit per claim — what is asserted, what it is
asserted against, and which examples were used to carry it — because a claim
with its supporting examples attached is the smallest thing that can later be
compared against a claim made somewhere else.

Deliberately not "summarise": the units are extracted, the original is left
untouched and stays the source of record. Each unit carries 来源:<id> back to
it, so nothing here is a replacement for reading the thing itself.

Usage:
    python scripts/kb_unpack.py 4 --project 智慧流域课程 --dry-run
    python scripts/kb_unpack.py 4 --project 智慧流域课程
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


def _read_env(path):
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


_ENV = _read_env(BACKEND_ENV)
_CREDS = _read_env(CREDS)


def cfg(key, default=""):
    return os.environ.get(key) or _ENV.get(key) or _CREDS.get(key) or default


KB = cfg("KB_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = cfg("KB_API_TOKEN")


def api(method, path, json_body=None, fields=None):
    headers = {"Authorization": "Bearer " + TOKEN} if TOKEN else {}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif fields is not None:
        boundary = "----kbunpack"
        body = "".join(
            "--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)
            for k, v in fields) + "--%s--\r\n" % boundary
        data = body.encode("utf-8")
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    req = urllib.request.Request(KB + path, data=data, headers=headers, method=method)
    with _opener.open(req, timeout=600) as resp:
        return json.load(resp)


def chat(prompt, max_tokens=3000):
    payload = {
        "model": cfg("QWEN_MODEL"),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        # Lesson id=21: a reasoning model spends the whole budget thinking and
        # returns empty content on extraction-shaped work.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Content-Type": "application/json"}
    if cfg("QWEN_API_KEY"):
        headers["Authorization"] = "Bearer " + cfg("QWEN_API_KEY")
    req = urllib.request.Request(
        cfg("QWEN_BASE_URL").rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with _opener.open(req, timeout=600) as resp:
        return json.load(resp)["choices"][0]["message"]["content"].strip()


PROMPT = """下面是一段{kind}的实录（口述转文字，可能有识别错误和口语重复）。

请抽出其中作者**真正主张的观点**，一条一个单元。注意这是口述，一个观点常常被反复绕、
换几个说法讲同一件事——那算一条，不要拆成三条。

每条输出这些字段：
- title: 这条主张是什么，一句话，15-30 字，完整通顺
- claim: 主张本身，2-4 句，用作者的逻辑说，不要替他拔高也不要替他补充
- against: 他在反驳/纠正什么。很多主张是冲着一个常见误解去的，写清那个误解是什么；没有就空字符串
- examples: 他用来支撑这条主张的例子，字符串数组，照他举的写，别自己编
- method: 这条主张里可操作的做法（要求人具体做什么/不做什么）；纯理念没给做法就空字符串
- terms: 这条里出现的关键概念，字符串数组

只抽真正的主张，别把过场话、点名、闲聊、组织事务当成主张。
遇到明显的转写错误（同音字之类）按上下文理解，但不要改写他的意思。

严格输出 JSON 数组，不要输出任何其他文字：
[{{"title":"...","claim":"...","against":"...","examples":["..."],"method":"...","terms":["..."]}}]

实录：
{body}"""


def parse_units(raw):
    match = re.search(r"\[.*\]", raw, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    out = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        claim = str(item.get("claim") or "").strip()
        if not title or not claim:
            continue
        as_list = lambda key: [str(x).strip() for x in (item.get(key) or []) if str(x).strip()]
        out.append({
            "title": title[:120], "claim": claim,
            "against": str(item.get("against") or "").strip(),
            "examples": as_list("examples"),
            "method": str(item.get("method") or "").strip(),
            "terms": as_list("terms"),
        })
    return out


def body_of(unit):
    blocks = [("主张", unit["claim"]), ("针对的误解", unit["against"]),
              ("例子", "\n".join("- " + e for e in unit["examples"])),
              ("可操作", unit["method"])]
    return "\n\n".join("【%s】\n%s" % (label, text) for label, text in blocks if text)


def chunks(text, size=4000, overlap=300):
    """Overlapping windows: a claim that straddles a cut would otherwise be
    lost from both sides, and duplicates are cheaper to spot than gaps."""
    if len(text) <= size:
        return [text]
    out, start = [], 0
    while start < len(text):
        out.append(text[start:start + size])
        start += size - overlap
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("knowledge_id", type=int, help="要拆解的条目 id")
    ap.add_argument("--project", required=True, help="拆出来的单元放进哪个项目")
    ap.add_argument("--kind", default="课堂讲授", help="材料类型，写进提示词")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not cfg("QWEN_BASE_URL") or not cfg("QWEN_MODEL"):
        print("没有配置 QWEN_BASE_URL / QWEN_MODEL", file=sys.stderr)
        return 1

    source = api("GET", "/api/knowledge/%d" % args.knowledge_id)
    text = (source.get("content") or "").strip()
    print("源条目 #%d《%s》%d 字" % (source["id"], source["title"], len(text)))

    project_id = None
    if not args.dry_run:
        project_id = next(
            (p["id"] for p in api("GET", "/api/projects")
             if p["name"].lower() == args.project.lower()), None)
        if project_id is None:
            project_id = api("POST", "/api/projects", json_body={
                "name": args.project,
                "description": "从《%s》等长条目拆出的论点单元（抽取，非原文）" % source["title"][:20],
            })["id"]

    parts = chunks(text)
    print("分 %d 段处理" % len(parts))
    started, total = time.time(), 0
    seen_titles = set()
    for i, part in enumerate(parts, 1):
        t0 = time.time()
        try:
            raw = chat(PROMPT.format(kind=args.kind, body=part))
        except Exception as exc:  # noqa: BLE001
            print("  第 %d 段失败: %s" % (i, exc))
            continue
        units = parse_units(raw)
        fresh = [u for u in units if u["title"] not in seen_titles]
        for u in fresh:
            seen_titles.add(u["title"])
            if args.dry_run:
                print("\n--- %s" % u["title"])
                print(body_of(u))
                continue
            tags = ["kind:claim", "来源:%d" % source["id"]]
            tags += ["概念:%s" % t for t in u["terms"][:5] if "," not in t]
            api("POST", "/api/knowledge", fields=[
                ("title", u["title"]), ("content", body_of(u)), ("type", "text"),
                ("project_id", str(project_id)), ("source", "unpack")]
                + [("tags", t) for t in tags])
        total += len(fresh)
        print("  第 %d/%d 段：%d 条主张（去重后 %d）(%.0f 秒)"
              % (i, len(parts), len(units), len(fresh), time.time() - t0))

    print("共 %d 条主张，用时 %.0f 秒" % (total, time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
