"""Review queue: what is waiting for a decision, and recording that decision.

Kept separate from /api/knowledge because a proposal is not just another item
to read — it is a question addressed to a person, and answering it changes
other items. The one endpoint that answers it is shared by the UI and by the
automated pass, so both land in the same audit trail.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db.database import get_db
from app.models.schemas import DecideRequest, RubricCriteriaRequest
from app.services import review_service

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


@router.get("")
def list_pending(limit: int = 50, conn: sqlite3.Connection = Depends(get_db)):
    return review_service.pending(conn, limit=limit)


@router.get("/rubric")
def get_rubric(conn: sqlite3.Connection = Depends(get_db)):
    from app.services.common import knowledge_out

    rubric = review_service.get_or_create_rubric(conn)
    return {
        "item": knowledge_out(rubric, attachments=[]),
        "criteria": review_service.rubric_criteria(conn),
        "decisions": review_service.decision_log(conn),
    }


@router.put("/rubric")
def put_rubric(data: RubricCriteriaRequest, conn: sqlite3.Connection = Depends(get_db)):
    return review_service.set_criteria(conn, data.criteria)


@router.post("/rubric/synthesize")
def synthesize_rubric(conn: sqlite3.Connection = Depends(get_db)):
    """Propose a criteria section derived from the decisions so far.

    Returns it rather than saving it: a standard the reviewer hasn't read is
    not a standard they agreed to, and the first one especially should be
    looked at before anything starts being decided by it.
    """
    from app.providers.factory import get_llm_provider

    provider = get_llm_provider()
    decisions = [d for d in review_service.decisions_with_context(conn) if d["logic"]]
    if not provider.is_configured() or len(decisions) < 4:
        return {"criteria": "", "provider": provider.name, "decisions": len(decisions)}
    try:
        criteria = provider.synthesize_rubric(decisions)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"llm provider failed: {exc}")
    return {"criteria": criteria, "provider": provider.name, "decisions": len(decisions)}


@router.get("/{proposal_id}/items")
def proposal_items(proposal_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        return review_service.referenced_items(conn, proposal_id)
    except review_service.ProposalNotFound:
        raise HTTPException(404, f"proposal {proposal_id} not found")


@router.post("/{proposal_id}/decide")
def decide(proposal_id: int, data: DecideRequest,
           conn: sqlite3.Connection = Depends(get_db)):
    if data.verdict not in ("approve", "dismiss"):
        raise HTTPException(422, "verdict must be approve or dismiss")
    try:
        return review_service.decide(conn, proposal_id, data.verdict,
                                     note=data.note, by=data.by)
    except review_service.ProposalNotFound:
        raise HTTPException(404, f"proposal {proposal_id} not found")
