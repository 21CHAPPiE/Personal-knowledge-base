"""LLM provider routes: status, summarize, suggest-tags.

All endpoints work without QWEN_* configured (Noop fallback), and report which
provider produced the result so the UI can be honest about it.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db.database import get_db
from app.models.schemas import LogicGroupsRequest, SummarizeRequest, SuggestTagsRequest
from app.providers.factory import get_llm_provider
from app.providers.qwen import LLMProviderError
from app.utils import parse_tags, utcnow_iso

router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.get("/status")
def status():
    provider = get_llm_provider()
    stt = get_stt_status()
    return {
        "llm": {
            "configured": provider.is_configured(),
            "provider": provider.name,
            "model": getattr(provider, "model", None),
        },
        "stt": stt,
    }


def get_stt_status() -> dict:
    from app.providers.factory import get_stt_provider

    provider = get_stt_provider()
    return {
        "configured": provider.is_configured(),
        "provider": provider.name,
        "model": getattr(provider, "model", None),
    }


def _get_item(conn: sqlite3.Connection, knowledge_id: int):
    row = conn.execute("SELECT * FROM knowledge_items WHERE id = ?", (knowledge_id,)).fetchone()
    if not row:
        raise HTTPException(404, f"knowledge {knowledge_id} not found")
    return row


@router.post("/summarize")
def summarize(data: SummarizeRequest, conn: sqlite3.Connection = Depends(get_db)):
    row = _get_item(conn, data.knowledge_id)
    provider = get_llm_provider()
    try:
        summary = provider.summarize(row["title"], row["content"])
        err = None
    except LLMProviderError as exc:
        if not data.fallback:
            raise HTTPException(502, f"llm provider failed: {exc}")
        from app.providers.base import NoopLLMProvider

        summary = NoopLLMProvider().summarize(row["title"], row["content"])
        err = str(exc)
    conn.execute(
        "UPDATE knowledge_items SET summary = ?, updated_at = ? WHERE id = ?",
        (summary, utcnow_iso(), row["id"]),
    )
    conn.commit()
    return {
        "knowledge_id": row["id"],
        "summary": summary,
        "provider": provider.name,
        "fallback": not provider.is_configured() or err is not None,
        "error": err,
    }


@router.post("/logic-groups")
def logic_groups(data: LogicGroupsRequest):
    """Group items by shared underlying logic (根因/动机/因果), not shared
    topic — the maintenance script's building block for the "propose a
    cross-reference" pass. Never writes anything itself; the caller decides
    what to do with the groups (kb_maintenance.py turns them into
    kind:proposal entries for a person to review).
    """
    provider = get_llm_provider()
    if not provider.is_configured() or len(data.items) < 2:
        return {"groups": [], "provider": provider.name}
    try:
        groups = provider.find_logic_groups(
            [item.model_dump() for item in data.items], context=data.context)
    except LLMProviderError as exc:
        return {"groups": [], "provider": provider.name, "error": str(exc)}
    return {"groups": groups, "provider": provider.name}


@router.post("/suggest-tags")
def suggest_tags(data: SuggestTagsRequest, conn: sqlite3.Connection = Depends(get_db)):
    row = _get_item(conn, data.knowledge_id)
    provider = get_llm_provider()
    try:
        tags = provider.suggest_tags(row["title"], row["content"])
        err = None
    except LLMProviderError as exc:
        if not data.fallback:
            raise HTTPException(502, f"llm provider failed: {exc}")
        from app.providers.base import NoopLLMProvider

        tags = NoopLLMProvider().suggest_tags(row["title"], row["content"])
        err = str(exc)
    if data.apply:
        merged = parse_tags(list(parse_tags(row["tags"])) + tags)
        conn.execute(
            "UPDATE knowledge_items SET tags = ?, updated_at = ? WHERE id = ?",
            (",".join(merged), utcnow_iso(), row["id"]),
        )
        conn.commit()
        tags = merged
    return {
        "knowledge_id": row["id"],
        "tags": tags,
        "provider": provider.name,
        "fallback": not provider.is_configured() or err is not None,
        "error": err,
    }
