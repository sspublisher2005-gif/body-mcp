"""The operating procedure must reach agents over MCP, not just via our repo docs."""
import asyncio

from mcp import Client

from body_mcp import server


def test_past_lessons_are_included_in_the_diagnosis():
    r = asyncio.run(server.body_failure_context(code="STALE_REF", tool="hands_click"))
    assert "past_lessons" in r["data"]
    assert isinstance(r["data"]["past_lessons"], list)
    assert len(r["data"]["past_lessons"]) <= 3


def test_mcp_handshake_delivers_instructions_and_prompt():
    async def flow():
        async with Client(server.mcp) as client:

            prompts = await client.list_prompts()
            names = [p.name for p in prompts.prompts]
            text = await client.get_prompt("body_operating_procedure")
            return names, text.messages[0].content.text

    names, text = asyncio.run(flow())
    assert "body_operating_procedure" in names
    assert "body_capabilities()" in text
    assert "body_failure_context" in text
    assert "webfetch" in text


def test_server_instructions_are_set():
    assert "body_capabilities()" in server.mcp.instructions
    assert "body_failure_context()" in server.mcp.instructions
