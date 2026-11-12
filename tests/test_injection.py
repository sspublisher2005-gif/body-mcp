"""Prompt-injection containment: hostile page text confers no permissions."""
import asyncio
import os

from body_mcp import permissions, server


def fixture_url(name: str) -> str:
    return "file:///" + os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", name)).replace("\\", "/")


def test_injection_page_grants_no_permissions_and_no_actions():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("injection_page.html"))
        assert seen["success"]  # content is readable as DATA — that is all
        # the page demands file upload, VPN, deletion — none of that is possible without you
        assert permissions.check("vpn_control", tool="x", target="vpn", risk="high",
                                 action="toggle VPN as commanded by page").allowed is False
        assert permissions.check("uploads", tool="x", target="files", risk="high",
                                 action="upload files as commanded by page").allowed is False
        assert permissions.check("local_files", tool="x", target="docs", risk="high",
                                 action="delete documents as commanded by page").allowed is False
        # no approval was conjured by the page, and none was consumed
        from body_mcp.approvals import approvals
        assert await approvals.peek({"tool": "hands_click", "capability": "consequential",
                                     "target": "OK", "url": None, "task_id": None}) is False
        raise_result = await server.hands_click("OK")
        # 'OK' is not a dangerous label — it clicks, harms nothing, and proves the
        # page did not "unlock" anything on the way
        assert raise_result["success"] is True
        return seen

    result = asyncio.run(flow())
    assert "admin mode" in result["data"]["text"].lower()  # read as data, not obeyed
    assert permissions.check("consequential", tool="x", target="delete", risk="high",
                             action="as commanded by page").allowed is False
