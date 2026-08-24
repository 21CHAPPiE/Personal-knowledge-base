def _seed(client):
    client.post(
        "/api/knowledge",
        data={"title": "FastAPI notes", "content": "dependency injection and middleware", "type": "text"},
    )
    client.post(
        "/api/knowledge",
        data={"title": "数据库设计", "content": "项目 数据 管理 与 索引 优化", "type": "text"},
    )
    client.post(
        "/api/knowledge",
        data={"title": "Random", "content": "nothing special here", "type": "text"},
    )


def test_search_english_fts(client):
    _seed(client)
    resp = client.get("/api/search", params={"q": "FastAPI"})
    assert resp.status_code == 200
    titles = [h["title"] for h in resp.json()]
    assert "FastAPI notes" in titles


def test_search_chinese_two_char_fallback(client):
    _seed(client)
    # two-char CJK term that FTS5 unicode61 cannot match alone -> LIKE fallback
    resp = client.get("/api/search", params={"q": "数据"})
    assert resp.status_code == 200
    titles = [h["title"] for h in resp.json()]
    assert "数据库设计" in titles


def test_search_chinese_three_char(client):
    _seed(client)
    resp = client.get("/api/search", params={"q": "数据库"})
    titles = [h["title"] for h in resp.json()]
    assert "数据库设计" in titles


def test_search_project_and_type_filters(client, project_id):
    pid = client.post(
        "/api/knowledge",
        data={"title": "ProjWord uniquealpha", "content": "x", "project_id": str(project_id)},
    ).json()["id"]
    client.post(
        "/api/knowledge",
        data={"title": "ProjWord uniquebeta", "content": "voice thing", "type": "voice"},
    )
    by_project = client.get("/api/search", params={"q": "uniquealpha", "project_id": project_id})
    assert len(by_project.json()) == 1
    no_project = client.get("/api/search", params={"q": "uniquealpha", "project_id": 999})
    assert len(no_project.json()) == 0

    by_type = client.get("/api/search", params={"q": "uniquebeta", "type": "voice"})
    assert len(by_type.json()) == 1
    wrong_type = client.get("/api/search", params={"q": "uniquebeta", "type": "screenshot"})
    assert len(wrong_type.json()) == 0


def test_search_no_results(client):
    _seed(client)
    resp = client.get("/api/search", params={"q": "zebraquantum"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_search_dedup(client):
    _seed(client)
    resp = client.get("/api/search", params={"q": "数据"})
    ids = [h["id"] for h in resp.json()]
    assert len(ids) == len(set(ids))


def test_search_special_chars_no_crash(client):
    _seed(client)
    for q in ['a"b', "AND", "OR", "NEAR:", "fastapi AND notes", "（中文）", "***", "100%"]:
        resp = client.get("/api/search", params={"q": q})
        assert resp.status_code == 200, q
