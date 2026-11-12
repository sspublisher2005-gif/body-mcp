"""Video evidence: honest verdicts when the page refuses us."""
import urllib.error

from body_mcp import video


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://www.youtube.com/watch?v=x", code, "boom", None, None)


def test_a_rate_limited_page_is_blocked_not_failed(monkeypatch):
    def refuse(url, timeout=25.0):
        raise _http_error(429)

    monkeypatch.setattr(video, "_fetch", refuse)
    record = video.collect_video("https://www.youtube.com/watch?v=x")
    assert record["status"] == "BLOCKED", record
    assert record["verification"] == "FAILED"
    assert "rate limit" in record["limitation"]


def test_a_forbidden_page_is_blocked(monkeypatch):
    def refuse(url, timeout=25.0):
        raise _http_error(403)

    monkeypatch.setattr(video, "_fetch", refuse)
    record = video.collect_video("https://www.youtube.com/watch?v=x")
    assert record["status"] == "BLOCKED"


def test_a_missing_page_is_failed(monkeypatch):
    def refuse(url, timeout=25.0):
        raise OSError("no route to host")

    monkeypatch.setattr(video, "_fetch", refuse)
    record = video.collect_video("https://www.youtube.com/watch?v=x")
    assert record["status"] == "FAILED"
    assert "could not fetch" in record["limitation"]


def test_an_empty_caption_track_is_reported_not_invented(monkeypatch):
    """The endpoint returned 0 bytes here - the tool must say so, not guess."""
    page = ('{"captions":{"playerCaptionsTracklistRenderer":{"captionTracks":'
            '[{"baseUrl":"https://www.youtube.com/api/timedtext?v=x","languageCode":"en",'
            '"name":{"simpleText":"English"}}]}}}')
    monkeypatch.setattr(video, "_fetch", lambda url, timeout=25.0: page)
    monkeypatch.setattr(video, "_player_response", lambda html: {
        "captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
            {"baseUrl": "https://www.youtube.com/api/timedtext?v=x", "languageCode": "en",
             "name": {"simpleText": "English"}}]}},
        "videoDetails": {"title": "A video", "author": "A channel"}})
    monkeypatch.setattr(video, "_transcript", lambda track: {
        "ok": False, "lines": [], "error": "the caption track was not in a readable format"})
    record = video.collect_video("https://www.youtube.com/watch?v=x")
    assert record["captions_available"] is True
    assert record["verification"] == "UNCONFIRMED"
    assert record["transcript"] == "", "no transcript may be invented"
    assert record["limitation"]
