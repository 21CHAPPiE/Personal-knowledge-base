"""Serve this project's own install path over HTTP, independent of GitHub.

A brand-new machine bootstrapping this knowledge base for the first time
needs to fetch two things before Claude Code can discover the `kb` Skill:
the tiny installer script, and `skills/kb/SKILL.md` itself. The obvious
place for both is GitHub raw, but that stops working the moment this repo's
visibility changes to private, or if GitHub is unreachable from that
machine — and this project has already been bitten once by assuming a
public repo would stay that way. The backend is a source every install is
already configuring anyway (the whole point of running the installer is to
know its address), so serving both from here removes the last GitHub
dependency from the install path entirely.

`/kb` (the Skill content) sits behind the same shared-secret auth as
everything else in this API — the install flow already asks for
`KB_API_TOKEN` before it gets here, so there is no ordering problem, and
leaving it open would let anyone who finds the URL read internal API usage
details for free. `/install.sh` and `/install.ps1` cannot be behind that
auth: they are the *first* thing a machine with zero prior setup fetches,
before any token exists to send. They carry no secret — install logic
only — so that is the same tradeoff `/health` already makes, and `main.py`
exempts them from `require_api_token` the same way.
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.config import REPO_ROOT

router = APIRouter(prefix="/api/skill", tags=["skill"])

SKILL_PATH = REPO_ROOT / "skills" / "kb" / "SKILL.md"
INSTALL_SH_PATH = REPO_ROOT / "scripts" / "install_kb_skill.sh"
INSTALL_PS1_PATH = REPO_ROOT / "scripts" / "install_kb_skill.ps1"


def _read_or_404(path):
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"{path.name} not found on this backend: {exc}")


@router.get("/kb", response_class=PlainTextResponse)
def get_kb_skill():
    return _read_or_404(SKILL_PATH)


# Unauthenticated by design — see module docstring. Exempted from
# require_api_token in app/main.py alongside /health.
@router.get("/install.sh", response_class=PlainTextResponse)
def get_install_sh():
    return _read_or_404(INSTALL_SH_PATH)


@router.get("/install.ps1", response_class=PlainTextResponse)
def get_install_ps1():
    return _read_or_404(INSTALL_PS1_PATH)
