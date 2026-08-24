"""Knowledge routes (list/create/detail/patch/delete, attachments, recent)."""

import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.db.database import get_db
from app.models.schemas import KnowledgeCreate, KnowledgeUpdate
from app.services import attachment_service, knowledge_service

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


def _validate_upload(upload: UploadFile, max_bytes: int) -> dict:
    data = upload.file.read()
    if len(data) > max_bytes:
        raise HTTPException(413, f"file larger than {max_bytes} bytes")
    mime = (upload.content_type or "").split(";")[0].strip()
    return {"name": upload.filename or "file", "bytes": data, "mime": mime}


@router.get("/recent")
def recent(limit: int = Query(20, ge=1, le=100), conn: sqlite3.Connection = Depends(get_db)):
    return knowledge_service.get_recent(conn, limit)


@router.get("")
def list_knowledge(
    project_id: Optional[int] = None,
    type: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
):
    return knowledge_service.list_knowledge(
        conn, project_id=project_id, type=type, tag=tag, q=q, limit=limit, offset=offset
    )


@router.post("", status_code=201)
def create_knowledge(
    title: str = Form(..., min_length=1, max_length=200),
    content: str = Form("", max_length=50000),
    type: str = Form("text", pattern="^(text|voice|screenshot|project_note)$"),
    project_id: Optional[int] = Form(None),
    tags: List[str] = Form(default=[]),
    source: str = Form("manual", max_length=60),
    file: Optional[UploadFile] = File(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    data = KnowledgeCreate(
        title=title, content=content, type=type, project_id=project_id,
        tags=tags, source=source,
    )
    upload = _validate_upload(file, 10 * 1024 * 1024) if file is not None else None
    try:
        return knowledge_service.create_knowledge(conn, data, file=upload)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/{knowledge_id}")
def get_knowledge(knowledge_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return knowledge_service.get_knowledge(conn, knowledge_id)
    except knowledge_service.KnowledgeNotFound:
        raise HTTPException(404, f"knowledge {knowledge_id} not found")


@router.patch("/{knowledge_id}")
def update_knowledge(knowledge_id: int, data: KnowledgeUpdate, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return knowledge_service.update_knowledge(conn, knowledge_id, data)
    except knowledge_service.KnowledgeNotFound:
        raise HTTPException(404, f"knowledge {knowledge_id} not found")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/{knowledge_id}")
def delete_knowledge(knowledge_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return knowledge_service.delete_knowledge(conn, knowledge_id)
    except knowledge_service.KnowledgeNotFound:
        raise HTTPException(404, f"knowledge {knowledge_id} not found")


@router.get("/{knowledge_id}/attachments")
def list_attachments(knowledge_id: int, conn: sqlite3.Connection = Depends(get_db)):
    row = conn.execute("SELECT id FROM knowledge_items WHERE id = ?", (knowledge_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"knowledge {knowledge_id} not found")
    return attachment_service.list_attachments(conn, knowledge_id)


@router.post("/{knowledge_id}/attachments", status_code=201)
def upload_attachment(
    knowledge_id: int,
    file: UploadFile = File(...),
    conn: sqlite3.Connection = Depends(get_db),
):
    from app.config import get_settings

    row = conn.execute("SELECT id FROM knowledge_items WHERE id = ?", (knowledge_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"knowledge {knowledge_id} not found")
    settings = get_settings()
    upload = _validate_upload(file, settings.upload_max_bytes)
    try:
        return attachment_service.create_attachment(conn, knowledge_id, upload["name"], upload["bytes"], upload["mime"])
    except attachment_service.FileTooLarge:
        raise HTTPException(413, f"file larger than {settings.upload_max_bytes} bytes")
    except attachment_service.BadExtension as exc:
        raise HTTPException(415, f"unsupported extension: {exc}")
    except attachment_service.AttachmentError as exc:
        raise HTTPException(400, str(exc))
