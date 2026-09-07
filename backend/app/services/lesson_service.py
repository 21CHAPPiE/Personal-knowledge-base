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

from app.services.attachment_service import list_attachment_rows
from app.services.common import knowledge_out
from app.utils import parse_tags

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


def _candidate_rows(conn: sqlite3.Connection, signature: str, limit: int) -> list:
    """Rows whose title/content contain the signature, FTS hits first.

    Mirrors search_service's two-pass approach: FTS5 for ranked term matches,
    plus a LIKE pass because FTS misses short CJK terms and mid-token
    substrings — and an error string pasted verbatim is usually the latter.
    """
    tag_filter = " AND (',' || k.tags || ',') LIKE ?"
    tag_param = "%,{},%".format(LESSON_TAG)
    fetch = max(limit * 5, 50)

    found = {}
    order = []

    terms = [t for t in re.split(r"\s+", signature.strip()) if t]
    if terms:
        fts_q = " ".join(_escape_fts_term(t) for t in terms)
        sql = (
            "{} JOIN knowledge_fts f ON f.rowid = k.id"
            " WHERE knowledge_fts MATCH ?{}"
            " ORDER BY bm25(knowledge_fts, 5.0, 1.0, 2.0) LIMIT ?".format(_ITEM_SELECT, tag_filter)
        )
        try:
            rows = conn.execute(sql, [fts_q, tag_param, fetch]).fetchall()
        except sqlite3.OperationalError:
            rows = []  # malformed FTS expression; the LIKE pass still covers us
        for r in rows:
            if r["id"] not in found:
                found[r["id"]] = r
                order.append(r["id"])

    like = "%{}%".format(signature.strip())
    sql = (
        "{} WHERE (k.title LIKE ? OR k.content LIKE ?){}"
        " ORDER BY k.updated_at DESC LIMIT ?".format(_ITEM_SELECT, tag_filter)
    )
    for r in conn.execute(sql, [like, like, tag_param, fetch]).fetchall():
        if r["id"] not in found:
            found[r["id"]] = r
            order.append(r["id"])

    return [found[i] for i in order]


def match_lessons(conn: sqlite3.Connection, signature: str,
                  os_name: Optional[str] = None, machine: Optional[str] = None,
                  stack: Optional[List[str]] = None, project_id: Optional[int] = None,
                  limit: int = 10) -> List[dict]:
    limit = max(1, min(int(limit), 50))
    scored = []
    for row in _candidate_rows(conn, signature, limit):
        tags = parse_tags(row["tags"])
        if LESSON_TAG not in tags:
            continue  # LIKE on the joined tag string can over-match; verify exactly
        if _excluded(tags, os_name, machine):
            continue
        score, reasons = _score(tags, row["project_id"], machine, stack, project_id)
        scored.append((score, row["updated_at"], row, reasons))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)

    out = []
    for score, _updated, row, reasons in scored[:limit]:
        item = knowledge_out(row, attachments=list_attachment_rows(conn, row["id"]),
                             content_preview=True)
        item["match_score"] = score
        item["match_reasons"] = reasons
        out.append(item)
    return out
