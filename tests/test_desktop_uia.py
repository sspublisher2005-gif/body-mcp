"""Desktop control (UIA) and the YouTube reference search: unit level."""
import asyncio
import json

from body_mcp import server, uia, youtube_search


class FakeControl:
    def __init__(self, name, control_type="Button", enabled=True):
        self.element_info = type("Info", (), {"name": name, "control_type": control_type})()
        self._enabled = enabled
        self.clicked = False
        self.typed = None

    def is_enabled(self):
        return self._enabled

    def is_visible(self):
        return True

    def rectangle(self):
        class _Rect:
            left = 0
            top = 0

            @staticmethod
            def width():
                return 10

            @staticmethod
            def height():
                return 10

        return _Rect()

    def invoke(self):
        self.clicked = True

    def set_focus(self):
        return None

    def set_edit_text(self, text):
        self.typed = text

    def type_keys(self, text, **kwargs):
        self.typed = (self.typed or "") + text

    def get_value(self):
        return self.typed or ""


class FakeWindow:
    def __init__(self, controls, title="Fake - Notepad"):
        self._controls = controls
        self._title = title

    def descendants(self):
        return self._controls

    def window_text(self):
        return self._title

    def set_focus(self):
        return None


def test_uia_finds_controls_by_name(monkeypatch):
    button = FakeControl("Save")
    field = FakeControl("Text editor", "Edit")
    monkeypatch.setattr(uia, "_connect", lambda title, timeout=10.0: FakeWindow([button, field]))
    result = uia.inspect("Fake")
    assert result["ok"] is True
    assert result["count"] == 2
    assert {c["name"] for c in result["controls"]} == {"Save", "Text editor"}


def test_uia_refuses_password_like_fields(monkeypatch):
    monkeypatch.setattr(uia, "_connect", lambda title, timeout=10.0: FakeWindow([]))
    result = uia.type_text("Fake", "Password", "hunter2")
    assert result["ok"] is False
    assert "password" in result["reason"].lower()


def test_uia_click_invokes_the_named_control(monkeypatch):
    button = FakeControl("Save")
    other = FakeControl("Delete")
    monkeypatch.setattr(uia, "_connect", lambda title, timeout=10.0: FakeWindow([button, other]))
    result = uia.click("Fake", "Save")
    assert result["ok"] is True
    assert button.clicked is True
    assert other.clicked is False


def test_uia_refuses_an_unknown_control(monkeypatch):
    monkeypatch.setattr(uia, "_connect", lambda title, timeout=10.0: FakeWindow([FakeControl("Save")]))
    result = uia.click("Fake", "NoSuchButton")
    assert result["ok"] is False
    assert "no control named" in result["reason"]


def test_uia_read_value_is_the_verification_step(monkeypatch):
    field = FakeControl("Text editor", "Edit")
    monkeypatch.setattr(uia, "_connect", lambda title, timeout=10.0: FakeWindow([field]))
    uia.type_text("Fake", "Text editor", "hello")
    read = uia.read_value("Fake", "Text editor")
    assert read["ok"] is True
    assert "hello" in read["value"]


def test_uia_reports_a_missing_window():
    result = uia.inspect("ThereIsNoSuchWindowAnywhere")
    assert result["ok"] is False
    assert result["reason"]


def test_youtube_search_parses_results(monkeypatch):
    payload = {
        "contents": {"videoRenderer": {
            "videoId": "abc123", "title": {"simpleText": "A reference video"},
            "ownerText": {"simpleText": "Some Channel"}, "viewCountText": {"simpleText": "1.2M views"},
            "publishedTimeText": {"simpleText": "3 days ago"},
            "lengthText": {"simpleText": "12:22"},
            "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [{"baseUrl": "x"}]}},
        }}}
    page = 'var ytInitialData = ' + json.dumps(payload) + ';'
    monkeypatch.setattr(youtube_search, "_youtube_search_html", lambda query: page)
    result = youtube_search.youtube_search("reference", limit=3)
    assert result["count"] == 1
    item = result["results"][0]
    assert item["video_id"] == "abc123"
    assert item["title"] == "A reference video"
    assert item["channel"] == "Some Channel"
    assert item["age"] == "3 days ago"
    assert item["captions_available"] is True


def test_youtube_search_survives_a_blocked_page(monkeypatch):
    monkeypatch.setattr(youtube_search, "_youtube_search_html", lambda query: "<html>nothing</html>")
    result = youtube_search.youtube_search("reference")
    assert result["count"] == 0
    assert result["note"]


def test_desktop_tools_are_exposed_and_gated():
    async def names():
        tools = await server.mcp.list_tools()
        return [tool.name for tool in tools]

    listed = asyncio.run(names())
    for tool in ("desktop_inspect", "desktop_click", "desktop_type", "desktop_read_value",
                 "research_youtube_search"):
        assert tool in listed, tool
