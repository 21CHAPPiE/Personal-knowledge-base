def test_create_and_get_project(client):
    resp = client.post("/api/projects", json={"name": "Alpha", "description": "first project"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["name"] == "Alpha"
    assert body["status"] == "active"
    pid = body["id"]

    got = client.get(f"/api/projects/{pid}")
    assert got.status_code == 200
    assert got.json()["name"] == "Alpha"


def test_create_duplicate_name_409(client):
    assert client.post("/api/projects", json={"name": "Beta"}).status_code == 201
    resp = client.post("/api/projects", json={"name": "beta "})
    assert resp.status_code == 409


def test_list_projects(client):
    client.post("/api/projects", json={"name": "P1"})
    client.post("/api/projects", json={"name": "P2", "status": "archived"})
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    resp = client.get("/api/projects", params={"status": "archived"})
    names = [p["name"] for p in resp.json()]
    assert names == ["P2"]


def test_patch_project(client, project_id):
    resp = client.patch(f"/api/projects/{project_id}", json={"description": "new desc", "status": "done"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["description"] == "new desc"
    assert body["status"] == "done"

    clash = client.patch(f"/api/projects/{project_id}", json={"name": "Test Project"})
    assert clash.status_code == 200  # same name as self is fine


def test_patch_project_name_conflict(client):
    client.post("/api/projects", json={"name": "A"})
    client.post("/api/projects", json={"name": "B"})
    b = client.get("/api/projects").json()
    b_id = [p for p in b if p["name"] == "B"][0]["id"]
    resp = client.patch(f"/api/projects/{b_id}", json={"name": "a"})
    assert resp.status_code == 409


def test_delete_project(client, project_id):
    kid = client.post(
        "/api/knowledge", data={"title": "k", "content": "c", "project_id": str(project_id)}
    ).json()["id"]
    resp = client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert client.get(f"/api/projects/{project_id}").status_code == 404
    # knowledge survives with project_id = NULL
    k = client.get(f"/api/knowledge/{kid}").json()
    assert k["project_id"] is None


def test_missing_project_404(client):
    assert client.get("/api/projects/999").status_code == 404
    assert client.patch("/api/projects/999", json={"description": "x"}).status_code == 404
    assert client.delete("/api/projects/999").status_code == 404


def test_malformed_project(client):
    assert client.post("/api/projects", json={"name": "  "}).status_code == 422
    assert client.post("/api/projects", json={"name": "X", "status": "weird"}).status_code == 422
    assert client.post("/api/projects", json={"description": "no name"}).status_code == 422
