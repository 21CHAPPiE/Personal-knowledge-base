"""Knowledge item CRUD and association with projects."""

import sqlite3
from typing import List, Optional

from app.models.schemas import KnowledgeCreate, KnowledgeUpdate
from app.services.attachment_service import (
    create_attachment,
    delete_attachments_for_knowledge,
    list_attachment_rows,
)
from app.services.common import find_project, knowledge_out
from app.utils import parse_tags, utcnow_iso


class KnowledgeNotFound(Exception):
    pass


def _item_row(conn: sqlite3.Connection, knowledge_id: int) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT k.*, p.name AS project_name FROM knowledge_items k"
        " LEFT JOIN projects p ON p.id = k.project_id"
        " WHERE k.id = ?",
        (knowledge_id,),
    ).fetchone()


def create_knowledge(conn: sqlite3.Connection, data: KnowledgeCreate,
                     file: Optional[dict] = None) -> dict:
    """Create an item; `file` (when given) is {name, bytes, mime} saved as its attachment.

    For type=voice with a file and an STT provider configured, a transcript is
    attempted and written to content when the caller passed no content.
    """
    if data.project_id is not None and not find_project(conn, data.project_id):
        raise ValueError(f"project_id {data.project_id} does not exist")
    now = utcnow_iso()
    tags = ",".join(parse_tags(data.tags))
    cur = conn.execute(
        "INSERT INTO knowledge_items (project_id, type, title, content, source, tags, summary, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
        (data.project_id, data.type, data.title, data.content, data.source, tags, now, now),
    )
    conn.commit()
    knowledge_id = cur.lastrowid
    if file is not None:
        create_attachment(conn, knowledge_id, file["name"], file["bytes"], file.get("mime", ""))

    stt_info = None
    if data.type == "voice" and file is not None and not (data.content or "").strip():
        stt_info = _try_transcribe(conn, knowledge_id)
    _maybe_embed_lesson(conn, knowledge_id, tags)
    row = _item_row(conn, knowledge_id)
    out = knowledge_out(row, attachments=list_attachment_rows(conn, knowledge_id), content_preview=True)
    if stt_info:
        out["stt"] = stt_info
    return out


def _maybe_embed_lesson(conn: sqlite3.Connection, knowledge_id: int, tags: str) -> None:
    """Vectorise a lesson as it is written.

    Without this the two halves of the loop never meet: a lesson recorded
    through the skill or MCP stays invisible to semantic search until somebody
    remembers to call /api/lessons/reindex — and remembering is precisely what
    this system exists to not depend on.

    Never allowed to fail the write. An unavailable embedding service means the
    lesson is still saved and still keyword-matchable; reindex can fill the
    vector in later.
    """
    from app.services.lesson_service import LESSON_TAG

    if LESSON_TAG not in parse_tags(tags):
        return
    try:
        from app.services.lesson_service import embed_lesson

        embed_lesson(conn, knowledge_id)
    except Exception:  # noqa: BLE001 - a lost vector must never lose the lesson
        pass


def _try_transcribe(conn: sqlite3.Connection, knowledge_id: int) -> Optional[dict]:
    """Best-effort STT on the first audio attachment. Returns status info for the
    API response; never raises, never invents a transcript."""
    from app.providers.factory import get_stt_provider
    from app.services.attachment_service import attachment_file_path

    provider = get_stt_provider()
    if not provider.is_configured():
        return {"configured": False, "transcript": None}
    rows = conn.execute(
        "SELECT * FROM attachments WHERE knowledge_id = ? ORDER BY id LIMIT 1", (knowledge_id,)
    ).fetchall()
    if not rows:
        return {"configured": True, "transcript": None}
    try:
        path = str(attachment_file_path(rows[0]))
        transcript = provider.transcribe(path, rows[0]["mime_type"])
    except Exception:
        transcript = None
    if transcript:
        conn.execute(
            "UPDATE knowledge_items SET content = ?, updated_at = ? WHERE id = ?",
            (transcript.strip(), utcnow_iso(), knowledge_id),
        )
        conn.commit()
    return {"configured": True, "transcript": transcript}


def get_knowledge(conn: sqlite3.Connection, knowledge_id: int) -> dict:
    row = _item_row(conn, knowledge_id)
    if not row:
        raise KnowledgeNotFound(knowledge_id)
    return knowledge_out(row, attachments=list_attachment_rows(conn, knowledge_id))


def list_knowledge(conn: sqlite3.Connection, project_id: Optional[int] = None,
                   type: Optional[str] = None, tag: Optional[str] = None,
                   q: Optional[str] = None, limit: int = 20, offset: int = 0) -> List[dict]:
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
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    if q:
        from app.services.search_service import search

        return search(conn, q, project_id=project_id, type=type, tag=tag, limit=limit, offset=offset)
    rows = conn.execute(
        f"SELECT k.*, p.name AS project_name FROM knowledge_items k"
        f" LEFT JOIN projects p ON p.id = k.project_id"
        f" {where_sql} ORDER BY k.updated_at DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return [knowledge_out(r, attachments=[], content_preview=True) for r in rows]


def get_recent(conn: sqlite3.Connection, limit: int = 20) -> List[dict]:
    rows = conn.execute(
        "SELECT k.*, p.name AS project_name FROM knowledge_items k"
        " LEFT JOIN projects p ON p.id = k.project_id"
        " ORDER BY k.created_at DESC, k.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [knowledge_out(r, attachments=[], content_preview=True) for r in rows]


def update_knowledge(conn: sqlite3.Connection, knowledge_id: int, data: KnowledgeUpdate) -> dict:
    row = _item_row(conn, knowledge_id)
    if not row:
        raise KnowledgeNotFound(knowledge_id)
    title = data.title if data.title is not None else row["title"]
    content = data.content if data.content is not None else row["content"]
    type_ = data.type if data.type is not None else row["type"]
    project_id = data.project_id if data.project_id is not None else row["project_id"]
    source = data.source if data.source is not None else row["source"]
    summary = data.summary if data.summary is not None else row["summary"]
    tags = ",".join(parse_tags(data.tags)) if data.tags is not None else row["tags"]
    if project_id is not None and not find_project(conn, project_id):
        raise ValueError(f"project_id {project_id} does not exist")
    conn.execute(
        "UPDATE knowledge_items SET title=?, content=?, type=?, project_id=?, source=?, tags=?, summary=?, updated_at=?"
        " WHERE id=?",
        (title, content, type_, project_id, source, tags, summary, utcnow_iso(), knowledge_id),
    )
    conn.commit()
    # Re-embed on edit too, or semantic search keeps matching text that is no
    # longer there — a silently wrong answer rather than a missing one.
    _maybe_embed_lesson(conn, knowledge_id, tags)
    new_row = _item_row(conn, knowledge_id)
    return knowledge_out(new_row, attachments=list_attachment_rows(conn, knowledge_id))


def delete_knowledge(conn: sqlite3.Connection, knowledge_id: int) -> dict:
    row = _item_row(conn, knowledge_id)
    if not row:
        raise KnowledgeNotFound(knowledge_id)
    out = knowledge_out(row, attachments=list_attachment_rows(conn, knowledge_id))
    delete_attachments_for_knowledge(conn, knowledge_id)
    conn.execute("DELETE FROM knowledge_items WHERE id = ?", (knowledge_id,))
    conn.commit()
    return out
