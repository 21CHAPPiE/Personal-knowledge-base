"""Dashboard stats route."""

import sqlite3

from fastapi import APIRouter, Depends

from app.db.database import get_db
from app.services.stats_service import get_dashboard_stats

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def stats(conn: sqlite3.Connection = Depends(get_db)):
    return get_dashboard_stats(conn)
