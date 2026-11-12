"""Privacy session: isolated context, nothing persisted, cleanup verified."""
import asyncio
import os

from body_mcp import privacy, server


def _fixture_url(name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "fixtures", name)
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def test_privacy_session_lifecycle_and_cleanup():
    async def flow():
        started = await server.privacy_session_start("test")
        assert started["success"] is True
        session_id = started["data"]["session_id"]
        assert "anonymous" in started["data"]["note"]

        opened = await server.privacy_session_open(session_id, _fixture_url("test_page.html"))
        assert opened["success"] is True
        # the URL is deliberately not echoed back in full
        assert "test_page.html" not in str(opened["data"])

        snap = await server.privacy_session_snapshot(session_id)
        assert snap["success"] is True
        assert snap["data"]["text"]

        ended = await server.privacy_session_end(session_id)
        assert ended["success"] is True
        assert ended["data"]["cleanup_verified"] is True
        assert privacy.get(session_id) is None

    asyncio.run(flow())


def test_privacy_session_keeps_nothing_in_the_event_stream():
    from body_mcp import events

    async def flow():
        events.bus.clear()
        started = await server.privacy_session_start("quiet")
        session_id = started["data"]["session_id"]
        await server.privacy_session_open(session_id, _fixture_url("test_page.html"))
        await server.privacy_session_snapshot(session_id)
        await server.privacy_session_end(session_id)
        blob = str(events.bus.recent(limit=50))
        assert "test_page.html" not in blob
        assert "quiet" not in blob

    asyncio.run(flow())


def test_privacy_session_refuses_unknown_session():
    result = asyncio.run(server.privacy_session_open("priv_missing", _fixture_url("test_page.html")))
    assert result["success"] is False


def test_privacy_session_end_is_idempotent_and_reports_state():
    started = privacy.start("state")
    session_id = started["data"]["session_id"]
    assert privacy.sessions()
    ended = asyncio.run(privacy.end(session_id))
    assert ended["success"] is True
    assert privacy.sessions() == []
    again = asyncio.run(privacy.end(session_id))
    assert again["success"] is False


def test_privacy_session_blocks_restricted_pages():
    async def flow():
        started = privacy.start("restricted")
        session_id = started["data"]["session_id"]
        opened = await privacy.open(session_id, _fixture_url("restricted_page.html"))
        # the page opens, but the snapshot reports the restriction instead of hiding it
        assert opened["success"] is True
        snap = await privacy.snapshot(session_id)
        assert snap["data"]["restricted"] is True
        await privacy.end(session_id)

    asyncio.run(flow())
