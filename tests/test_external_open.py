"""Opening a URL in the user's own browser: safe by construction."""
import asyncio

from body_mcp import launch, server


def test_only_http_and_https_are_handed_over():
    for bad in ("file:///C:/Windows/System32/drivers/etc/hosts",
                "javascript:alert(1)",
                "ftp://example.com/",
                "data:text/html,<script>alert(1)</script>",
                "ms-msdt:/id PCWDiagnostic"):
        result = launch.open_external(bad)
        assert result["success"] is False, bad
        assert "scheme" in result["message"] or "host" in result["message"]


def test_empty_and_hostless_urls_are_refused():
    assert launch.open_external("")["success"] is False
    assert launch.open_external("https://")["success"] is False


def test_known_browsers_are_found_by_fixed_paths():
    for name in ("chrome", "edge", "brave", "firefox"):
        found = launch.find_browser(name)
        assert found is None or found.endswith(".exe")
    assert launch.find_browser("not-a-browser") is None


def test_unknown_browser_is_refused_before_anything_starts():
    result = launch.open_external("https://example.com", browser="not-a-browser")
    assert result["success"] is False
    assert "could not find" in result["message"]


def test_tool_passes_the_browser_through(monkeypatch):
    seen = {}

    def fake(url, browser=""):
        seen["url"] = url
        seen["browser"] = browser
        return {"success": True, "message": "ok", "data": {}}

    monkeypatch.setattr(launch, "open_external", fake)
    result = asyncio.run(server.body_open_external("https://example.com", browser="chrome"))
    assert result["success"] is True
    assert seen == {"url": "https://example.com", "browser": "chrome"}
