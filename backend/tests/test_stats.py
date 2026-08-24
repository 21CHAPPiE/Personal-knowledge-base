def test_stats_endpoint(client):
    client.post("/api/projects", json={"name": "统计项目"})
    client.post("/api/knowledge", data={"title": "今日条目", "content": "x", "type": "text"})
    resp = client.get("/api/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["today_count"] >= 1
    assert body["total_items"] == 1
    assert body["total_projects"] == 1
    assert body["recent_items"][0]["title"] == "今日条目"
    assert body["updated_projects"][0]["name"] == "统计项目"


def test_stats_empty_db(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["today_count"] == 0
    assert body["total_items"] == 0
    assert body["recent_items"] == []
