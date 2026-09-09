#!/usr/bin/env python3
"""Extract a book into knowledge items, one pass per chapter.

Unlike a plain summary, each event keeps the layer that makes later
cross-context matching possible: why the actor did it, what forced it, and
whose interests were on the line. An event skeleton ("A met B in Berlin") can
only ever be matched to other events involving A or Berlin; an event carrying
its motive ("A traded a regulatory gap for cash to clear an inherited debt")
can be matched to a structurally identical event with a different cast, which
is the whole point of extracting it this way.

Zero third-party dependencies. Talks to the KB over REST and to the local
OpenAI-compatible model directly — deliberately not through the backend,
which must not grow a general prompt-passthrough endpoint while it is exposed
to the public internet.

Usage:
    python scripts/kb_book_extract.py BOOK.epub --project 天幕红尘 --chapters 1-3 --dry-run
    python scripts/kb_book_extract.py BOOK.epub --project 天幕红尘
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import zipfile
from html.parser import HTMLParser

CREDS = os.path.expanduser("~/.claude/kb-credentials")
BACKEND_ENV = os.path.expanduser("~/.kb_backend.env")

# Same reasoning as mcp/kb_mcp_server.py: these targets are this machine's own
# services, never something a system proxy should sit in front of.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _read_env_file(path):
    values = {}
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    except OSError:
        pass
    return values


def config():
    env = _read_env_file(BACKEND_ENV)
    creds = _read_env_file(CREDS)
    get = lambda key, default="": os.environ.get(key) or env.get(key) or creds.get(key) or default
    return {
        "kb_base": get("KB_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
        "kb_token": get("KB_API_TOKEN"),
        "qwen_base": get("QWEN_BASE_URL").rstrip("/"),
        "qwen_key": get("QWEN_API_KEY"),
        "qwen_model": get("QWEN_MODEL"),
    }


CFG = config()


# --- epub -> chapters -------------------------------------------------------

class _Text(HTMLParser):
    """Collect visible text, remembering where each anchor id started.

    Chapters in this epub are anchors inside a handful of large documents
    rather than separate files, so splitting needs character offsets into the
    extracted text, not a file list.
    """

    def __init__(self):
        HTMLParser.__init__(self)
        self.parts = []
        self.length = 0
        self.anchors = {}
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        anchor = attrs.get("id")
        if anchor:
            self.anchors[anchor] = self.length
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("p", "div", "br", "h1", "h2", "h3"):
            self.parts.append("\n")
            self.length += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if self.skip:
            return
        self.parts.append(data)
        self.length += len(data)

    def text(self):
        return "".join(self.parts)


def chapters_from_epub(path):
    """[(title, body)] in reading order, driven by the book's own TOC."""
    book = zipfile.ZipFile(path)
    toc = book.read("OEBPS/toc.ncx").decode("utf-8", "replace")
    nav = re.findall(r"<navPoint.*?<text>(.*?)</text>.*?src=\"(.*?)\"", toc, re.S)

    docs = {}
    for name in book.namelist():
        if name.endswith(".html") or name.endswith(".xhtml"):
            parser = _Text()
            parser.feed(book.read(name).decode("utf-8", "replace"))
            docs[name.split("/")[-1]] = (parser.text(), parser.anchors)

    marks = []
    for title, src in nav:
        title = re.sub(r"<[^>]+>", "", title).strip()
        doc, _, anchor = src.partition("#")
        doc = doc.split("/")[-1]
        if doc not in docs:
            continue
        offset = docs[doc][1].get(anchor, 0) if anchor else 0
        marks.append((title, doc, offset))

    out = []
    for i, (title, doc, offset) in enumerate(marks):
        text = docs[doc][0]
        end = len(text)
        if i + 1 < len(marks) and marks[i + 1][1] == doc:
            end = marks[i + 1][2]
        body = re.sub(r"\n{2,}", "\n", text[offset:end]).strip()
        if len(body) > 200:  # skip the cover/title nav entries
            out.append((title, body))
    return out


# --- model ------------------------------------------------------------------

def chat(prompt, max_tokens=3000, timeout=300):
    """One completion from the local model, with thinking disabled.

    enable_thinking=false is not optional here: a reasoning model spends the
    whole budget on reasoning_content and returns empty content for a task
    this size (kb lesson id=21, hit twice on this deployment).
    """
    payload = {
        "model": CFG["qwen_model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Content-Type": "application/json"}
    if CFG["qwen_key"]:
        headers["Authorization"] = "Bearer " + CFG["qwen_key"]
    req = urllib.request.Request(
        CFG["qwen_base"] + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with _opener.open(req, timeout=timeout) as resp:
        body = json.load(resp)
    return body["choices"][0]["message"]["content"].strip()


PROMPT = """下面是小说《{book}》{chapter}的正文。

请抽取本章的关键事件，每个事件必须包含它的动机和因果，而不只是"谁做了什么"。
这一步的目的是让不同章节、不同人物之间结构相同的事件将来能被识别出来，
所以"为什么这么做""是什么逼出了这件事""谁的什么利益在其中"这三样是重点，
只写事件经过等于白做。

每个事件输出这些字段：
- title: 一句话概括这个事件，15-30 字，必须是完整通顺的一句话，不要截断
- event: 事件经过，2-4 句
- motive: 当事人为什么这么做，用书里的逻辑说，不要替他升华
- cause: 什么条件/前因逼出了这件事，它又导致了什么
- stake: 谁的什么东西（钱、名声、立场、感情、性命）在这件事上有得失
- people: 参与的人物名字数组
- place: 地点，没有就空字符串

只抽真正推动情节或体现人物选择的事件，一章通常 3-8 个，宁缺毋滥。
纯环境描写、过场寒暄不要。

严格输出 JSON 数组，不要输出任何其他文字：
[{{"title":"...","event":"...","motive":"...","cause":"...","stake":"...","people":["..."],"place":"..."}}]

正文：
{body}"""


def parse_events(raw):
    match = re.search(r"\[.*\]", raw, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        event = str(item.get("event") or "").strip()
        if not title or not event:
            continue
        people = [str(p).strip() for p in (item.get("people") or []) if str(p).strip()]
        out.append({
            "title": title[:120],
            "event": event,
            "motive": str(item.get("motive") or "").strip(),
            "cause": str(item.get("cause") or "").strip(),
            "stake": str(item.get("stake") or "").strip(),
            "people": people,
            "place": str(item.get("place") or "").strip(),
        })
    return out


# --- knowledge base ---------------------------------------------------------

def api(method, path, json_body=None, fields=None):
    headers = {"Authorization": "Bearer " + CFG["kb_token"]} if CFG["kb_token"] else {}
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif fields is not None:
        boundary = "----kbbook"
        body = "".join(
            "--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)
            for k, v in fields) + "--%s--\r\n" % boundary
        data = body.encode("utf-8")
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    req = urllib.request.Request(CFG["kb_base"] + path, data=data, headers=headers, method=method)
    with _opener.open(req, timeout=300) as resp:
        return json.load(resp)


def ensure_project(name):
    for project in api("GET", "/api/projects"):
        if project["name"].lower() == name.lower():
            return project["id"]
    return api("POST", "/api/projects", json_body={
        "name": name, "description": "《%s》结构化抽取（事件+动机+因果，非原文）" % name})["id"]


def item_body(ev):
    blocks = [("事件", ev["event"]), ("动机", ev["motive"]), ("因果", ev["cause"]),
              ("利害", ev["stake"]), ("地点", ev["place"]),
              ("出场人物", "、".join(ev["people"]))]
    return "\n\n".join("【%s】\n%s" % (label, text) for label, text in blocks if text)


def write_event(project_id, book, chapter, ev):
    tags = ["kind:event", "作品:%s" % book, "章节:%s" % chapter]
    tags += ["人物:%s" % p for p in ev["people"] if "," not in p]
    fields = [("title", "%s · %s" % (chapter, ev["title"])), ("content", item_body(ev)),
              ("type", "text"), ("project_id", str(project_id)), ("source", "book-extract")]
    fields += [("tags", t) for t in tags]
    return api("POST", "/api/knowledge", fields=fields)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("epub")
    ap.add_argument("--project", required=True, help="项目名，同时用作作品名")
    ap.add_argument("--chapters", help="只处理这些章，如 1-3 或 5")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写入知识库")
    args = ap.parse_args()

    if not CFG["qwen_base"] or not CFG["qwen_model"]:
        print("没有配置 QWEN_BASE_URL / QWEN_MODEL，无法抽取", file=sys.stderr)
        return 1

    chapters = chapters_from_epub(args.epub)
    if args.chapters:
        lo, _, hi = args.chapters.partition("-")
        lo = int(lo)
        hi = int(hi or lo)
        chapters = chapters[lo - 1:hi]
    print("待处理 %d 章" % len(chapters))

    project_id = None if args.dry_run else ensure_project(args.project)
    started = time.time()
    total = 0
    for title, body in chapters:
        t0 = time.time()
        try:
            raw = chat(PROMPT.format(book=args.project, chapter=title, body=body[:12000]))
        except Exception as exc:  # noqa: BLE001 - one bad chapter must not kill the run
            print("  %s 抽取失败: %s" % (title, exc))
            continue
        events = parse_events(raw)
        if not events:
            print("  %s 没解析出事件（模型返回 %d 字符）" % (title, len(raw)))
            continue
        for ev in events:
            if args.dry_run:
                print("\n--- %s · %s" % (title, ev["title"]))
                print(item_body(ev))
            else:
                write_event(project_id, args.project, title, ev)
        total += len(events)
        print("  %s: %d 个事件 (%.0f 秒)" % (title, len(events), time.time() - t0))

    print("共 %d 个事件，用时 %.0f 秒" % (total, time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
