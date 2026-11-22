"""Local tool discovery: the Tool Search idea, reimplemented without a proprietary API."""
import asyncio

from body_mcp import server


def test_search_finds_a_tool_from_a_paraphrase():
    r = asyncio.run(server.body_tool_search("verify a click changed the page"))
    assert r["success"] is True
    names = [x["tool"] for x in r["data"]["results"]]
    assert "reflex_verify" in names or "hands_batch" in names, names
    assert all("why" in x for x in r["data"]["results"])


def test_search_respects_the_limit_and_is_bounded():
    r = asyncio.run(server.body_tool_search("browser", limit=3))
    assert len(r["data"]["results"]) <= 3


def test_no_match_falls_back_to_capabilities():
    r = asyncio.run(server.body_tool_search("zzzznotarealtool"))
    assert r["success"] is False
    assert "body_capabilities()" in r["message"]
