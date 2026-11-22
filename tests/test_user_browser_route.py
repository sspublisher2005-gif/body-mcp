"""A blocked source must ASK the user, and research must prefer the user's browser."""
from body_mcp import sources


def test_blocked_source_gives_the_user_a_route_not_a_silent_substitute():
    r = sources.search("x", "some query")
    assert r["success"] is False
    assert r["status"] == "needs_user"
    assert "log in yourself in YOUR browser" in r["options"][0]
    assert "browser_bridge" in r["options"][0] and "attach_browser" in r["options"][0]
    assert "never logs in or types credentials" in r["options"][0]


def test_rate_limited_source_also_gives_a_user_route(monkeypatch):
    monkeypatch.setattr(sources, "_get_json", lambda url, name: (None, "HTTP 403: Forbidden"))
    r = sources.search("reddit", "some query")
    assert r["success"] is False
    assert r["status"] == "needs_user"


def test_search_any_failure_is_needs_user_with_a_route(monkeypatch):
    monkeypatch.setattr(sources, "search", lambda name, query, limit=8: {
        "success": False, "source": name, "items": [], "reason": "blocked",
        "status": "needs_user"})
    r = sources.search_any("query", sources=["reddit"], allow_browser=False)
    assert r["success"] is False
    assert r["status"] == "needs_user"
    assert "log in yourself" in r["user_route"]["options"][0]


def test_browser_choice_prefers_cdp_then_extension_then_managed(monkeypatch):
    import asyncio

    from body_mcp import research

    async def fake_page():
        return object()

    async def fake_context():
        return object(), object()

    monkeypatch.setattr(research, "browser", type("B", (), {
        "ensure_page": staticmethod(fake_page),
        "new_isolated_context": staticmethod(fake_context),
    })())

    # 1. CDP attached wins
    monkeypatch.setattr("body_mcp.attach.attached_status", lambda: {"attached": True})
    monkeypatch.setattr("body_mcp.bridge.status", lambda: {"extension_connected": True})
    _, _, label = asyncio.run(research._browser_for_research())
    assert "CDP" in label

    # 2. extension bridge next
    monkeypatch.setattr("body_mcp.attach.attached_status", lambda: {"attached": False})
    _, _, label = asyncio.run(research._browser_for_research())
    assert "extension bridge" in label

    # 3. managed browser last, and says so honestly
    monkeypatch.setattr("body_mcp.bridge.status", lambda: {"extension_connected": False})
    _, _, label = asyncio.run(research._browser_for_research())
    assert "not connected" in label and "managed Chromium" in label
