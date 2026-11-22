"""body_context_report measures the body's own context cost (researched 2026-11-22)."""
import asyncio

from mcp import Client

from body_mcp import server


def test_context_report_is_measured_not_guessed():
    result = asyncio.run(server.body_context_report())
    assert result["success"] is True
    data = result["data"]
    assert data["total_tools"] == 83
    assert data["total_schema_bytes"] > 10000
    assert data["largest_schemas"]
    assert data["largest_schemas"][0]["tool"]
    assert "page_text_chars" in data["bounded_outputs"]
    assert "body_focus" in " ".join(data["advice"])
    assert "not tokens" in " ".join(data["advice"])


def test_context_report_over_real_mcp_and_focus_saves():
    async def flow():
        async with Client(server.mcp) as client:
            all_report = await client.call_tool("body_context_report", {})
            await client.call_tool("body_focus", {"mode": "research"})
            focused = await client.call_tool("body_context_report", {})
            await client.call_tool("body_focus", {"mode": "all"})
            return all_report, focused

    a, b = asyncio.run(flow())
    import json

    da = json.loads(a.content[0].text)["data"]
    db = json.loads(b.content[0].text)["data"]
    assert db["visible_tools"] < da["visible_tools"]
    assert db["visible_schema_bytes"] < da["visible_schema_bytes"]
    assert db["saving_percent"] > 0
