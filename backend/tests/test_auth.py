from fastapi.testclient import TestClient


def _client_with_token(tmp_path, monkeypatch, token="secret123"):
    monkeypatch.setenv("KB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("KB_API_TOKEN", token)
    from app.main import create_app

    return TestClient(create_app())


def test_no_token_configured_allows_all(client):
    # Default fixture has no KB_API_TOKEN set: back-compat, nothing to prove
    # beyond "still works", covered by every other test file already.
    resp = client.get("/health")
    assert resp.status_code == 200


def test_missing_header_rejected(tmp_path, monkeypatch):
    with _client_with_token(tmp_path, monkeypatch) as c:
        resp = c.get("/api/knowledge")
        assert resp.status_code == 401


def test_wrong_token_rejected(tmp_path, monkeypatch):
    with _client_with_token(tmp_path, monkeypatch) as c:
        resp = c.get("/api/knowledge", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401


def test_correct_token_allowed(tmp_path, monkeypatch):
    with _client_with_token(tmp_path, monkeypatch) as c:
        resp = c.get("/api/knowledge", headers={"Authorization": "Bearer secret123"})
        assert resp.status_code == 200


def test_health_open_even_with_token(tmp_path, monkeypatch):
    with _client_with_token(tmp_path, monkeypatch) as c:
        resp = c.get("/health")
        assert resp.status_code == 200


def test_uploads_protected_when_token_set(tmp_path, monkeypatch):
    with _client_with_token(tmp_path, monkeypatch) as c:
        resp = c.get("/uploads/does-not-exist.png")
        assert resp.status_code == 401
