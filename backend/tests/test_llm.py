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


def test_logic_groups_noop_returns_empty(client):
    resp = client.post("/api/llm/logic-groups", json={
        "items": [{"id": 1, "title": "a", "excerpt": "x"},
                  {"id": 2, "title": "b", "excerpt": "y"}],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["groups"] == []
    assert body["provider"] == "noop"


def test_logic_groups_too_few_items_short_circuits(client, monkeypatch):
    """Fewer than two items can never form a group — never worth a model call."""
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")
    import app.providers.qwen as qwen_mod

    called = []
    monkeypatch.setattr(qwen_mod.httpx, "post", lambda *a, **k: called.append(1))

    resp = client.post("/api/llm/logic-groups", json={
        "items": [{"id": 1, "title": "a", "excerpt": "x"}],
    })
    assert resp.status_code == 200
    assert resp.json()["groups"] == []
    assert called == [], "must not call the model for a single item"


def test_logic_groups_parses_qwen_response_and_drops_unknown_ids(client, monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")
    import app.providers.qwen as qwen_mod

    raw = '[{"item_ids": [1, 2, 999], "shared_logic": "都是为了还债"}, {"item_ids": [3], "shared_logic": "太少了"}]'
    monkeypatch.setattr(qwen_mod.httpx, "post",
                        lambda *a, **k: FakeResponse({"choices": [{"message": {"content": raw}}]}))

    resp = client.post("/api/llm/logic-groups", json={
        "items": [{"id": 1, "title": "a", "excerpt": "x"},
                  {"id": 2, "title": "b", "excerpt": "y"},
                  {"id": 3, "title": "c", "excerpt": "z"}],
        "context": "天幕红尘",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "qwen"
    assert body["groups"] == [{"item_ids": [1, 2], "shared_logic": "都是为了还债"}], (
        "an id the caller never sent (999) must be dropped, and a group left "
        "with fewer than 2 real items must be dropped entirely"
    )


def test_abstract_patterns_drops_unknown_ids(client, monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")
    import app.providers.qwen as qwen_mod

    raw = '[{"id":1,"pattern":"甲因关联方破产背债 → 甲用制度差价变现"},{"id":99,"pattern":"不存在"}]'
    monkeypatch.setattr(qwen_mod.httpx, "post",
                        lambda *a, **k: FakeResponse({"choices": [{"message": {"content": raw}}]}))

    body = client.post("/api/llm/abstract-patterns", json={
        "items": [{"id": 1, "title": "a", "excerpt": "x"}],
    }).json()
    assert body["patterns"] == [{"id": 1, "pattern": "甲因关联方破产背债 → 甲用制度差价变现"}]


def test_abstract_patterns_disables_thinking(client, monkeypatch):
    """A reasoning model spends the whole budget thinking and returns empty
    content on a task this size — the flag is not optional here (lesson 21)."""
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")
    import app.providers.qwen as qwen_mod

    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(json or {})
        return FakeResponse({"choices": [{"message": {"content": "[]"}}]})

    monkeypatch.setattr(qwen_mod.httpx, "post", fake_post)
    client.post("/api/llm/abstract-patterns", json={
        "items": [{"id": 1, "title": "a", "excerpt": "x"}],
    })
    assert captured["chat_template_kwargs"] == {"enable_thinking": False}


def test_match_patterns_needs_two_patterns(client, monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")
    import app.providers.qwen as qwen_mod

    called = []
    monkeypatch.setattr(qwen_mod.httpx, "post", lambda *a, **k: called.append(1))

    body = client.post("/api/llm/match-patterns", json={
        "patterns": [{"id": 1, "pattern": "甲…", "where": "第一章"}],
    }).json()
    assert body["groups"] == []
    assert called == [], "one pattern can never recur; don't spend a call on it"


def test_match_patterns_parses_groups(client, monkeypatch):
    monkeypatch.setenv("QWEN_BASE_URL", "http://fake.local/v1")
    monkeypatch.setenv("QWEN_MODEL", "qwen-test")
    import app.providers.qwen as qwen_mod

    raw = '[{"item_ids":[1,2],"shared_logic":"都是以利益为饵把人引进预设场合"}]'
    monkeypatch.setattr(qwen_mod.httpx, "post",
                        lambda *a, **k: FakeResponse({"choices": [{"message": {"content": raw}}]}))

    body = client.post("/api/llm/match-patterns", json={
        "patterns": [{"id": 1, "pattern": "甲…", "where": "第一章"},
                     {"id": 2, "pattern": "乙…", "where": "第四十章"}],
    }).json()
    assert body["groups"] == [{"item_ids": [1, 2], "shared_logic": "都是以利益为饵把人引进预设场合"}]


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


class FakeRerank:
    """Scores by keyword overlap, enough to exercise ranking without a model."""
    name = "fake"

    def is_configured(self):
        return True

    def rerank(self, query, documents):
        return [float(sum(1 for ch in set(query) if ch in d)) for d in documents]


def test_discrimination_reports_where_claimed_items_landed(client, monkeypatch):
    """A claimed item near the middle of the ranking is indistinguishable from
    one picked at random — the number exists so a reviewer sees that without
    re-reading the group."""
    import app.api.llm as llm_api

    monkeypatch.setattr(llm_api, "get_rerank_provider", lambda: FakeRerank())
    body = client.post("/api/llm/discrimination", json={
        "statement": "甲乙丙",
        "claimed": [1, 3],
        "candidates": [{"id": 1, "text": "甲乙丙"}, {"id": 2, "text": "无关"},
                       {"id": 3, "text": "戊己"}],
    }).json()
    assert body["available"] is True
    assert body["total"] == 3
    ranks = {r["id"]: r["rank"] for r in body["claimed_ranks"]}
    assert ranks[1] == 1, "the item the statement actually describes ranks first"
    assert ranks[3] > ranks[1]
    assert body["spread"] > 0


def test_discrimination_degrades_without_a_reranker(client):
    body = client.post("/api/llm/discrimination", json={
        "statement": "x", "claimed": [1], "candidates": [{"id": 1, "text": "y"}],
    }).json()
    assert body == {"available": False}, (
        "no reranker means the check is unavailable, not that the group failed it")
