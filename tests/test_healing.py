"""The self-healing entry point: diagnosis, never auto-fix."""
import asyncio
import json

from mcp import Client

from body_mcp import server


def test_known_error_gives_its_catalog_fix():
    r = asyncio.run(server.body_failure_context(code="STALE_REF", tool="hands_click"))
    d = r["data"]
    assert "eyes_see_browser" in d["known_fix"]
    assert d["tool"] == "hands_click"
    assert "reflex_verify" in " ".join(d["loop"])


def test_retry_limit_stops_the_loop():
    r = asyncio.run(server.body_failure_context(code="X", attempt=3))
    assert "limit reached" in r["data"]["retry_rule"]


def test_blocks_are_never_healed_around():
    r = asyncio.run(server.body_failure_context(code="BLOCKED_BY_CAPTCHA"))
    assert "bypass a block" in r["data"]["never"]
    assert "human" in r["data"]["known_fix"].lower() or "human" in r["data"]["never"][1]


def test_unknown_code_says_research_before_guessing():
    r = asyncio.run(server.body_failure_context(code="SOMETHING_NEW"))
    assert "research before guessing" in r["data"]["known_fix"]


def test_over_real_mcp_and_never_auto_applies():
    async def flow():
        async with Client(server.mcp) as client:
            return await client.call_tool("body_failure_context", {"code": "STALE_REF"})

    r = asyncio.run(flow())
    data = json.loads(r.content[0].text)["data"]
    assert data["code"] == "STALE_REF"
    assert "auto-apply" in data["never"]
