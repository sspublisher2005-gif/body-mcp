"""Regressions for the bugs found by the 2026-11-22 code reviews."""
import asyncio
import os

from body_mcp import bridge, reflex, server, user_browser


def test_eyes_see_browser_has_a_real_description():
    tools = asyncio.run(server.mcp.list_tools())
    tool = next(t for t in tools if t.name == "eyes_see_browser")
    assert tool.description and "refs" in tool.description


def test_other_browser_tools_refuse_without_a_connection(monkeypatch):
    monkeypatch.setenv("BODY_MCP_CONFIG_DIR", os.path.join(
        os.environ.get("TEMP", "/tmp"), "body_review_guard"))
    monkeypatch.setattr(user_browser, "connected", lambda: {"connected": False})
    r = asyncio.run(server.hands_open("https://example.com"))
    assert r["status"] == "needs_user"


def test_private_screenshot_is_refused():
    r = asyncio.run(server.eyes_see_browser(url="https://example.com",
                                            private=True, screenshot=True))
    assert r["success"] is False
    assert "not supported" in r["message"]


def test_reflex_ask_shows_the_exact_action(monkeypatch):
    seen = {}

    class Ctx:
        client_capabilities = type("C", (), {"elicitation": True})()

        async def elicit(self, message, schema):
            seen["message"] = message
            return type("R", (), {"action": "accept", "data": type("D", (), {"answer": True})()})()

    asyncio.run(reflex.ask("Open the docs?", Ctx(),
                          action={"tool": "hands_click", "capability": "consequential",
                                  "target": "Confirm transfer"}))
    assert "hands_click" in seen["message"]
    assert "Confirm transfer" in seen["message"]


def test_bridge_token_is_required():
    path = os.path.join(os.path.dirname(bridge.__file__), "bridge.py")
    with open(path, encoding="utf-8") as handle:
        assert "compare_digest" in handle.read()


def test_unverified_batch_is_not_success():
    # Guard the contract at the helper level (no browser needed).
    from body_mcp import batch

    out = batch._make_result("t", "completed", [], evidence={"last_verify": None}, start=0)
    assert out["success"] is False
    out2 = batch._make_result("t", "completed", [], evidence={"last_verify": {"status": "CONFIRMED"}}, start=0)
    assert out2["success"] is True
