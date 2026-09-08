"""Lesson matching: "have we hit this before?"

Lessons are ordinary knowledge_items carrying a `kind:lesson` tag — there is no
lessons table, because `knowledge_items.type` is CHECK-constrained and this
project has no migration mechanism (see docs/lessons-system-plan.md).

Matching is deliberately two-sided. Scoring surfaces the lessons most likely to
apply, but the exclusion rules matter more: a lesson that is true on Linux and
false on Windows is worse than no lesson at all, so scope tags that contradict
the caller's situation drop the row entirely rather than merely lowering it.
"""

import hashlib
import json
import os
import re
import sqlite3
from typing import List, Optional

from app.providers.embedding import cosine, pack_vector, unpack_vector
from app.providers.factory import get_embedding_provider, get_rerank_provider
from app.services.attachment_service import list_attachment_rows
from app.services.common import knowledge_out
from app.utils import parse_tags, utcnow_iso

LESSON_TAG = "kind:lesson"

SIGNATURE_SCORE = 5
MACHINE_SCORE = 3
STACK_SCORE = 2
PROJECT_SCORE = 2
UNIVERSAL_SCORE = 1

_ITEM_SELECT = (
    "SELECT k.*, p.name AS project_name FROM knowledge_items k"
    " LEFT JOIN projects p ON p.id = k.project_id"
)


def _escape_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _tag_values(tags: List[str], prefix: str) -> List[str]:
    """All values carried under a tag prefix, e.g. stack:vite -> ['vite']."""
    return [t[len(prefix):] for t in tags if t.startswith(prefix)]


def _scope_of(tags: List[str]) -> Optional[str]:
    values = _tag_values(tags, "scope:")
    return values[0] if values else None


def _excluded(tags: List[str], os_name: Optional[str], machine: Optional[str]) -> bool:
    """Reasons a lesson must not be shown at all, regardless of its score."""
    if os_name:
        # Explicit anti-scope: the lesson author said it does not hold here.
        if "not:os:" + os_name in tags:
            return True
        # Declares an OS, and it isn't the caller's.
        lesson_os = _tag_values(tags, "os:")
        if lesson_os and os_name not in lesson_os:
            return True
    if machine and _scope_of(tags) == "machine":
        # Machine-scoped lessons never transfer to a different machine.
        lesson_machines = _tag_values(tags, "machine:")
        if lesson_machines and machine not in lesson_machines:
            return True
    return False


def _score(tags: List[str], project_id_of_row: Optional[int],
           machine: Optional[str], stack: Optional[List[str]],
           project_id: Optional[int]) -> (int, List[str]):
    score = SIGNATURE_SCORE
    reasons = ["signature"]
    if machine and machine in _tag_values(tags, "machine:"):
        score += MACHINE_SCORE
        reasons.append("machine")
    if stack:
        lesson_stack = _tag_values(tags, "stack:")
        if any(s in lesson_stack for s in stack):
            score += STACK_SCORE
            reasons.append("stack")
    if project_id is not None and project_id_of_row == project_id:
        score += PROJECT_SCORE
        reasons.append("project")
    if _scope_of(tags) == "universal":
        score += UNIVERSAL_SCORE
        reasons.append("universal")
    return score, reasons


def _signature_keys(content: str) -> List[str]:
    """The 【触发签名】 block, one distinctive marker per line.

    Falls back to the whole content when the block is absent, so lessons
    written before this convention still match on something.
    """
    match = re.search(r"【触发签名】\s*\n(.*?)(?=\n\s*【|\Z)", content or "", re.S)
    if not match:
        return [ln.strip() for ln in (content or "").splitlines() if ln.strip()]
    return [ln.strip() for ln in match.group(1).splitlines() if ln.strip()]


def _candidate_rows(conn: sqlite3.Connection, signature: str) -> list:
    """Lessons whose signature keys relate to this query, as (row, hit_kind).

    Matching runs primarily in the direction "does the incoming error contain a
    stored marker?" rather than the reverse. The reverse is what the first
    version did, and it failed exactly when the caller was most helpful: every
    extra token in a pasted error (a port, a path, a PID) made a hit less
    likely, so the more faithfully you reported the error, the less you found.

    Candidate rows are filtered by tag in SQL and then compared in Python. That
    is fine while lessons number in the hundreds; past a few thousand this
    wants to move back into the query.
    """
    rows = conn.execute(
        "{} WHERE (',' || k.tags || ',') LIKE ?".format(_ITEM_SELECT),
        ["%,{},%".format(LESSON_TAG)],
    ).fetchall()
    query = signature.strip()
    query_lower = query.lower()
    query_terms = set(t.lower() for t in re.split(r"\s+", query) if t)

    scored = []
    for row in rows:
        keys = _signature_keys(row["content"])
        hit = None

        # Primary direction: does the (noisy) incoming error contain a known
        # marker? This is the case that used to fail — the old code asked the
        # reverse, so every extra word in the query made a match less likely.
        for key in keys:
            if key.lower() in query_lower:
                hit = "signature"
                break

        # Reverse: a short query naming part of a stored key.
        if hit is None:
            for key in keys:
                if query_lower and query_lower in key.lower():
                    hit = "signature"
                    break

        # Fallback for reworded text: partial term overlap against the whole
        # item, requiring a majority of query terms so this stays selective.
        if hit is None and query_terms:
            haystack = "{}\n{}".format(row["title"], row["content"]).lower()
            overlap = sum(1 for t in query_terms if t in haystack)
            if overlap / len(query_terms) >= 0.6:
                hit = "partial"

        if hit:
            scored.append((row, hit))
    return scored


def _semantic_text(row) -> str:
    """What gets embedded and reranked: title + 根因 + 解法.

    Not the raw error string — signature keys are the keyword layer's job, and
    folding them in only dilutes the vector.

    解法 earns its place by measurement, not symmetry: "不小心把 node_modules
    提交上去了怎么撤回" scored -3.48 against a lesson carrying only title+根因
    and -0.81 once 解法 was included. Queries phrased as "how do I undo this"
    are answered by the remedy, so leaving it out made exactly that phrasing
    unmatchable.
    """
    parts = [row["title"] or ""]
    for marker in ("【根因】", "【解法】"):
        section = _section(row["content"], marker)
        if section:
            parts.append(section)
    return "\n".join(p for p in parts if p).strip()


def _section(content: str, marker: str) -> str:
    found = re.search(re.escape(marker) + r"\s*\n(.*?)(?=\n\s*【|\Z)", content or "", re.S)
    return found.group(1).strip() if found else ""


def _rerank_texts(row) -> List[str]:
    """Two views of one lesson, scored separately, best score wins.

    Different phrasings want different halves of a lesson, and no single blob
    serves both. Measured: "Invalid Host header" (asking *what is this error*)
    matches title+根因 at -0.74 but disappears entirely once 解法 is mixed in,
    because the remedy is Vite-specific while the question came from webpack.
    "node_modules 提交了怎么撤回" (asking *how do I fix it*) is the mirror image:
    -3.48 against 根因, -0.81 against 解法.

    Scoring both and keeping the max got every true positive through while
    single-blob variants each lost one — and it is what pushed the worst true
    positive above the best false positive, which no single representation did.
    """
    title = row["title"] or ""
    texts = []
    for marker in ("【根因】", "【解法】"):
        section = _section(row["content"], marker)
        text = "{}\n{}".format(title, section).strip() if section else title.strip()
        if text and text not in texts:
            texts.append(text)
    return texts or [title.strip() or "(untitled)"]


def embed_lesson(conn: sqlite3.Connection, knowledge_id: int) -> bool:
    """Compute and store one lesson's vector. False when unavailable — callers
    must treat that as normal, not as an error."""
    provider = get_embedding_provider()
    if not provider.is_configured():
        return False
    row = conn.execute(
        "SELECT k.*, NULL AS project_name FROM knowledge_items k WHERE k.id = ?",
        (knowledge_id,),
    ).fetchone()
    if not row:
        return False
    vector = provider.embed(_semantic_text(row))
    if not vector:
        return False
    conn.execute(
        "INSERT INTO knowledge_embeddings (knowledge_id, model, dim, vector, updated_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT(knowledge_id) DO UPDATE SET"
        " model=excluded.model, dim=excluded.dim, vector=excluded.vector,"
        " updated_at=excluded.updated_at",
        (knowledge_id, provider.model, len(vector), pack_vector(vector), utcnow_iso()),
    )
    conn.commit()
    return True


# Recall floor, not a precision cut: the reranker makes the final call, so this
# only has to avoid dragging the whole corpus into the rerank batch.
SEMANTIC_FLOOR = 0.35
SEMANTIC_MAX_HITS = 10

# Precision cut on cross-encoder scores, with the two-view scoring above.
# Measured over 6 real lessons and 8 queries: true positives bottom out at -0.74
# ("Invalid Host header") and the nearest false positives are "怎么配置 nginx
# 反向代理" at -1.01 and "docker compose 启动失败" at -1.81, so -0.9 separates
# every case — narrowly.
#
# Two caveats worth keeping in view. The margin is 0.27, tuned on 8 points, so
# treat it as provisional; that is why it is an env knob rather than a constant.
# And the plausible near-misses are the ones that hurt: an obviously unrelated
# query ("怎么做红烧肉") is rejected by a mile, while a query from the same
# neighbourhood as a lesson sits right on the line. Callers see the score, so a
# consumer wanting a stricter bar can apply its own.
def _rerank_cutoff() -> float:
    try:
        return float(os.environ.get("KB_RERANK_CUTOFF", "-0.9"))
    except ValueError:
        return -0.9

# Used only when no reranker is configured, where the bi-encoder has to make the
# precision call by itself and the workable band is much narrower.
VECTOR_ONLY_FLOOR = 0.50


def _corpus_fingerprint(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), '') AS latest"
        " FROM knowledge_items WHERE (',' || tags || ',') LIKE ?",
        ["%,{},%".format(LESSON_TAG)],
    ).fetchone()
    return "{}:{}".format(row["n"], row["latest"])


def _cache_key(conn: sqlite3.Connection, signature: str, os_name, machine,
               stack, project_id) -> str:
    raw = "|".join([
        signature.strip(), os_name or "", machine or "",
        ",".join(sorted(stack or [])), str(project_id or ""),
        _corpus_fingerprint(conn),
    ])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cache_get(conn: sqlite3.Connection, cache_key: str, limit: int):
    """Previously matched ids for this exact situation, re-materialised.

    Only ids are cached, never the rendered items — a lesson's text can be
    edited without changing the corpus fingerprint's row count, and serving a
    stale copy of its body would be worse than the cache miss it saves.
    """
    row = conn.execute(
        "SELECT result_ids FROM lesson_match_cache WHERE cache_key = ?", (cache_key,)
    ).fetchone()
    if row is None:
        return None
    try:
        entries = json.loads(row["result_ids"])
    except (ValueError, TypeError):
        return None
    if not entries:
        return []
    out = []
    for entry in entries[:limit]:
        kid = entry["id"]
        item_row = conn.execute("{} WHERE k.id = ?".format(_ITEM_SELECT), (kid,)).fetchone()
        if item_row is None:
            return None  # a cached lesson was deleted; recompute instead
        item = knowledge_out(item_row, attachments=list_attachment_rows(conn, kid),
                             content_preview=True)
        item["match_score"] = entry["score"]
        item["match_reasons"] = entry["reasons"] + ["cached"]
        out.append(item)
    return out


def _cache_put(conn: sqlite3.Connection, cache_key: str, items: List[dict]) -> None:
    conn.execute(
        "INSERT INTO lesson_match_cache (cache_key, result_ids, created_at)"
        " VALUES (?, ?, ?)"
        " ON CONFLICT(cache_key) DO UPDATE SET"
        " result_ids=excluded.result_ids, created_at=excluded.created_at",
        (cache_key, json.dumps([
            {"id": i["id"], "score": i["match_score"], "reasons": i["match_reasons"]}
            for i in items
        ]), utcnow_iso()),
    )
    conn.commit()


def _semantic_candidates(conn: sqlite3.Connection, signature: str,
                         threshold: float = SEMANTIC_FLOOR) -> dict:
    """{knowledge_id: similarity} for lessons close to this text in meaning.

    Covers the case signature keys cannot: same root cause, different wording
    (Vite's "Blocked request" vs webpack's "Invalid Host header").

    On the floor: bge-m3 compresses cosine scores into a narrow band. Measured
    on real pairs here, a same-cause/different-framework match scored 0.53 while
    unrelated text scored 0.43 — a margin of only ~0.1. A stricter cut would
    have dropped precisely the case this layer exists for, so the floor is
    deliberately loose, hits are capped, and the similarity is returned to the
    caller instead of being hidden behind a boolean.
    """
    provider = get_embedding_provider()
    if not provider.is_configured():
        return {}
    query_vec = provider.embed(signature)
    if not query_vec:
        return {}
    rows = conn.execute(
        "SELECT e.knowledge_id, e.vector FROM knowledge_embeddings e"
        " JOIN knowledge_items k ON k.id = e.knowledge_id"
        " WHERE (',' || k.tags || ',') LIKE ?",
        ["%,{},%".format(LESSON_TAG)],
    ).fetchall()
    hits = []
    for row in rows:
        score = cosine(query_vec, unpack_vector(row["vector"]))
        if score >= threshold:
            hits.append((score, row["knowledge_id"]))
    hits.sort(reverse=True)
    return {kid: score for score, kid in hits[:SEMANTIC_MAX_HITS]}


def _apply_rerank(conn: sqlite3.Connection, signature: str, candidates: dict):
    """Let a cross-encoder make the precision call on the recalled candidates.

    The vector floor above is deliberately loose because it only has to achieve
    recall; this is where things actually get rejected. Without a reranker the
    bi-encoder has to do both jobs, so the tighter VECTOR_ONLY_FLOOR applies
    instead — workable, but with roughly a tenth of the headroom.
    """
    if not candidates:
        return candidates, False
    provider = get_rerank_provider()
    if not provider.is_configured():
        return {
            kid: value for kid, value in candidates.items()
            if value[1] != "semantic" or (value[2] or 0.0) >= VECTOR_ONLY_FLOOR
        }, False

    docs = []
    owners = []
    for kid in candidates:
        for text in _rerank_texts(candidates[kid][0]):
            docs.append(text)
            owners.append(kid)
    scores = provider.rerank(signature, docs)
    if scores is None:
        return candidates, False  # reranker unreachable: degrade to recall results

    best = {}
    for kid, score in zip(owners, scores):
        if kid not in best or score > best[kid]:
            best[kid] = score

    kept = {}
    for kid, score in best.items():
        row, hit_kind, _similarity = candidates[kid]
        if hit_kind != "semantic" or score >= _rerank_cutoff():
            kept[kid] = (row, hit_kind, score)
    return kept, True


def match_lessons(conn: sqlite3.Connection, signature: str,
                  os_name: Optional[str] = None, machine: Optional[str] = None,
                  stack: Optional[List[str]] = None, project_id: Optional[int] = None,
                  limit: int = 10) -> List[dict]:
    limit = max(1, min(int(limit), 50))

    cache_key = _cache_key(conn, signature, os_name, machine, stack, project_id)
    cached = _cache_get(conn, cache_key, limit)
    if cached is not None:
        return cached

    reranked = False
    keyword_rows = _candidate_rows(conn, signature)
    candidates = {}
    for row, hit_kind in keyword_rows:
        candidates[row["id"]] = (row, hit_kind, None)

    # Short circuit: a signature hit means the incoming error literally contains
    # a marker someone recorded, which is stronger evidence than anything the
    # models can offer. Returning here keeps the common case — the same error
    # hit twice — at a few milliseconds and touches no model at all.
    strong = any(kind == "signature" for _row, kind in keyword_rows)

    if not strong:
        for kid, similarity in _semantic_candidates(conn, signature).items():
            if kid in candidates:
                row, hit_kind, _ = candidates[kid]
                candidates[kid] = (row, hit_kind, similarity)
            else:
                row = conn.execute(
                    "{} WHERE k.id = ?".format(_ITEM_SELECT), (kid,)
                ).fetchone()
                if row is not None:
                    candidates[kid] = (row, "semantic", similarity)
        candidates, reranked = _apply_rerank(conn, signature, candidates)

    scored = []
    for row, hit_kind, similarity in candidates.values():
        tags = parse_tags(row["tags"])
        if LESSON_TAG not in tags:
            continue  # LIKE on the joined tag string can over-match; verify exactly
        if _excluded(tags, os_name, machine):
            continue
        score, reasons = _score(tags, row["project_id"], machine, stack, project_id)
        if hit_kind == "partial":
            score -= 2  # reworded guess, rank it under a real signature hit
            reasons = ["partial"] + reasons[1:]
        elif hit_kind == "semantic":
            score -= 1  # meaning-only match: useful, but weaker evidence
            reasons = ["semantic"] + reasons[1:]
        if similarity is not None:
            # After reranking this number is a cross-encoder logit, not a cosine;
            # labelling them the same would invite comparing incomparable scales.
            label = "rerank" if reranked else "similarity"
            reasons.append("{}={:.2f}".format(label, similarity))
        scored.append((score, similarity or 0.0, row["updated_at"], row, reasons))

    # Similarity has to sit in the sort key, not just the output: semantic-only
    # hits all share one base score, so without it a 0.59 match could outrank a
    # 0.62 one purely because it was written later.
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

    out = []
    for score, _sim, _updated, row, reasons in scored[:limit]:
        item = knowledge_out(row, attachments=list_attachment_rows(conn, row["id"]),
                             content_preview=True)
        item["match_score"] = score
        item["match_reasons"] = reasons
        out.append(item)
    _cache_put(conn, cache_key, out)
    return out
