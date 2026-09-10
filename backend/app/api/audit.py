"""Reading the access log back out.

Separate from the knowledge routes because this is not knowledge: it is the
record of who claimed to be doing what to it, which is only useful if it sits
outside the thing it describes.
"""

from typing import Optional

from fastapi import APIRouter

from app import audit

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
def list_access(limit: int = 200, agent: Optional[str] = None,
                writes_only: bool = False):
    entries = audit.read(limit=limit, agent=agent, writes_only=writes_only)
    return {
        "entries": entries,
        "note": "agent/machine 由调用方自行声明，未经验证；本日志证明请求发生过，不证明调用者身份",
    }
