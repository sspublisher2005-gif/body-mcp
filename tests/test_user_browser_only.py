"""The no-test-browser rule: refuse with needs_user when no user browser is connected."""
import asyncio
import os

from body_mcp import permissions, server, user_browser


def _default_env(monkeypatch, tmp_path):
    monkeypatch.setenv("BODY_MCP_CONFIG_DIR", str(tmp_path))
    return permissions.load_profile()


def test_gate_refuses_when_no_browser_connected(monkeypatch, tmp_path):
    _default_env(monkeypatch, tmp_path)
    monkeypatch.setattr(user_browser, "connected", lambda: {"connected": False})
    refused = user_browser.gate()
    assert refused is not None
    assert refused["status"] == "needs_user"
    assert "chrome://extensions" in refused["data"]["steps"][0]
    assert "edge://extensions" in refused["data"]["steps"][0]
    assert "Disconnect & forget" in refused["data"]["revoke"]


def test_gate_passes_when_a_user_browser_is_connected(monkeypatch, tmp_path):
    _default_env(monkeypatch, tmp_path)
    monkeypatch.setattr(user_browser, "connected", lambda: {"connected": True,
                                                            "source": "extension bridge"})
    assert user_browser.gate() is None


def test_gate_can_be_disabled_by_the_profile_for_ci(monkeypatch, tmp_path):
    _default_env(monkeypatch, tmp_path)
    profile = permissions.load_profile()
    profile["capabilities"]["own_browser_only"] = "deny"
    with open(os.path.join(tmp_path, "permissions.json"), "w", encoding="utf-8") as handle:
        import json

        json.dump(profile, handle, indent=2)
    monkeypatch.setattr(user_browser, "connected", lambda: {"connected": False})
    assert user_browser.gate() is None


def test_eyes_see_browser_refuses_instead_of_launching_managed(monkeypatch, tmp_path):
    _default_env(monkeypatch, tmp_path)
    monkeypatch.setattr(user_browser, "connected", lambda: {"connected": False})
    result = asyncio.run(server.eyes_see_browser(url="https://www.reddit.com"))
    assert result["status"] == "needs_user"
    assert "will not open a separate test browser" in result["message"]


def test_connected_detection_lists_both_routes(monkeypatch):
    monkeypatch.setattr("body_mcp.attach.attached_status", lambda: {"attached": False})
    monkeypatch.setattr("body_mcp.bridge.status", lambda: {"extension_connected": False})
    assert user_browser.connected()["connected"] is False
    monkeypatch.setattr("body_mcp.bridge.status", lambda: {"extension_connected": True,
                                                           "tabs": [{"id": 1}]})
    assert user_browser.connected()["source"] == "extension bridge"
