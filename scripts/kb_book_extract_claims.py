#!/usr/bin/env python3
"""Extract a non-fiction book into the claims it actually makes, per chapter.

kb_book_extract.py assumes a novel: each unit is an event with its motive and
stake. A book like *The Selfish Gene* has no plot or cast — it argues, and
each argument is built the same way Dawkins builds all of them: state a
claim, name the misconception it corrects, carry it with a concrete example.
That is exactly the unit kb_unpack.py already extracts from lecture
transcripts, so this script reuses that prompt and its chunk-boundary dedup,
combined with kb_book_extract.py's epub-to-chapter parsing (spine order,
TOC-driven, already fixed once for chapters that live across file boundaries).

Long chapters (this book has several past 20k characters) are chunked the
same way kb_unpack.py chunks a transcript: 12000 characters with a 300
character overlap, telling each later call which titles were already pulled
out of this chapter so a claim split across the cut is not extracted twice.
Dedup state resets at each chapter boundary — a claim the book revisits three
chapters later is a new claim in a new context, not a repeat.

Usage:
    python scripts/kb_book_extract_claims.py BOOK.epub --project "The Extended Selfish Gene" --chapters 8-10 --dry-run
    python scripts/kb_book_extract_claims.py BOOK.epub --project "The Extended Selfish Gene" --chapters 8-22
"""

import argparse
import json
import os
import posixpath
import re
import sys
import time
import urllib.request
import zipfile
from html.parser import HTMLParser
from urllib.parse import unquote

CREDS = os.path.expanduser("~/.claude/kb-credentials")
BACKEND_ENV = os.path.expanduser("~/.kb_backend.env")

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


# --- epub -> chapters (identical to kb_book_extract.py) ---------------------

class _Text(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.parts = []
        self.length = 0
        self.anchors = {}
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for anchor in (attrs.get("id"), attrs.get("name") if tag == "a" else None):
            if anchor and anchor not in self.anchors:
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


def _attrs(tag_text):
    return dict(re.findall(r'([\w:-]+)\s*=\s*"([^"]*)"', tag_text))


def chapters_from_epub(path):
    book = zipfile.ZipFile(path)
    names = set(book.namelist())

    opf_path = None
    if "META-INF/container.xml" in names:
        container = book.read("META-INF/container.xml").decode("utf-8", "replace")
        found = re.search(r'full-path="([^"]+)"', container)
        opf_path = found.group(1) if found else None
    if opf_path not in names:
        opf_path = next((n for n in sorted(names) if n.endswith(".opf")), None)
    if opf_path is None:
        raise ValueError("epub has no package document (.opf)")
    opf_dir = posixpath.dirname(opf_path)
    opf = book.read(opf_path).decode("utf-8", "replace")

    manifest = {}
    ncx_path = None
    for tag in re.findall(r"<item\b[^>]*>", opf):
        a = _attrs(tag)
        if "id" not in a or "href" not in a:
            continue
        full = posixpath.normpath(posixpath.join(opf_dir, unquote(a["href"])))
        manifest[a["id"]] = full
        if a.get("media-type") == "application/x-dtbncx+xml":
            ncx_path = full
    spine = [manifest[_attrs(t)["idref"]] for t in re.findall(r"<itemref\b[^>]*>", opf)
             if _attrs(t).get("idref") in manifest]
    if ncx_path is None:
        ncx_path = next((n for n in sorted(names) if n.endswith(".ncx")), None)
    if ncx_path is None:
        raise ValueError("epub has no NCX table of contents")

    pieces, doc_start, anchor_at, total = [], {}, {}, 0
    for doc in spine:
        if doc not in names or doc in doc_start:
            continue
        parser = _Text()
        parser.feed(book.read(doc).decode("utf-8", "replace"))
        doc_start[doc] = total
        for anchor, local in parser.anchors.items():
            anchor_at[(doc, anchor)] = total + local
        pieces.append(parser.text() + "\n")
        total += len(pieces[-1])
    full_text = "".join(pieces)

    ncx_dir = posixpath.dirname(ncx_path)
    toc = book.read(ncx_path).decode("utf-8", "replace")
    marks = []
    for title, src in re.findall(r"<navPoint.*?<text>(.*?)</text>.*?src=\"(.*?)\"", toc, re.S):
        title = re.sub(r"<[^>]+>", "", title).strip()
        href, _, anchor = src.partition("#")
        doc = posixpath.normpath(posixpath.join(ncx_dir, unquote(href)))
        if doc not in doc_start:
            continue
        offset = anchor_at.get((doc, anchor), doc_start[doc]) if anchor else doc_start[doc]
        marks.append((offset, title))
    marks.sort(key=lambda m: m[0])

    out = []
    for i, (offset, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(full_text)
        body = re.sub(r"\n{2,}", "\n", full_text[offset:end]).strip()
        if len(body) > 200:
            out.append((title, body))
    return out


# --- model --------------------------------------------------------------

def chat(prompt, max_tokens=3000, timeout=300):
    payload = {
        "model": CFG["qwen_model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        # MiMo's official API reads max_completion_tokens instead of
        # max_tokens; sending both keeps this working whichever endpoint
        # QWEN_BASE_URL currently points at.
        "max_completion_tokens": max_tokens,
        "temperature": 0.2,
        # Lesson id=21: a reasoning model spends the whole budget thinking and
        # returns empty content on extraction-shaped work. chat_template_kwargs
        # is the vLLM/llama.cpp shape (local Qwen3); thinking.type is MiMo's
        # official API shape. Sending both is harmless on either.
        "chat_template_kwargs": {"enable_thinking": False},
        "thinking": {"type": "disabled"},
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


PROMPT = """下面是《{book}》{chapter}的正文（非虚构论证类图书的一章，不是小说）。

请抽出本章中作者真正主张的观点，一条一个单元。同一个观点如果在本章里被从不同角度反复
论证或换了个例子重讲，算作一条，不要拆成多条。

每条输出这些字段：
- title: 这条主张是什么，一句话，15-30 字，完整通顺
- claim: 主张本身，2-4 句，按作者的逻辑说，不要替他拔高也不要替他补充
- against: 他在反驳/纠正什么常见误解或对立观点；这本书大量论证都是冲着一个误解去的，写清那个误解是什么，没有就空字符串
- examples: 他用来支撑这条主张的具体例子（书里举的物种、实验、数据），照书里写，别自己编
- method: 这条主张里可操作的做法（要求读者具体怎么想/怎么做）；纯理论没给做法就空字符串
- terms: 这条里出现的关键概念，字符串数组

只抽真正的主张，不要把过渡句、对上一章的总结、纯背景介绍当成主张。
一章通常 3-10 条，宁缺毋滥。

只能抽下面「正文」里实际写出来的内容。如果「正文」本身不是论证性正文——比如只是目录、
章节标题列表、参考书目、版权信息这类结构性文字——里面没有可抽的主张，直接输出空数组 []。
绝对不能凭你自己对《自私的基因》这本书的已有了解去补内容；这里只做文本抽取，不是背书。
{already}
严格输出 JSON 数组，不要输出任何其他文字：
[{{"title":"...","claim":"...","against":"...","examples":["..."],"method":"...","terms":["..."]}}]

正文：
{body}"""

ALREADY = """
以下主张在本章前面部分已经抽过了，**不要再抽一遍**——如果这一段只是换个说法或换个例子
重讲同一个观点，跳过它；只有当这一段对它有实质性的新增（新的论证、新的适用范围）时，
才作为新的一条抽出来，并在 claim 里写清新增的是什么。
{titles}
"""


def parse_units(raw):
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


# Same sizing and reasoning as kb_unpack.py: large enough that a typical
# chapter needs no split at all, and the overlap plus already-seen dedup
# handles the chapters that do.
CHUNK = 12000
OVERLAP = 300


def chunks(text, size=CHUNK, overlap=OVERLAP):
    if len(text) <= size:
        return [text]
    out, start = [], 0
    while start < len(text):
        out.append(text[start:start + size])
        start += size - overlap
    return out


# --- knowledge base -------------------------------------------------------

def api(method, path, json_body=None, fields=None):
    headers = {"X-KB-Agent": "kb-book-extract-claims"}
    if CFG["kb_token"]:
        headers["Authorization"] = "Bearer " + CFG["kb_token"]
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif fields is not None:
        boundary = "----kbbookclaims"
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
        "name": name, "description": "《%s》主张抽取（论点+反驳对象+例子，非原文）" % name})["id"]


def item_body(u):
    blocks = [("主张", u["claim"]), ("针对的误解", u["against"]),
              ("例子", "\n".join("- " + e for e in u["examples"])),
              ("可操作", u["method"])]
    return "\n\n".join("【%s】\n%s" % (label, text) for label, text in blocks if text)


def write_claim(project_id, book, chapter, u):
    tags = ["kind:claim", "作品:%s" % book, "章节:%s" % chapter]
    tags += ["概念:%s" % t for t in u["terms"][:5] if "," not in t]
    fields = [("title", "%s · %s" % (chapter, u["title"])), ("content", item_body(u)),
              ("type", "text"), ("project_id", str(project_id)), ("source", "book-extract")]
    fields += [("tags", t) for t in tags]
    return api("POST", "/api/knowledge", fields=fields)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("epub")
    ap.add_argument("--project", required=True, help="项目名，同时用作作品名")
    ap.add_argument("--chapters", help="只处理这些章（按解析出的目录顺序编号，从1开始），如 8-22 或 5")
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
        parts = chunks(body)
        seen_titles = set()
        chapter_total = 0
        for i, part in enumerate(parts, 1):
            already = ALREADY.format(titles="\n".join("- " + t for t in sorted(seen_titles))) if seen_titles else ""
            prompt = PROMPT.format(book=args.project, chapter=title, body=part, already=already)
            try:
                raw = chat(prompt)
            except Exception as exc:  # noqa: BLE001 - one bad segment must not kill the run
                print("  %s 第%d段 抽取失败: %s" % (title, i, exc))
                continue
            units = parse_units(raw)
            # A real chunk of prose that comes back with zero claims is more
            # often a bad sample (temperature=0.2 still varies run to run —
            # confirmed by hand on this exact model: the same chunk returned
            # 9 claims, then 5, then 0 across three calls) than a genuinely
            # argument-free section. Anecdotal-opening prefaces (the author
            # reminiscing before the real argument starts) seem to trigger
            # this particularly often, so a single retry isn't always enough
            # — up to 2 retries costs at most 2 extra calls, and it does not
            # touch chunks that are legitimately empty on every try (front
            # matter that really is just structural text stays at zero).
            attempt = 1
            while not units and len(part) >= 500 and attempt < 3:
                attempt += 1
                try:
                    raw = chat(prompt)
                    units = parse_units(raw)
                except Exception:
                    break
            fresh = [u for u in units if u["title"] not in seen_titles]
            for u in fresh:
                seen_titles.add(u["title"])
                if args.dry_run:
                    print("\n--- %s · %s" % (title, u["title"]))
                    print(item_body(u))
                else:
                    write_claim(project_id, args.project, title, u)
            chapter_total += len(fresh)
        total += chapter_total
        print("  %s: %d 条主张 (%.0f 秒)" % (title, chapter_total, time.time() - t0))

    print("共 %d 条主张，用时 %.0f 秒" % (total, time.time() - started))
    return 0


if __name__ == "__main__":
    sys.exit(main())
