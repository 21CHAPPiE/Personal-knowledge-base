"""Deciding on proposals: what a verdict changes, and what it records."""


def make_items(client, n=2):
    ids = []
    for i in range(n):
        ids.append(client.post("/api/knowledge", data={
            "title": "事件 {}".format(i), "content": "内容 {}".format(i), "type": "text",
        }).json()["id"])
    return ids


def make_proposal(client, ids):
    key = "about:logic-" + "-".join(str(i) for i in sorted(ids))
    resp = client.post("/api/knowledge", data={
        "title": "待审 · 疑似同一底层逻辑",
        "content": "模型认为这几条背后是同一个底层逻辑",
        "type": "text",
        "tags": ["kind:proposal", "proposal:logic-group", key],
    })
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_pending_lists_only_open_proposals(client):
    ids = make_items(client)
    pid = make_proposal(client, ids)
    assert [p["id"] for p in client.get("/api/proposals").json()] == [pid]

    client.post("/api/proposals/{}/decide".format(pid), json={"verdict": "dismiss"})
    assert client.get("/api/proposals").json() == [], "a decided proposal leaves the queue"


def test_approve_links_the_referenced_items(client):
    ids = make_items(client, 3)
    pid = make_proposal(client, ids)

    body = client.post("/api/proposals/{}/decide".format(pid),
                       json={"verdict": "approve", "note": "确实是同一套路"}).json()
    assert sorted(body["linked_items"]) == sorted(ids)

    key = "about:logic-" + "-".join(str(i) for i in sorted(ids))
    for kid in ids:
        assert key in client.get("/api/knowledge/{}".format(kid)).json()["tags"], (
            "approving must make the connection findable on the items themselves")


def test_dismiss_changes_nothing_on_the_items(client):
    ids = make_items(client)
    before = [client.get("/api/knowledge/{}".format(i)).json()["tags"] for i in ids]
    pid = make_proposal(client, ids)

    client.post("/api/proposals/{}/decide".format(pid), json={"verdict": "dismiss"})
    after = [client.get("/api/knowledge/{}".format(i)).json()["tags"] for i in ids]
    assert before == after, "dismissing must not touch the knowledge itself"


def test_decided_proposals_stay_readable_for_spot_checks(client):
    ids = make_items(client)
    pid = make_proposal(client, ids)
    client.post("/api/proposals/{}/decide".format(pid),
                json={"verdict": "approve", "by": "auto"})

    item = client.get("/api/knowledge/{}".format(pid)).json()
    assert item["id"] == pid, "resolved proposals are retagged, never deleted"
    assert "kind:proposal" not in item["tags"]
    assert "decision:approve" in item["tags"]
    assert "decided-by:auto" in item["tags"], (
        "who decided has to survive, or an automated decision can't be audited")


def test_every_decision_is_recorded_in_the_rubric(client):
    ids = make_items(client)
    pid = make_proposal(client, ids)
    client.post("/api/proposals/{}/decide".format(pid),
                json={"verdict": "dismiss", "note": "只是顺承因果", "by": "human"})

    log = client.get("/api/proposals/rubric").json()["decisions"]
    assert len(log) == 1
    assert "dismiss" in log[0] and "只是顺承因果" in log[0] and "human" in log[0]


def test_setting_criteria_keeps_the_decision_log(client):
    ids = make_items(client)
    pid = make_proposal(client, ids)
    client.post("/api/proposals/{}/decide".format(pid), json={"verdict": "dismiss"})

    client.put("/api/proposals/rubric", json={"criteria": "顺承因果不算，跨情境同构才算"})
    body = client.get("/api/proposals/rubric").json()
    assert "跨情境同构" in body["criteria"]
    assert len(body["decisions"]) == 1, (
        "rewriting the derived criteria must never drop the evidence under it")


def test_referenced_items_are_read_live_not_from_the_snapshot(client):
    ids = make_items(client)
    pid = make_proposal(client, ids)
    client.patch("/api/knowledge/{}".format(ids[0]), json={"content": "改过的正文"})

    items = client.get("/api/proposals/{}/items".format(pid)).json()
    assert [i["id"] for i in items] == sorted(ids)
    assert items[0]["content"] == "改过的正文"


def test_bad_verdict_is_rejected(client):
    ids = make_items(client)
    pid = make_proposal(client, ids)
    assert client.post("/api/proposals/{}/decide".format(pid),
                       json={"verdict": "maybe"}).status_code == 422
