"""Shared row-serialization helpers for service layer."""

import sqlite3
from typing import Optional

from app.utils import parse_tags


def project_out(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def attachment_out(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "knowledge_id": row["knowledge_id"],
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "size_bytes": row["size_bytes"],
        "url": f"/uploads/{row['stored_name']}",
        "created_at": row["created_at"],
    }


def knowledge_out(row: sqlite3.Row, attachments=None, content_preview: bool = False) -> dict:
    out = {
        "id": row["id"],
        "project_id": row["project_id"],
        "project_name": row["project_name"] if "project_name" in row.keys() else None,
        "type": row["type"],
        "title": row["title"],
        "content": row["content"],
        "source": row["source"],
        "tags": parse_tags(row["tags"]),
        "summary": row["summary"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "attachments": [attachment_out(a) for a in (attachments or [])],
    }
    if content_preview:
        text = (row["content"] or "").strip()
        out["content_preview"] = text[:200] + ("…" if len(text) > 200 else "")
    return out


def find_project(conn: sqlite3.Connection, project_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()


def find_project_by_name(conn: sqlite3.Connection, name: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM projects WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
