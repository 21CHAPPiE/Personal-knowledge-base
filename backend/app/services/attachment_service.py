"""Attachment storage: validation, safe file naming, path-traversal guards."""

import os
import re
import sqlite3
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from app.config import get_settings
from app.services.common import attachment_out
from app.utils import sanitize_original_name, utcnow_iso

# (ext, mime) whitelist. First matching signature wins; fallback = declared mime.
IMAGE_EXTS = ("png", "jpg", "jpeg", "gif", "webp", "bmp")
AUDIO_EXTS = ("mp3", "wav", "ogg", "oga", "webm", "m4a", "aac", "opus", "flac")
VIDEO_EXTS = ("mp4", "mov", "webm")
DOC_EXTS = ("pdf", "txt", "md", "json", "csv")
ALLOWED_EXTS = IMAGE_EXTS + AUDIO_EXTS + VIDEO_EXTS + DOC_EXTS

MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"RIFF", "image/webp"),  # RIFF....WEBP
    (b"BM", "image/bmp"),
    (b"%PDF", "application/pdf"),
    (b"OggS", "audio/ogg"),
    (b"ID3", "audio/mpeg"),
    (b"fLaC", "audio/flac"),
)


class AttachmentError(Exception):
    pass


class FileTooLarge(AttachmentError):
    pass


class BadExtension(AttachmentError):
    pass


def _sniff_mime(head: bytes) -> Optional[str]:
    for magic, mime in MAGIC:
        if head.startswith(magic):
            if mime == "image/webp" and head[8:12] != b"WEBP":
                continue
            return mime
    return None


def _ext_of(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_and_store(knowledge_id: int, filename: str, data: bytes, declared_mime: str) -> Tuple[str, str, str]:
    """Validate and persist one upload. Returns (stored_name, file_path_rel, final_mime).

    Raises AttachmentError subclasses on bad input.
    """
    settings = get_settings()
    if not data:
        raise AttachmentError("empty file")
    if len(data) > settings.upload_max_bytes:
        raise FileTooLarge(len(data), settings.upload_max_bytes)

    original = sanitize_original_name(filename)
    ext = _ext_of(original)
    if ext not in ALLOWED_EXTS:
        raise BadExtension(ext or "(none)", ALLOWED_EXTS)

    final_mime = _sniff_mime(data[:16]) or declared_mime or "application/octet-stream"
    # webm (RIFF) and mp4 (ftyp) share no simple magic; trust declared mime for those
    if ext in VIDEO_EXTS and not final_mime.startswith("video/"):
        final_mime = declared_mime if declared_mime.startswith("video/") else f"video/{ext}"

    stored_name = uuid.uuid4().hex[:12] + "." + ext
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    target = (settings.uploads_dir / stored_name).resolve()
    uploads_root = settings.uploads_dir.resolve()
    # Path-traversal guard: stored_name is uuid+ext, but verify anyway.
    if not str(target).startswith(str(uploads_root) + os.sep):
        raise AttachmentError(f"stored path escaped uploads root: {target}")
    target.write_bytes(data)
    return stored_name, stored_name, final_mime


def create_attachment(conn: sqlite3.Connection, knowledge_id: int, filename: str,
                      data: bytes, declared_mime: str) -> dict:
    stored_name, file_path, final_mime = validate_and_store(knowledge_id, filename, data, declared_mime)
    cur = conn.execute(
        "INSERT INTO attachments (knowledge_id, filename, stored_name, mime_type, file_path, size_bytes, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (knowledge_id, sanitize_original_name(filename), stored_name, final_mime, file_path, len(data), utcnow_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (cur.lastrowid,)).fetchone()
    return attachment_out(row)


def list_attachments(conn: sqlite3.Connection, knowledge_id: int) -> List[dict]:
    return [attachment_out(r) for r in list_attachment_rows(conn, knowledge_id)]


def list_attachment_rows(conn: sqlite3.Connection, knowledge_id: int) -> List[sqlite3.Row]:
    """Raw rows for internal composition (e.g. knowledge_out serialization)."""
    return conn.execute(
        "SELECT * FROM attachments WHERE knowledge_id = ? ORDER BY id", (knowledge_id,)
    ).fetchall()


def get_attachment(conn: sqlite3.Connection, attachment_id: int) -> dict:
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not row:
        return None
    return attachment_out(row)


def attachment_file_path(row: sqlite3.Row) -> Path:
    """Resolve an attachment row to a filesystem path, guarding traversal."""
    settings = get_settings()
    rel = str(row["file_path"]).replace("\\", "/").lstrip("/")
    if rel.startswith("..") or rel.startswith("/"):
        raise AttachmentError(f"bad stored path: {row['file_path']}")
    full = (settings.uploads_dir / rel).resolve()
    root = settings.uploads_dir.resolve()
    if not str(full).startswith(str(root) + os.sep) and full != root:
        raise AttachmentError(f"attachment path escaped uploads root: {full}")
    return full


def delete_attachment_file(row: sqlite3.Row) -> None:
    try:
        path = attachment_file_path(row)
        if path.exists():
            path.unlink()
    except AttachmentError:
        pass  # best effort; DB row removal is the source of truth


def delete_attachments_for_knowledge(conn: sqlite3.Connection, knowledge_id: int) -> None:
    """Delete rows + files for a knowledge item (used before/after item delete)."""
    rows = conn.execute(
        "SELECT * FROM attachments WHERE knowledge_id = ?", (knowledge_id,)
    ).fetchall()
    for r in rows:
        delete_attachment_file(r)
    conn.execute("DELETE FROM attachments WHERE knowledge_id = ?", (knowledge_id,))
    conn.commit()


def delete_attachment(conn: sqlite3.Connection, attachment_id: int) -> Optional[dict]:
    row = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
    if not row:
        return None
    delete_attachment_file(row)
    conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    conn.commit()
    return attachment_out(row)
