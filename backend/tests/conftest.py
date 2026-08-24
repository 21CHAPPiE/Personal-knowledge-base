import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402


def pytest_configure(config):
    # Windows: the shared %TEMP%/pytest-of-* dir can be locked by other
    # processes and break tmp_path cleanup. Use a project-local dir instead.
    if not config.getoption("--basetemp"):
        config.option.basetemp = BACKEND_DIR / ".testtmp"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Isolated app instance per test: fresh data dir, no LLM/STT configured."""
    monkeypatch.setenv("KB_DATA_DIR", str(tmp_path / "data"))
    for var in ("QWEN_BASE_URL", "QWEN_API_KEY", "QWEN_MODEL",
                "STT_BASE_URL", "STT_API_KEY", "STT_MODEL", "KB_UPLOAD_MAX_BYTES"):
        monkeypatch.delenv(var, raising=False)
    from app.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def png_bytes():
    # 1x1 red PNG
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


@pytest.fixture()
def project_id(client):
    resp = client.post("/api/projects", json={"name": "Test Project", "description": "d"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]
