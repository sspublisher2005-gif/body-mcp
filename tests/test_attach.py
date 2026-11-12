"""Current-browser (CDP) attach: endpoint safety, authorization, and clean detach.

These are unit-level tests: no browser is launched here. The REAL browser path is
covered by tests/test_attach_real.py (opt-in, needs a real Chrome/Edge).
"""
import asyncio
import json

from body_mcp import attach, permissions
from body_mcp.approvals import approvals


def _approve(tool: str, target: str, task: str | None = None):
    """Approve exactly what the tool will consume (as reflex_ask would)."""
    spec = permissions.required_action_spec(tool, "chrome_attach", target, None, task)
    asyncio.run(approvals.issue(spec))
    return spec


def test_endpoint_must_be_loopback_http():
    assert attach._valid_endpoint("http://127.0.0.1:9222")["ok"] is True
    assert attach._valid_endpoint("http://localhost:9222")["ok"] is True
    for bad in ("http://192.168.1.10:9222", "http://evil.example.com:9222",
                "https://127.0.0.1:9222", "http://127.0.0.1:80",
                "http://127.0.0.1:70000", "not-a-url"):
        verdict = attach._valid_endpoint(bad)
        assert verdict["ok"] is False, bad
        assert verdict["reason"]


def test_attach_refused_without_approval():
    async def flow():
        await approvals.clear()
        result = await attach.attach("http://127.0.0.1:9222")
        assert result["success"] is False
        assert result["data"]["permission"] == "ask"
        spec = result["data"]["required_action"]
        assert spec["tool"] == "attach_browser"
        assert spec["capability"] == "chrome_attach"
        # the returned spec is exactly what must be approved — approving it works
        await approvals.issue(spec)
        assert await approvals.peek(spec) is True
        await approvals.clear()

    asyncio.run(flow())


def test_approved_spec_matches_what_is_consumed():
    """The spec handed to the user must match the spec consumed at execution."""
    async def flow():
        await approvals.clear()
        denied = await attach.attach("http://127.0.0.1:9222")
        spec = denied["data"]["required_action"]
        await approvals.issue(spec)
        # attach() now passes the authorization gate and fails later at connect time
        result = await attach.attach("http://127.0.0.1:9222")
        assert result["success"] is False
        assert "permission" not in (result["data"] or {})
        assert "cannot reach CDP" in result["message"]
        await approvals.clear()

    asyncio.run(flow())


def test_deny_beats_approval(tmp_path, monkeypatch):
    monkeypatch.setenv("BODY_MCP_CONFIG_DIR", str(tmp_path))
    (tmp_path / "permissions.json").write_text(json.dumps(
        {"version": 1, "capabilities": {"chrome_attach": "deny"},
         "allowed_applications": []}), encoding="utf-8")
    permissions.acknowledge_consent()

    async def flow():
        await approvals.clear()
        await approvals.issue(permissions.required_action_spec(
            "attach_browser", "chrome_attach", "cdp:http://127.0.0.1:9222", None, None))
        result = await attach.attach("http://127.0.0.1:9222")
        assert result["success"] is False
        assert result["data"]["permission"] == "deny"
        await approvals.clear()

    asyncio.run(flow())


def test_detach_when_not_attached_is_a_noop():
    result = asyncio.run(attach.detach())
    assert result["success"] is True
    assert "not attached" in result["message"]


def test_status_reports_not_attached():
    snap = attach.attached_status()
    assert snap["attached"] is False


def test_list_tabs_without_attachment_is_empty():
    from body_mcp import server

    result = asyncio.run(server.list_tabs())
    assert result["success"] is True
    assert result["data"]["tabs"] == []
