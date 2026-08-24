def test_create_and_get_knowledge(client):
    resp = client.post(
        "/api/knowledge",
        data={"title": "Note", "content": "hello world", "tags": ["a", "b"]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["type"] == "text"
    assert body["tags"] == ["a", "b"]
    kid = body["id"]

    got = client.get(f"/api/knowledge/{kid}")
    assert got.status_code == 200
    assert got.json()["content"] == "hello world"


def test_knowledge_with_project_and_tags(client, project_id):
    resp = client.post(
        "/api/knowledge",
        data={"title": "proj note", "content": "x", "project_id": str(project_id), "tags": "t1, t2"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["project_id"] == project_id
    assert body["project_name"] == "Test Project"
    assert body["tags"] == ["t1", "t2"]


def test_list_filters(client, project_id):
    client.post("/api/knowledge", data={"title": "A", "content": "a", "project_id": str(project_id)})
    client.post("/api/knowledge", data={"title": "B", "content": "b", "type": "voice"})
    client.post(
        "/api/knowledge",
        data={"title": "C", "content": "c", "tags": "special"},
    )

    by_project = client.get("/api/knowledge", params={"project_id": project_id}).json()
    assert [k["title"] for k in by_project] == ["A"]

    by_type = client.get("/api/knowledge", params={"type": "voice"}).json()
    assert [k["title"] for k in by_type] == ["B"]

    by_tag = client.get("/api/knowledge", params={"tag": "special"}).json()
    assert [k["title"] for k in by_tag] == ["C"]


def test_update_knowledge(client):
    kid = client.post("/api/knowledge", data={"title": "old", "content": "old"}).json()["id"]
    resp = client.patch(f"/api/knowledge/{kid}", json={"title": "new", "tags": ["z"]})
    assert resp.status_code == 200
    assert resp.json()["title"] == "new"
    assert resp.json()["tags"] == ["z"]
    assert client.get(f"/api/knowledge/{kid}").json()["title"] == "new"


def test_delete_knowledge(client):
    kid = client.post("/api/knowledge", data={"title": "gone", "content": "c"}).json()["id"]
    assert client.delete(f"/api/knowledge/{kid}").status_code == 200
    assert client.get(f"/api/knowledge/{kid}").status_code == 404
    assert client.delete(f"/api/knowledge/{kid}").status_code == 404


def test_missing_knowledge_404(client):
    assert client.get("/api/knowledge/4242").status_code == 404
    assert client.patch("/api/knowledge/4242", json={"title": "x"}).status_code == 404


def test_malformed_knowledge(client):
    assert client.post("/api/knowledge", data={"title": "", "content": "c"}).status_code == 422
    assert client.post("/api/knowledge", data={"title": "T", "type": "bogus"}).status_code == 422
    assert client.post("/api/knowledge", data={"content": "no title"}).status_code == 422


def test_knowledge_bad_project_id_400(client):
    resp = client.post("/api/knowledge", data={"title": "T", "content": "c", "project_id": "77"})
    assert resp.status_code == 400


def test_recent_endpoint(client):
    for i in range(3):
        client.post("/api/knowledge", data={"title": f"item {i}", "content": "c"})
    resp = client.get("/api/knowledge/recent", params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()) == 2
    titles = [k["title"] for k in resp.json()]
    assert titles == ["item 2", "item 1"]  # newest first
