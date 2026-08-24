"""Dashboard statistics."""

import sqlite3
from datetime import datetime, timedelta, timezone

from app.services.common import knowledge_out, project_out


def get_dashboard_stats(conn: sqlite3.Connection) -> dict:
    # "today" = since local midnight, converted to a UTC cutoff (personal-scale approximation)
    local_midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since_utc = (local_midnight - local_midnight.utcoffset()).strftime("%Y-%m-%dT%H:%M:%SZ")

    today_count = conn.execute(
        "SELECT COUNT(*) AS c FROM knowledge_items WHERE created_at >= ?", (since_utc,)
    ).fetchone()["c"]
    total_items = conn.execute("SELECT COUNT(*) AS c FROM knowledge_items").fetchone()["c"]
    total_projects = conn.execute("SELECT COUNT(*) AS c FROM projects").fetchone()["c"]

    recent = conn.execute(
        "SELECT k.*, p.name AS project_name FROM knowledge_items k"
        " LEFT JOIN projects p ON p.id = k.project_id"
        " ORDER BY k.created_at DESC, k.id DESC LIMIT 10",
    ).fetchall()
    recent_items = [knowledge_out(r, attachments=[], content_preview=True) for r in recent]

    updated_projects = conn.execute(
        "SELECT * FROM projects ORDER BY updated_at DESC LIMIT 5"
    ).fetchall()
    project_rows = [project_out(r) for r in updated_projects]

    return {
        "today_count": today_count,
        "total_items": total_items,
        "total_projects": total_projects,
        "recent_items": recent_items,
        "updated_projects": project_rows,
    }
