"""Lesson routes: match a situation against lessons already recorded."""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.db.database import get_db
from app.services.lesson_service import match_lessons
from app.utils import parse_tags

router = APIRouter(prefix="/api/lessons", tags=["lessons"])


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
