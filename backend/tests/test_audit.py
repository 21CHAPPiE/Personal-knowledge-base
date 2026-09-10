"""The access log: what it records, and what it refuses to pretend."""


def test_requests_are_recorded_with_the_caller_they_claim(client):
    client.post("/api/knowledge", data={"title": "T", "content": "c"},
                headers={"X-KB-Agent": "claude-opus-5", "X-KB-Machine": "X99/b3c9c3"})

    entries = client.get("/api/audit").json()["entries"]
    write = next(e for e in entries if e["method"] == "POST")
    assert write["path"] == "/api/knowledge"
    assert write["status"] == 201
    assert write["agent"] == "claude-opus-5"
    assert write["machine"] == "X99/b3c9c3"


def test_an_unnamed_caller_is_marked_as_such(client):
    client.get("/api/stats")
    entry = client.get("/api/audit").json()["entries"][0]
    assert entry["agent"] == "未声明", (
        "a caller that names no one must read as unnamed, not as trusted")


def test_rejected_requests_are_recorded_too(client, monkeypatch):
    """A refused call is exactly the kind of thing worth a record."""
    monkeypatch.setenv("KB_API_TOKEN", "sekret")
    assert client.get("/api/stats", headers={"Authorization": "Bearer wrong"}).status_code == 401
    monkeypatch.delenv("KB_API_TOKEN")

    entry = next(e for e in client.get("/api/audit").json()["entries"]
                 if e["path"] == "/api/stats")
    assert entry["status"] == 401


def test_writes_only_filter(client):
    client.get("/api/stats")
    client.post("/api/knowledge", data={"title": "T", "content": "c"})

    entries = client.get("/api/audit?writes_only=true").json()["entries"]
    assert entries and all(e["method"] not in ("GET", "HEAD") for e in entries)


def test_health_and_the_log_itself_are_not_logged(client):
    """Otherwise uptime checks bury the record, and reading the log becomes an
    entry in the log."""
    client.get("/health")
    client.get("/api/audit")
    paths = [e["path"] for e in client.get("/api/audit").json()["entries"]]
    assert "/health" not in paths
    assert "/api/audit" not in paths


def test_filter_by_agent(client):
    client.post("/api/knowledge", data={"title": "A", "content": "c"},
                headers={"X-KB-Agent": "codex"})
    client.post("/api/knowledge", data={"title": "B", "content": "c"},
                headers={"X-KB-Agent": "claude-opus-5"})

    entries = client.get("/api/audit?agent=codex").json()["entries"]
    assert entries and all(e["agent"] == "codex" for e in entries)


def test_the_response_says_the_caller_is_unverified(client):
    body = client.get("/api/audit").json()
    assert "未经验证" in body["note"], (
        "self-reported identity has to be labelled as such wherever it is shown")


def test_a_broken_log_never_breaks_a_request(client, tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    monkeypatch.setattr("app.audit.log_path", lambda: blocker / "nested" / "access.jsonl")

    assert client.get("/api/stats").status_code == 200, (
        "losing an audit line is bad; refusing to serve the knowledge base is worse")
