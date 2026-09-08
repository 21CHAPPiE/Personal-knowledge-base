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
