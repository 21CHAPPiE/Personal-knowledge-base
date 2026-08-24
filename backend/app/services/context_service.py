"""Project context: timeline, statistics, and appending project progress notes."""

import sqlite3
from typing import Optional

from app.models.schemas import ProjectContextAppend
from app.services.common import knowledge_out, project_out
from app.services.project_service import ProjectNotFound
from app.utils import utcnow_iso


def get_project_context(conn: sqlite3.Connection, project_id: int) -> dict:
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        raise ProjectNotFound(project_id)

    total = conn.execute(
        "SELECT COUNT(*) AS c FROM knowledge_items WHERE project_id = ?", (project_id,)
    ).fetchone()["c"]
    by_type = {
        r["type"]: r["c"]
        for r in conn.execute(
            "SELECT type, COUNT(*) AS c FROM knowledge_items WHERE project_id = ? GROUP BY type",
            (project_id,),
        )
    }
    first = conn.execute(
        "SELECT MIN(created_at) AS t FROM knowledge_items WHERE project_id = ?", (project_id,)
    ).fetchone()["t"]
    last = conn.execute(
        "SELECT MAX(created_at) AS t FROM knowledge_items WHERE project_id = ?", (project_id,)
    ).fetchone()["t"]

    recent = conn.execute(
        "SELECT k.*, p.name AS project_name FROM knowledge_items k"
        " LEFT JOIN projects p ON p.id = k.project_id"
        " WHERE k.project_id = ? ORDER BY k.updated_at DESC, k.id DESC LIMIT 20",
        (project_id,),
    ).fetchall()
    recent_items = [knowledge_out(r, attachments=[], content_preview=True) for r in recent]

    # Timeline: last 30 days, grouped by day
    since = conn.execute("SELECT date('now', '-29 days') AS d").fetchone()["d"]
    timeline_rows = conn.execute(
        "SELECT date(created_at) AS day, COUNT(*) AS c FROM knowledge_items"
        " WHERE project_id = ? AND date(created_at) >= ? GROUP BY day ORDER BY day",
        (project_id, since),
    ).fetchall()
    timeline = [{"date": r["day"], "count": r["c"]} for r in timeline_rows]

    return {
        "project": project_out(project),
        "statistics": {
            "total_items": total,
            "by_type": by_type,
            "first_activity": first,
            "last_activity": last,
        },
        "timeline": timeline,
        "recent_items": recent_items,
    }


def append_project_context(conn: sqlite3.Connection, project_id: int, data: ProjectContextAppend) -> dict:
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not project:
        raise ProjectNotFound(project_id)
    now = utcnow_iso()
    title = (data.title or f"进展 {now[:10]}").strip()[:200]
    cur = conn.execute(
        "INSERT INTO knowledge_items (project_id, type, title, content, source, tags, summary, created_at, updated_at)"
        " VALUES (?, 'project_note', ?, ?, ?, '', NULL, ?, ?)",
        (project_id, title, data.content, data.source or "agent", now, now),
    )
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
    conn.commit()
    row = conn.execute(
        "SELECT k.*, p.name AS project_name FROM knowledge_items k"
        " LEFT JOIN projects p ON p.id = k.project_id WHERE k.id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return knowledge_out(row, attachments=[])
