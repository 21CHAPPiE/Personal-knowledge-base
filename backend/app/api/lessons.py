"""Lesson routes: match a situation against lessons already recorded."""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.db.database import get_db
from app.providers.factory import get_embedding_provider
from app.services.lesson_service import LESSON_TAG, embed_lesson, match_lessons
from app.utils import parse_tags

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


@router.get("/status")
def status_route(conn: sqlite3.Connection = Depends(get_db)):
    provider = get_embedding_provider()
    lessons = conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_items WHERE (',' || tags || ',') LIKE ?",
        ["%,{},%".format(LESSON_TAG)],
    ).fetchone()["n"]
    embedded = conn.execute(
        "SELECT COUNT(*) AS n FROM knowledge_embeddings e"
        " JOIN knowledge_items k ON k.id = e.knowledge_id"
        " WHERE (',' || k.tags || ',') LIKE ?",
        ["%,{},%".format(LESSON_TAG)],
    ).fetchone()["n"]
    return {
        "embedding": {
            "configured": provider.is_configured(),
            "provider": provider.name,
            "model": getattr(provider, "model", None),
        },
        "lessons": lessons,
        "embedded": embedded,
    }


@router.post("/reindex")
def reindex_route(conn: sqlite3.Connection = Depends(get_db)):
    """Backfill vectors for lessons that have none (or were embedded by an
    older model). Safe to re-run; skips nothing silently."""
    provider = get_embedding_provider()
    if not provider.is_configured():
        return {"embedded": 0, "failed": 0, "skipped": 0,
                "detail": "no embedding provider configured"}
    rows = conn.execute(
        "SELECT k.id FROM knowledge_items k"
        " LEFT JOIN knowledge_embeddings e ON e.knowledge_id = k.id"
        " WHERE (',' || k.tags || ',') LIKE ?"
        " AND (e.knowledge_id IS NULL OR e.model != ?)",
        ["%,{},%".format(LESSON_TAG), provider.model],
    ).fetchall()
    embedded = failed = 0
    for row in rows:
        if embed_lesson(conn, row["id"]):
            embedded += 1
        else:
            failed += 1
    return {"embedded": embedded, "failed": failed, "model": provider.model}


@router.get("/match")
def match_route(
    signature: str = Query(..., min_length=1, max_length=500),
    os: Optional[str] = None,
    machine: Optional[str] = None,
    stack: Optional[str] = None,
    project_id: Optional[int] = None,
    limit: int = Query(10, ge=1, le=50),
    conn: sqlite3.Connection = Depends(get_db),
):
    return match_lessons(
        conn,
        signature,
        os_name=os,
        machine=machine,
        stack=parse_tags(stack) if stack else None,
        project_id=project_id,
        limit=limit,
    )
