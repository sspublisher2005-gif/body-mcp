"""Progressive disclosure: focus narrows tools/list without deleting anything."""
import asyncio

from mcp import Client

from body_mcp import focus, server


def test_default_focus_is_all():
    assert focus.current() == "all"
    assert len(asyncio.run(server.mcp.list_tools())) == 83


def test_focus_narrows_and_restores_the_list():
    async def flow():
        async with Client(server.mcp) as client:
            before = len((await client.list_tools()).tools)
            result = await client.call_tool("body_focus", {"mode": "browser"})
            assert "success" in result.content[0].text
            during = len((await client.list_tools()).tools)
            await client.call_tool("body_focus", {"mode": "all"})
            after = len((await client.list_tools()).tools)
            return before, during, after

    before, during, after = asyncio.run(flow())
    assert before == after == 83
    assert 10 <= during < before, (before, during)
    assert focus.current() == "all"  # restored even after the client closed


def test_hidden_tools_stay_callable():
    async def flow():
        async with Client(server.mcp) as client:
            await client.call_tool("body_focus", {"mode": "research"})
            names = {t.name for t in (await client.list_tools()).tools}
            assert "hands_click" not in names  # hidden from the view
            # but still callable by name
            result = await client.call_tool("hands_click", {"target": "no-such-element"})
            assert "success" in result.content[0].text or result.isError
            await client.call_tool("body_focus", {"mode": "all"})

    asyncio.run(flow())


def test_unknown_focus_is_refused():
    result = asyncio.run(server.body_focus(mode="admin"))
    assert result["success"] is False
    assert "unknown focus" in result["message"]
