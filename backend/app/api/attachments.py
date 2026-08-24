"""Attachment routes (metadata + delete; file bytes are served from /uploads)."""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db.database import get_db
from app.services import attachment_service

router = APIRouter(prefix="/api/attachments", tags=["attachments"])


@router.get("/{attachment_id}")
def get_attachment_meta(attachment_id: int, conn: sqlite3.Connection = Depends(get_db)):
    att = attachment_service.get_attachment(conn, attachment_id)
    if not att:
        raise HTTPException(404, f"attachment {attachment_id} not found")
    return att


@router.delete("/{attachment_id}")
def delete_attachment(attachment_id: int, conn: sqlite3.Connection = Depends(get_db)):
    att = attachment_service.delete_attachment(conn, attachment_id)
    if not att:
        raise HTTPException(404, f"attachment {attachment_id} not found")
    return att
