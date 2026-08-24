def test_append_context_creates_project_note(client, project_id):
    resp = client.post(
        f"/api/projects/{project_id}/context/append",
        json={"content": "完成了数据库设计", "source": "agent"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["type"] == "project_note"
    assert body["project_id"] == project_id
    assert body["source"] == "agent"

    items = client.get("/api/knowledge", params={"project_id": project_id}).json()
    assert any(i["id"] == body["id"] for i in items)


def test_context_returns_stats_and_recent(client, project_id):
    client.post(
        "/api/projects", json={"name": "Another"}
    )  # noise project
    client.post(
        "/api/knowledge",
        data={"title": "k1", "content": "c", "project_id": str(project_id)},
    )
    client.post(
        f"/api/projects/{project_id}/context/append",
        json={"content": "progress"},
    )
    resp = client.get(f"/api/projects/{project_id}/context")
    assert resp.status_code == 200
    body = resp.json()
    assert body["project"]["id"] == project_id
    assert body["statistics"]["total_items"] == 2
    assert body["statistics"]["by_type"].get("project_note") == 1
    assert len(body["recent_items"]) == 2
    assert isinstance(body["timeline"], list)


def test_context_missing_project_404(client):
    assert client.get("/api/projects/777/context").status_code == 404
    assert client.post(
        "/api/projects/777/context/append", json={"content": "x"}
    ).status_code == 404


def test_append_updates_project_timestamp(client, project_id):
    before = client.get(f"/api/projects/{project_id}").json()["updated_at"]
    import time

    time.sleep(1.1)
    client.post(
        f"/api/projects/{project_id}/context/append", json={"content": "tick"}
    )
    after = client.get(f"/api/projects/{project_id}").json()["updated_at"]
    assert after > before
