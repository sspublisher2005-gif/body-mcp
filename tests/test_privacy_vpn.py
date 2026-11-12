"""The VPN path: honest state reading, fail-closed permission, no guessing."""
import asyncio

from body_mcp import privacy, server


def test_the_state_is_read_from_the_apps_own_words():
    assert privacy.vpn_state("Proton VPN - Connected") == "connected"
    assert privacy.vpn_state("Secure Core") == "connected"
    assert privacy.vpn_state("Disconnected") == "not connected"
    assert privacy.vpn_state("Proton VPN") == "unknown"


def test_connecting_without_the_app_installed_is_refused(monkeypatch):
    monkeypatch.setattr(privacy, "_vpn_app", lambda: None)
    result = privacy.vpn_connect()
    assert result["success"] is False
    assert "not installed" in result["message"]
    assert result["data"]["app_installed"] is False


def test_only_proton_is_supported():
    result = privacy.vpn_connect(app="windscribe")
    assert result["success"] is False
    assert "only 'proton'" in result["message"]


def test_a_missing_connect_button_is_reported_not_guessed(monkeypatch):
    monkeypatch.setattr(privacy, "_vpn_app", lambda: "C:/fake/ProtonVPN.exe")
    monkeypatch.setattr(privacy, "_launch_vpn_app", lambda path: "")
    monkeypatch.setattr(privacy, "_vpn_window",
                        lambda: {"title": "Proton VPN", "hwnd": 1})
    monkeypatch.setattr("body_mcp.uia.inspect",
                        lambda title, timeout=10.0: {"ok": True, "window": title,
                                                    "controls": [{"name": "Settings"}]})
    monkeypatch.setattr("body_mcp.uia.click", lambda title, name, timeout=10.0: {
        "ok": True, "clicked": name})
    result = privacy.vpn_connect()
    assert result["success"] is False
    assert "no connect button" in result["message"]
    assert "nothing was clicked" in result["message"]


def test_a_working_connect_reports_the_apps_own_state(monkeypatch):
    clicked = []
    monkeypatch.setattr(privacy, "_vpn_app", lambda: "C:/fake/ProtonVPN.exe")
    monkeypatch.setattr(privacy, "_launch_vpn_app", lambda path: "")
    monkeypatch.setattr(privacy, "_vpn_window",
                        lambda: {"title": "Proton VPN", "hwnd": 1})
    monkeypatch.setattr("body_mcp.uia.inspect", lambda title, timeout=10.0: {
        "ok": True, "window": title,
        "controls": [{"name": "Quick Connect", "enabled": True}]})
    monkeypatch.setattr("body_mcp.uia.click", lambda title, name, timeout=10.0: (
        clicked.append(name) or {"ok": True, "clicked": name}))
    monkeypatch.setattr(privacy.time, "sleep", lambda seconds: None)
    result = privacy.vpn_connect()
    assert result["success"] is True, result
    assert clicked == ["Quick Connect"]
    assert result["data"]["vpn_state"] in ("connected", "unknown")


def test_the_tool_is_denied_by_default_because_vpn_control_is_deny():
    """The VPN must not move unless the user allowed it in their own profile."""
    result = asyncio.run(server.privacy_vpn_connect())
    assert result["success"] is False
    assert "vpn_control" in result["message"]


def test_the_tool_is_exposed():
    async def names():
        tools = await server.mcp.list_tools()
        return [tool.name for tool in tools]

    assert "privacy_vpn_connect" in asyncio.run(names())
