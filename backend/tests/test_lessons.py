"""Lesson matching: scoring, and the exclusion rules that stop a lesson from
being applied where it doesn't hold."""


def add_lesson(client, title, content, tags):
    resp = client.post("/api/knowledge", data={
        "title": title,
        "content": content,
        "type": "project_note",
        "tags": tags,
        "source": "agent",
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def match(client, signature, **params):
    params["signature"] = signature
    resp = client.get("/api/lessons/match", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_noisy_real_world_error_still_matches(client):
    """The regression this whole matching rewrite exists for.

    Under the original implementation the stored text had to contain the entire
    query, so a pasted error carrying a hostname/port/PID matched nothing.
    """
    add_lesson(client, "SOCKS proxy breaks httpx",
               "【触发签名】\nsocksio\nUsing SOCKS proxy\n\n【根因】\n环境变量 all_proxy 指向 socks5",
               ["kind:lesson", "scope:machine", "machine:X99/b3c9c3"])

    for noisy in [
        "socksio",
        "ImportError: Using SOCKS proxy, but the 'socksio' package is not installed",
        "2026-09-07 22:31:04 [worker-7] ImportError: Using SOCKS proxy, but the "
        "'socksio' package is not installed. host=10.0.0.5 port=8443 pid=91827",
    ]:
        assert len(match(client, noisy)) == 1, "should match: {}".format(noisy[:50])

    assert match(client, "Kubernetes operator crashed on node-42") == []


def test_signature_hit_and_miss(client):
    add_lesson(client, "SOCKS proxy breaks httpx",
               "【触发签名】\nImportError: Using SOCKS proxy, but the 'socksio' package is not installed",
               ["kind:lesson", "scope:machine", "machine:X99/b3c9c3"])

    hits = match(client, "socksio")
    assert len(hits) == 1
    assert hits[0]["match_score"] > 0
    assert "signature" in hits[0]["match_reasons"]

    assert match(client, "完全无关的报错串") == []


def test_non_lesson_items_are_never_returned(client):
    client.post("/api/knowledge", data={
        "title": "普通笔记",
        "content": "这里也提到了 socksio 但它不是一条教训",
        "type": "text",
    })
    assert match(client, "socksio") == []


def test_anti_scope_excludes_by_os(client):
    add_lesson(client, "bash history expansion",
               "【触发签名】\n!sudo 开头的命令被改写\n【不适用】\nPowerShell",
               ["kind:lesson", "scope:universal", "not:os:windows"])

    assert len(match(client, "!sudo")) == 1
    assert len(match(client, "!sudo", os="linux")) == 1
    assert match(client, "!sudo", os="windows") == []


def test_declared_os_excludes_other_os(client):
    add_lesson(client, "linux only lesson", "【触发签名】\nsystemctl restart failed",
               ["kind:lesson", "scope:stack", "os:linux"])

    assert len(match(client, "systemctl", os="linux")) == 1
    assert match(client, "systemctl", os="windows") == []
    # No OS asserted by the caller: don't guess, keep the lesson visible.
    assert len(match(client, "systemctl")) == 1


def test_machine_scoped_lesson_does_not_cross_machines(client):
    add_lesson(client, "proxy on X99", "【触发签名】\nHTTP 503 from localhost curl",
               ["kind:lesson", "scope:machine", "machine:X99/b3c9c3"])

    assert len(match(client, "HTTP 503", machine="X99/b3c9c3")) == 1
    assert match(client, "HTTP 503", machine="OTHER/aaaaaa") == []


def test_scoring_ranks_more_specific_matches_first(client):
    project_id = client.post("/api/projects", json={"name": "P"}).json()["id"]

    add_lesson(client, "generic", "【触发签名】\nconnection refused",
               ["kind:lesson", "scope:universal"])
    specific = add_lesson(client, "specific", "【触发签名】\nconnection refused",
                          ["kind:lesson", "scope:stack", "stack:vite",
                           "machine:X99/b3c9c3"])
    client.patch("/api/knowledge/{}".format(specific), json={"project_id": project_id})

    hits = match(client, "connection refused", machine="X99/b3c9c3",
                 stack="vite", project_id=project_id)
    assert len(hits) == 2
    assert hits[0]["id"] == specific
    assert hits[0]["match_score"] > hits[1]["match_score"]
    for reason in ("machine", "stack", "project"):
        assert reason in hits[0]["match_reasons"]


def test_cache_returns_same_results_and_marks_them(client):
    add_lesson(client, "cached lesson", "【触发签名】\nsocksio",
               ["kind:lesson", "scope:universal"])

    first = match(client, "socksio")
    second = match(client, "socksio")
    assert [x["id"] for x in first] == [x["id"] for x in second]
    assert "cached" not in first[0]["match_reasons"]
    assert "cached" in second[0]["match_reasons"]
    assert second[0]["match_score"] == first[0]["match_score"]


def test_cache_invalidated_when_a_lesson_is_added(client):
    add_lesson(client, "first", "【触发签名】\nconnection refused",
               ["kind:lesson", "scope:universal"])
    assert len(match(client, "connection refused")) == 1
    match(client, "connection refused")  # populate cache

    add_lesson(client, "second", "【触发签名】\nconnection refused",
               ["kind:lesson", "scope:universal"])
    # The corpus fingerprint is part of the cache key, so the stale single-hit
    # entry must be unreachable rather than served.
    assert len(match(client, "connection refused")) == 2


def test_rerank_cutoff_is_configurable(monkeypatch):
    """The cutoff is tuned on very few points, so it must be movable without a
    code change — see the measurement note in lesson_service."""
    from app.services import lesson_service

    monkeypatch.delenv("KB_RERANK_CUTOFF", raising=False)
    assert lesson_service._rerank_cutoff() == -0.9
    monkeypatch.setenv("KB_RERANK_CUTOFF", "-1.5")
    assert lesson_service._rerank_cutoff() == -1.5
    monkeypatch.setenv("KB_RERANK_CUTOFF", "not-a-number")
    assert lesson_service._rerank_cutoff() == -0.9


def _embedded_count(client):
    return client.get("/api/lessons/status").json()["embedded"]


def test_lesson_is_embedded_on_write_not_only_on_reindex(client, monkeypatch):
    """The gap that broke the loop: a lesson written through the skill/MCP was
    invisible to semantic search until someone remembered to call reindex."""
    calls = []
    from app.services import knowledge_service

    monkeypatch.setattr(knowledge_service, "_maybe_embed_lesson",
                        lambda conn, kid, tags: calls.append((kid, tags)))

    add_lesson(client, "a lesson", "【触发签名】\nboom", ["kind:lesson", "scope:universal"])
    assert len(calls) == 1, "creating a lesson must attempt embedding"

    client.post("/api/knowledge", data={"title": "普通笔记", "content": "x", "type": "text"})
    assert len(calls) == 2, "the hook runs for every item; it filters on the tag itself"


def test_embedding_failure_never_blocks_the_write(client, monkeypatch):
    from app.services import knowledge_service

    def boom(conn, knowledge_id):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr("app.services.lesson_service.embed_lesson", boom)
    kid = add_lesson(client, "still saved", "【触发签名】\nboom",
                     ["kind:lesson", "scope:universal"])
    assert client.get("/api/knowledge/{}".format(kid)).status_code == 200
    assert len(match(client, "boom")) == 1, "keyword matching must still work"


def test_editing_a_lesson_re_embeds_it(client, monkeypatch):
    kid = add_lesson(client, "v1", "【触发签名】\nboom", ["kind:lesson", "scope:universal"])

    calls = []
    monkeypatch.setattr("app.services.lesson_service.embed_lesson",
                        lambda conn, knowledge_id: calls.append(knowledge_id) or True)
    client.patch("/api/knowledge/{}".format(kid), json={"content": "【触发签名】\nbang"})
    assert calls == [kid], "a stale vector would match text no longer in the lesson"
