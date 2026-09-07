"""MCP server tests: protocol handshake plus all six tools against the real
backend (TestClient), with the stdio transport's http_request swapped for a
direct route into the ASGI app."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_PATH = REPO_ROOT / "mcp" / "kb_mcp_server.py"


@pytest.fixture(scope="module")
def mcp_module():
    spec = importlib.util.spec_from_file_location("kb_mcp_server", MCP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kb_mcp_server"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mcp(mcp_module, client):
    """Route MCP http_request into the TestClient instead of real sockets."""
    def route(method: str, path: str, json_body=None, multipart=None):
        headers = {}
        data = None
        if multipart is not None:
            body, ctype = mcp_module._encode_multipart(multipart)
            data = body
            headers["Content-Type"] = ctype
        resp = client.request(
            method,
            path,
            json=json_body if data is None else None,
            data=data,
            headers=headers,
        )
        payload = resp.json()
        if resp.status_code >= 400:
            raise mcp_module.MCPHttpError(resp.status_code, payload)
        return payload

    mcp_module.http_request = route
    return mcp_module


def call(mcp, name: str, arguments: dict):
    resp = mcp.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    assert "error" not in resp
    return resp["result"]


def test_initialize_handshake(mcp):
    resp = mcp.handle_request({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    })
    result = resp["result"]
    assert result["protocolVersion"] == "2025-03-26"
    assert result["serverInfo"]["name"] == "kb"
    assert "tools" in result["capabilities"]


def test_initialize_unknown_version_falls_back(mcp):
    resp = mcp.handle_request({
        "jsonrpc": "2.0", "id": 2, "method": "initialize",
        "params": {"protocolVersion": "1999-01-01"},
    })
    assert resp["result"]["protocolVersion"] == "2025-03-26"


def test_initialized_notification_has_no_response(mcp):
    assert mcp.handle_request({
        "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
    }) is None


def test_unknown_method(mcp):
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 3, "method": "bogus/method"})
    assert resp["error"]["code"] == -32601


def test_tools_list_is_complete(mcp):
    resp = mcp.handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/list"})
    tools = resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert names == {
        "kb_search", "kb_get", "kb_add", "kb_recent",
        "project_get_context", "project_append_context",
        "kb_lesson_match", "kb_lesson_add",
    }
    for t in tools:
        assert t["inputSchema"]["type"] == "object"
        assert "description" in t


def test_kb_add_then_get_roundtrip(mcp, client):
    created = call(mcp, "kb_add", {
        "title": "MCP 写入的测试知识",
        "content": "通过 kb_add 工具写入，包含 中文内容 与 keyword-alpha",
        "type": "text",
        "tags": ["mcp", "测试"],
    })
    assert created["isError"] is False
    item = json.loads(created["content"][0]["text"])
    assert item["title"] == "MCP 写入的测试知识"
    assert item["source"] == "agent"

    fetched = call(mcp, "kb_get", {"id": item["id"]})
    payload = json.loads(fetched["content"][0]["text"])
    assert payload["id"] == item["id"]
    assert payload["tags"] == ["mcp", "测试"]

    # it must be visible through the REST API too (single source of truth)
    via_rest = client.get(f"/api/knowledge/{item['id']}").json()
    assert via_rest["content"] == item["content"]


def test_kb_search_chinese_and_filters(mcp):
    call(mcp, "kb_add", {"title": "FTS5 中文检索", "content": "子串回退 机制 的说明"})
    res = call(mcp, "kb_search", {"query": "回退"})
    payload = json.loads(res["content"][0]["text"])
    assert any(k["id"] for k in payload)
    titles = [k["title"] for k in payload]
    assert "FTS5 中文检索" in titles

    res2 = call(mcp, "kb_search", {"query": "回退", "type": "project_note", "limit": 5})
    payload2 = json.loads(res2["content"][0]["text"])
    assert all(k["type"] == "project_note" for k in payload2)


def test_kb_recent(mcp):
    res = call(mcp, "kb_recent", {"limit": 3})
    payload = json.loads(res["content"][0]["text"])
    assert isinstance(payload, list)
    assert len(payload) <= 3


def test_project_context_roundtrip_by_name(mcp, client):
    client.post("/api/projects", json={"name": "MCP 上下文项目", "description": "ctx"})
    client.post(
        "/api/knowledge",
        data={"title": "上下文条目", "content": "第一条进展", "type": "project_note",
              "project_id": client.get("/api/projects").json()[0]["id"]},
    )

    ctx = call(mcp, "project_get_context", {"project": "MCP 上下文项目"})
    text = ctx["content"][0]["text"]
    assert "MCP 上下文项目" in text
    assert "上下文条目" in text
    assert "total_items: 1" in text

    appended = call(mcp, "project_append_context", {
        "project": "MCP 上下文项目",
        "content": "MCP 追加的第二条进展",
        "title": "agent 进展",
    })
    assert appended["isError"] is False

    ctx2 = call(mcp, "project_get_context", {"project": "MCP 上下文项目"})
    text2 = ctx2["content"][0]["text"]
    assert "MCP 追加的第二条进展" in text2
    assert "total_items: 2" in text2


def test_project_context_by_id(mcp, client):
    proj = client.post("/api/projects", json={"name": "按 ID 解析"}).json()
    ctx = call(mcp, "project_get_context", {"project": str(proj["id"])})
    assert "按 ID 解析" in ctx["content"][0]["text"]


def test_unknown_tool_is_error_not_crash(mcp):
    res = call(mcp, "kb_fly", {"a": 1})
    assert res["isError"] is True
    assert "unknown tool" in res["content"][0]["text"]


def test_backend_404_is_mcp_error(mcp):
    res = call(mcp, "kb_get", {"id": 99999})
    assert res["isError"] is True
    assert "404" in res["content"][0]["text"]


def test_project_not_found_by_name(mcp):
    res = call(mcp, "project_get_context", {"project": "不存在的项目"})
    assert res["isError"] is True
    assert "不存在的项目" in res["content"][0]["text"]
