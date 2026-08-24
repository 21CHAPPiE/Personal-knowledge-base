"""Project CRUD."""

import sqlite3
from typing import List, Optional

from app.models.schemas import ProjectCreate, ProjectUpdate
from app.services.common import find_project, find_project_by_name, project_out
from app.utils import utcnow_iso


class ProjectNotFound(Exception):
    pass


class ProjectNameConflict(Exception):
    pass


class ProjectExistsError(Exception):
    pass


def create_project(conn: sqlite3.Connection, data: ProjectCreate) -> dict:
    if find_project_by_name(conn, data.name):
        raise ProjectNameConflict(data.name)
    now = utcnow_iso()
    cur = conn.execute(
        "INSERT INTO projects (name, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (data.name, data.description, data.status, now, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return project_out(row)


def list_projects(conn: sqlite3.Connection, status: Optional[str] = None) -> List[dict]:
    if status:
        rows = conn.execute(
            "SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [project_out(r) for r in rows]


def get_project(conn: sqlite3.Connection, project_id: int) -> dict:
    row = find_project(conn, project_id)
    if not row:
        raise ProjectNotFound(project_id)
    return project_out(row)


def update_project(conn: sqlite3.Connection, project_id: int, data: ProjectUpdate) -> dict:
    row = find_project(conn, project_id)
    if not row:
        raise ProjectNotFound(project_id)
    name = data.name if data.name is not None else row["name"]
    description = data.description if data.description is not None else row["description"]
    status = data.status if data.status is not None else row["status"]
    if name != row["name"]:
        clash = conn.execute(
            "SELECT id FROM projects WHERE name = ? COLLATE NOCASE AND id != ?", (name, project_id)
        ).fetchone()
        if clash:
            raise ProjectNameConflict(name)
    conn.execute(
        "UPDATE projects SET name = ?, description = ?, status = ?, updated_at = ? WHERE id = ?",
        (name, description, status, utcnow_iso(), project_id),
    )
    conn.commit()
    return project_out(find_project(conn, project_id))


def delete_project(conn: sqlite3.Connection, project_id: int) -> dict:
    row = find_project(conn, project_id)
    if not row:
        raise ProjectNotFound(project_id)
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    return project_out(row)
