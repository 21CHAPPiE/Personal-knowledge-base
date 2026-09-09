"""KB_API_TOKEN support in the MCP server's http_request helper.

Loaded fresh (not via the shared mcp_module fixture in test_mcp.py) since
that fixture permanently rebinds http_request for the whole test session;
this file only needs the real http_request/urlopen wiring in isolation.
"""

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_PATH = REPO_ROOT / "mcp" / "kb_mcp_server.py"


def _load_fresh_module():
    spec = importlib.util.spec_from_file_location("kb_mcp_server_auth_test", MCP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeResponse:
    def __init__(self, body=b'{"ok": true}'):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_sends_bearer_header_when_token_configured(monkeypatch):
    monkeypatch.setenv("KB_API_TOKEN", "sekret")
    mod = _load_fresh_module()
    captured = {}

    def fake_open(req, timeout=30):
        captured["auth"] = req.get_header("Authorization")
        return FakeResponse()

    monkeypatch.setattr(mod._opener, "open", fake_open)
    mod.http_request("GET", "/health")
    assert captured["auth"] == "Bearer sekret"


def test_omits_auth_header_when_token_not_configured(monkeypatch):
    monkeypatch.delenv("KB_API_TOKEN", raising=False)
    mod = _load_fresh_module()
    captured = {}

    def fake_open(req, timeout=30):
        captured["auth"] = req.get_header("Authorization")
        return FakeResponse()

    monkeypatch.setattr(mod._opener, "open", fake_open)
    mod.http_request("GET", "/health")
    assert captured["auth"] is None
