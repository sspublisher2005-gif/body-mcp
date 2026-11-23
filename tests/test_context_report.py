"""body_context_report measures the body's own context cost (researched 2026-11-22)."""
import asyncio
import json

from mcp import Client

from body_mcp import server


def test_context_report_is_measured_not_guessed():
    result = asyncio.run(server.body_context_report())
    assert result["success"] is True
    data = result["data"]
    assert data["total_tools"] == 83          # the full registry, not the focused view
    assert data["total_schema_bytes"] > 10000
    assert data["largest_schemas"]
    assert data["largest_schemas"][0]["tool"]
    assert "page_text_chars" in data["bounded_outputs"]
    assert "body_focus" in " ".join(data["advice"])
    assert "not tokens" in " ".join(data["advice"])


def test_context_report_over_real_mcp_and_focus_saves():
    async def flow():
        async with Client(server.mcp) as client:
            core = await client.call_tool("body_context_report", {})
            await client.call_tool("body_focus", {"mode": "all"})
            wide = await client.call_tool("body_context_report", {})
            await client.call_tool("body_focus", {"mode": "research"})
            focused = await client.call_tool("body_context_report", {})
            await client.call_tool("body_focus", {"mode": "core"})
            return core, wide, focused

    core, wide, focused = asyncio.run(flow())
    dc = json.loads(core.content[0].text)["data"]
    dw = json.loads(wide.content[0].text)["data"]
    df = json.loads(focused.content[0].text)["data"]
    assert dw["visible_tools"] == 83
    assert dw["saving_percent"] == 0
    assert dc["visible_tools"] < dw["visible_tools"]
    assert dc["saving_percent"] > 50           # the default view really is cheaper
    assert df["visible_tools"] < dw["visible_tools"]
    assert df["saving_percent"] > 0
