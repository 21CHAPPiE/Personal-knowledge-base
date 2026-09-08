"""Lesson matching: "have we hit this before?"

Lessons are ordinary knowledge_items carrying a `kind:lesson` tag — there is no
lessons table, because `knowledge_items.type` is CHECK-constrained and this
project has no migration mechanism (see docs/lessons-system-plan.md).

Matching is deliberately two-sided. Scoring surfaces the lessons most likely to
apply, but the exclusion rules matter more: a lesson that is true on Linux and
false on Windows is worse than no lesson at all, so scope tags that contradict
the caller's situation drop the row entirely rather than merely lowering it.
"""

import re
import sqlite3
from typing import List, Optional

from app.providers.embedding import cosine, pack_vector, unpack_vector
from app.providers.factory import get_embedding_provider
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
    """What actually gets embedded: the concept, not the raw error string.

    Signature keys are the keyword layer's job. Folding them into the vector
    would only dilute it — the two layers are meant to catch different things
    (literal repeat vs. same cause worded differently)."""
    content = row["content"] or ""
    cause = re.search(r"【根因】\s*\n(.*?)(?=\n\s*【|\Z)", content, re.S)
    parts = [row["title"] or ""]
    if cause:
        parts.append(cause.group(1).strip())
    return "\n".join(p for p in parts if p).strip()


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


SEMANTIC_FLOOR = 0.50
SEMANTIC_MAX_HITS = 3


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


def match_lessons(conn: sqlite3.Connection, signature: str,
                  os_name: Optional[str] = None, machine: Optional[str] = None,
                  stack: Optional[List[str]] = None, project_id: Optional[int] = None,
                  limit: int = 10) -> List[dict]:
    limit = max(1, min(int(limit), 50))

    candidates = {}
    for row, hit_kind in _candidate_rows(conn, signature):
        candidates[row["id"]] = (row, hit_kind, None)

    # Semantic pass: adds lessons whose wording differs but whose cause matches,
    # and upgrades ones the keyword pass only reached by partial overlap.
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
            reasons.append("similarity={:.2f}".format(similarity))
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
    return out
