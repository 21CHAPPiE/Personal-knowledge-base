"""LLM provider routes: status, summarize, suggest-tags.

All endpoints work without QWEN_* configured (Noop fallback), and report which
provider produced the result so the UI can be honest about it.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db.database import get_db
from app.models.schemas import (DiscriminationRequest, LogicGroupsRequest,
                                MatchPatternsRequest, SummarizeRequest,
                                SuggestTagsRequest)
from app.providers.factory import get_llm_provider, get_rerank_provider
from app.providers.qwen import LLMProviderError
from app.utils import parse_tags, utcnow_iso

router = APIRouter(prefix="/api/llm", tags=["llm"])

DISCRIMINATION_CHUNK = 50


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


@router.post("/abstract-patterns")
def abstract_patterns(data: LogicGroupsRequest):
    """Pass 1 of two: each item reduced to a de-identified structural pattern.

    Split from matching on purpose — the labels are the expensive part and
    they are stable, so a later run only has to label what is new and can
    reuse the rest.
    """
    provider = get_llm_provider()
    if not provider.is_configured() or not data.items:
        return {"patterns": [], "provider": provider.name}
    try:
        patterns = provider.abstract_patterns([item.model_dump() for item in data.items])
    except LLMProviderError as exc:
        return {"patterns": [], "provider": provider.name, "error": str(exc)}
    return {"patterns": patterns, "provider": provider.name}


@router.post("/match-patterns")
def match_patterns(data: MatchPatternsRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Pass 2 of two: the same structure showing up in unrelated places.

    Compares only the labels from pass 1, never the source text, which is
    what keeps "these are consecutive scenes" from being the easy answer.
    """
    provider = get_llm_provider()
    if not provider.is_configured() or len(data.patterns) < 2:
        return {"groups": [], "provider": provider.name}
    from app.services.review_service import rubric_criteria

    try:
        groups = provider.match_patterns([p.model_dump() for p in data.patterns],
                                         rubric=rubric_criteria(conn))
    except LLMProviderError as exc:
        return {"groups": [], "provider": provider.name, "error": str(exc)}
    return {"groups": groups, "provider": provider.name}


@router.post("/discrimination")
def discrimination(data: DiscriminationRequest):
    """Does this statement actually single out the items it claims, or does it
    fit everything equally?

    "Vacuous" can't be measured directly, but it has an operational shape: a
    sentence that fits anything rates every candidate about the same, while a
    sentence with content rates a few far above the rest. So the statement is
    scored against the whole corpus and two things are reported — where the
    items it claims to describe actually landed, and how far the top score
    sits above the median. A claimed item at the middle of the ranking is
    indistinguishable from one picked at random, which is worth knowing
    before trusting the group it sits in.

    This checks for vacuity, not for truth: a statement can single out its own
    members perfectly and still be a worthless observation ("these all happen
    indoors"). Judging whether it says anything worth saying stays with the
    reader.
    """
    provider = get_rerank_provider()
    if not provider.is_configured() or not data.candidates or not data.statement.strip():
        return {"available": False}

    # Chunked because a cross-encoder scores each pair independently, so the
    # split costs nothing — and a whole corpus in one request does not fit
    # under the provider timeout. Measured here: 197 documents took 64s
    # against a 60s limit, and the only symptom was the check silently
    # reporting itself unavailable.
    scores = []
    for start in range(0, len(data.candidates), DISCRIMINATION_CHUNK):
        chunk = data.candidates[start:start + DISCRIMINATION_CHUNK]
        part = provider.rerank(data.statement, [c.text for c in chunk])
        if part is None:
            return {"available": False}
        scores += part

    pairs = sorted(zip(data.candidates, scores), key=lambda p: p[1], reverse=True)
    rank_of = {c.id: i + 1 for i, (c, _s) in enumerate(pairs)}
    ordered = sorted(scores, reverse=True)
    median = ordered[len(ordered) // 2]
    return {
        "available": True,
        "total": len(scores),
        "spread": round(ordered[0] - median, 2),
        "claimed_ranks": [{"id": kid, "rank": rank_of.get(kid)} for kid in data.claimed],
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
