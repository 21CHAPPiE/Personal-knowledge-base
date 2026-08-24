"""Full-text search: SQLite FTS5 (unicode61, bm25 ranking) with a LIKE
substring fallback so short CJK terms (e.g. two-character words) still match.

FTS hits come first (ranked), then LIKE-only hits (newest first). Results are
deduplicated by knowledge id.
"""

import re
import sqlite3
from typing import List, Optional

from app.services.common import knowledge_out
from app.services.attachment_service import list_attachment_rows

_ITEM_SELECT = (
    "SELECT k.*, p.name AS project_name FROM knowledge_items k"
    " LEFT JOIN projects p ON p.id = k.project_id"
)


def _escape_fts_term(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _fts_query(q: str) -> Optional[str]:
    terms = [t for t in re.split(r"\s+", q.strip()) if t]
    if not terms:
        return None
    return " ".join(_escape_fts_term(t) for t in terms)


def _filters_sql(project_id: Optional[int], type: Optional[str], tag: Optional[str]):
    where = []
    params: list = []
    if project_id is not None:
        where.append("k.project_id = ?")
        params.append(project_id)
    if type:
        where.append("k.type = ?")
        params.append(type)
    if tag:
        where.append("(',' || k.tags || ',') LIKE ?")
        params.append(f"%,{tag.strip()},%")
    return (" AND " + " AND ".join(where)) if where else "", params


def search(conn: sqlite3.Connection, q: str, project_id: Optional[int] = None,
           type: Optional[str] = None, tag: Optional[str] = None,
           limit: int = 20, offset: int = 0) -> List[dict]:
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    extra, extra_params = _filters_sql(project_id, type, tag)
    results: dict = {}
    order: list = []

    # 1) FTS5 ranked matches
    fts_q = _fts_query(q)
    if fts_q:
        sql = (
            f"{_ITEM_SELECT} JOIN knowledge_fts f ON f.rowid = k.id"
            f" WHERE knowledge_fts MATCH ?{extra}"
            f" ORDER BY bm25(knowledge_fts, 5.0, 1.0, 2.0) LIMIT ?"
        )
        rows = conn.execute(sql, [fts_q] + extra_params + [limit]).fetchall()
        for i, r in enumerate(rows):
            results[r["id"]] = (r, i)
            order.append(r["id"])

    # 2) LIKE substring fallback (covers CJK terms FTS misses, e.g. 2-char words)
    terms = [t for t in re.split(r"\s+", q.strip()) if t]
    for term in terms:
        like = f"%{term}%"
        sql = (
            f"{_ITEM_SELECT}"
            f" WHERE (k.title LIKE ? OR k.content LIKE ?){extra}"
            f" ORDER BY k.updated_at DESC LIMIT ?"
        )
        rows = conn.execute(sql, [like, like] + extra_params + [limit]).fetchall()
        for r in rows:
            if r["id"] not in results:
                results[r["id"]] = (r, len(results))
                order.append(r["id"])

    ordered = order[offset: offset + limit]
    out = []
    for kid in ordered:
        row = results[kid][0]
        item = knowledge_out(row, attachments=list_attachment_rows(conn, kid), content_preview=True)
        out.append(item)
    return out
