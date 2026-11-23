"""Progressive disclosure: focus narrows tools/list without deleting anything."""
import asyncio

from mcp import Client

from body_mcp import focus, server


def test_default_focus_is_core():
    # A fresh client pays ~8 KB of schema, not ~53 KB.
    assert focus.current() == "core"
    listed = asyncio.run(server.mcp.list_tools())
    names = {tool.name for tool in listed}
    assert len(names) == len(focus.CORE)
    assert "body_capabilities" in names
    assert "hands_click" not in names  # widened with body_focus, never required


def test_focus_widens_and_restores_the_list():
    async def flow():
        async with Client(server.mcp) as client:
            core = len((await client.list_tools()).tools)
            await client.call_tool("body_focus", {"mode": "all"})
            wide = len((await client.list_tools()).tools)
            await client.call_tool("body_focus", {"mode": "browser"})
            browser = len((await client.list_tools()).tools)
            await client.call_tool("body_focus", {"mode": "core"})
            back = len((await client.list_tools()).tools)
            return core, wide, browser, back

    core, wide, browser, back = asyncio.run(flow())
    assert wide == 83
    assert core == back == len(focus.CORE)
    assert core < browser < wide, (core, browser, wide)
    assert focus.current() == "core"


def test_hidden_tools_stay_callable():
    async def flow():
        async with Client(server.mcp) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            assert "hands_click" not in names  # hidden from the default view
            # but still callable by name
            result = await client.call_tool("hands_click", {"target": "no-such-element"})
            assert "success" in result.content[0].text or result.isError

    asyncio.run(flow())


def test_unknown_focus_is_refused():
    result = asyncio.run(server.body_focus(mode="admin"))
    assert result["success"] is False
    assert "unknown focus" in result["message"]
