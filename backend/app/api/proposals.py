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
