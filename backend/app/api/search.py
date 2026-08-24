"""Search routes."""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.db.database import get_db
from app.services.search_service import search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search_route(
    q: str = Query(..., min_length=1, max_length=200),
    project_id: Optional[int] = None,
    type: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
):
    return search(conn, q, project_id=project_id, type=type, tag=tag, limit=limit, offset=offset)
