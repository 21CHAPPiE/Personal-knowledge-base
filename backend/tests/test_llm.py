class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def test_llm_status_noop(client):
    resp = client.get("/api/llm/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["llm"]["configured"] is False
    assert body["llm"]["provider"] == "noop"
    assert body["stt"]["configured"] is False


def test_summarize_fallback_noop(client):
    kid = client.post(
        "/api/knowledge", data={"title": "T", "content": "a" * 300}
    ).json()["id"]
    resp = client.post("/api/llm/summarize", json={"knowledge_id": kid})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "noop"
    assert body["fallback"] is True
    assert body["summary"]  # non-empty honest fallback
    assert client.get(f"/api/knowledge/{kid}").json()["summary"] == body["summary"]


def test_suggest_tags_fallback_noop(client):
    kid = client.post("/api/knowledge", data={"title": "T", "content": "c"}).json()["id"]
    resp = client.post("/api/llm/suggest-tags", json={"knowledge_id": kid, "apply": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "noop"
    assert body["tags"] == []


def test_summarize_with_qwen_provider(client, monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")

    import app.providers.qwen as qwen_mod

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse({"choices": [{"message": {"content": "  摘要XYZ  "}}]})

    monkeypatch.setattr(qwen_mod.httpx, "post", fake_post)
    kid = client.post(
        "/api/knowledge", data={"title": "标题", "content": "内容内容"}
    ).json()["id"]
    resp = client.post("/api/llm/summarize", json={"knowledge_id": kid})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["provider"] == "qwen"
    assert body["fallback"] is False
    assert body["summary"] == "摘要XYZ"
    assert captured["url"] == "http://fake.local/v1/chat/completions"
    assert captured["json"]["model"] == "qwen-test"


def test_summarize_qwen_error_falls_back(client, monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")

    import httpx as real_httpx
    import app.providers.qwen as qwen_mod

    def boom(url, json=None, headers=None, timeout=None):
        raise real_httpx.ConnectError("down")

    monkeypatch.setattr(qwen_mod.httpx, "post", boom)
    kid = client.post("/api/knowledge", data={"title": "T", "content": "content here"}).json()["id"]
    resp = client.post("/api/llm/summarize", json={"knowledge_id": kid, "fallback": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["fallback"] is True
    assert body["error"]

    # fallback=False -> 502
    resp2 = client.post("/api/llm/summarize", json={"knowledge_id": kid, "fallback": False})
    assert resp2.status_code == 502


def test_suggest_tags_qwen_parses_json(client, monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")

    import app.providers.qwen as qwen_mod

    monkeypatch.setattr(
        qwen_mod.httpx,
        "post",
        lambda url, json=None, headers=None, timeout=None: FakeResponse(
            {"choices": [{"message": {"content": 'tags: ["a", "b", "a"]'}}]}
        ),
    )
    kid = client.post("/api/knowledge", data={"title": "T", "content": "c"}).json()["id"]
    resp = client.post("/api/llm/suggest-tags", json={"knowledge_id": kid, "apply": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tags"] == ["a", "b"]
    assert client.get(f"/api/knowledge/{kid}").json()["tags"] == ["a", "b"]


def test_qwen_token_budget_covers_reasoning_overhead(client, monkeypatch):
    """Regression: qwen3.8-27b-local spends most of max_tokens on
    reasoning_content; the 150-token budget observed 2026-08-24 left
    content="" and produced tags=[]. Budget must stay >= LLM_MAX_TOKENS."""
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")

    import app.providers.qwen as qwen_mod

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["json"] = json
        # Real response shape of a reasoning model: content + reasoning_content
        return FakeResponse(
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '["Rock5A", "Vue", "Gesture"]',
                            "reasoning_content": "x" * 400,
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr(qwen_mod.httpx, "post", fake_post)
    kid = client.post(
        "/api/knowledge", data={"title": "T", "content": "内容"}
    ).json()["id"]

    resp = client.post("/api/llm/summarize", json={"knowledge_id": kid})
    assert resp.status_code == 200
    assert captured["json"]["max_tokens"] == qwen_mod.QwenProvider.LLM_MAX_TOKENS
    assert qwen_mod.QwenProvider.LLM_MAX_TOKENS >= 512

    resp = client.post(
        "/api/llm/suggest-tags", json={"knowledge_id": kid, "apply": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["tags"] == ["Rock5A", "Vue", "Gesture"]
    assert captured["json"]["max_tokens"] == qwen_mod.QwenProvider.LLM_MAX_TOKENS
    assert client.get(f"/api/knowledge/{kid}").json()["tags"] == ["Rock5A", "Vue", "Gesture"]


def test_llm_missing_item_404(client):
    assert client.post("/api/llm/summarize", json={"knowledge_id": 555}).status_code == 404
    assert client.post("/api/llm/suggest-tags", json={"knowledge_id": 555}).status_code == 404
