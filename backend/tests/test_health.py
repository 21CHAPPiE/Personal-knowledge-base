def test_health_ok(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["uploads"] == "ok"
    assert body["llm"] == "noop"
    assert body["stt"] == "noop"
