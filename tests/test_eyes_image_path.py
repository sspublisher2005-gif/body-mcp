"""The body must be able to SEE, even where Tesseract is missing.

Three gates used to make the body blind:
  1. eyes_see_desktop(as_image=True) bailed out when no OCR engine was installed,
     throwing the screenshot away - even for a vision model.
  2. desktop_watch_start refused to start without an OCR engine.
  3. body_local_worker had no way to describe an image with a local vision model.
"""
import asyncio
import json

from body_mcp import eyes, local_worker, server, watch


class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_ollama(calls, tags=None):
    """A stand-in for the Ollama HTTP API that records what was sent."""
    tags = tags if tags is not None else ["gemma3:270m", "qwen3:0.6b"]

    def opener(request, timeout=None):
        calls.append(request)
        if request.full_url.endswith("/api/tags"):
            return FakeResponse({"models": [{"name": name, "size": 1000,
                                             "details": {"family": name.split(":")[0]}}
                                            for name in tags]})
        if request.full_url.endswith("/api/generate"):
            return FakeResponse({"response": "- a code editor with a red error banner",
                                 "total_duration": 5_000_000})
        raise AssertionError(f"unexpected URL: {request.full_url}")

    return opener


def test_the_desktop_eye_attaches_the_image_without_an_ocr_engine(monkeypatch):
    """The whole point: no Tesseract must not mean blind."""
    monkeypatch.setattr(eyes, "capture_png", lambda monitor=1, region=None: {
        "ok": True, "png": b"\x89PNG\r\n\x1a\n" + b"0" * 100, "bytes": 108,
        "region": {"left": 0, "top": 0, "width": 10, "height": 10}})
    monkeypatch.setattr(eyes, "get_provider", lambda name=None: (None, {"reason": "not installed",
                                                                        "install": "winget install ..."}))
    payload = eyes.see_desktop(as_image=False)
    # without an image the old behaviour stays: refuse, do not pretend
    assert payload["success"] is False
    assert "no OCR engine" in payload["message"]

    monkeypatch.setattr("body_mcp.vision.prepare_image", lambda png, **kw: {
        "ok": True, "data": "BASE64", "mime_type": "image/jpeg", "bytes": 10,
        "width": 100, "height": 100, "downscaled": False, "note": "test"})
    monkeypatch.setattr("body_mcp.vision.with_image",
                        lambda p, prepared: {**p, "image": prepared["data"]})
    with_image = eyes.see_desktop(as_image=True)
    assert with_image["success"] is True, with_image
    assert with_image["data"]["text"] == ""
    assert with_image["data"]["provider"] is None
    assert with_image["image"] == "BASE64", "the image must survive without OCR"


def test_the_watcher_can_run_without_ocr(monkeypatch):
    monkeypatch.setattr(eyes, "ocr_status", lambda: {"selected": None, "providers": []})
    refused = watch.start()
    assert refused["success"] is False
    assert "ocr=False" in refused["message"], "the refusal must say how to watch as images"

    started = watch.start(ocr=False)
    assert started["success"] is True, started
    assert started["data"]["ocr"] is False
    watch.stop(started["data"]["session_id"])


def test_describe_uses_a_local_vision_model(monkeypatch):
    import urllib.request

    calls = []
    monkeypatch.setattr(local_worker, "ollama_installed", lambda: True)
    monkeypatch.setattr(urllib.request, "urlopen", fake_ollama(calls))
    result = local_worker.run("describe", "", image="BASE64PNG")
    assert result["ok"] is True, result
    assert result["model"] == "gemma3:270m", "it must pick a VISION model, not the text one"
    body = json.loads(calls[-1].data.decode("utf-8"))
    assert body["images"] == ["BASE64PNG"], "the image goes to the local runtime"
    assert body["model"] == "gemma3:270m"


def test_describe_refuses_a_text_only_model(monkeypatch):
    """A text model would invent a caption - that is worse than no caption."""
    import urllib.request

    calls = []
    monkeypatch.setattr(local_worker, "ollama_installed", lambda: True)
    monkeypatch.setattr(urllib.request, "urlopen", fake_ollama(calls, tags=["qwen3:0.6b"]))
    result = local_worker.run("describe", "", image="BASE64PNG")
    assert result["ok"] is False
    assert "VISION model" in result["reason"]
    # the local model LIST may be read, but no image may be sent to a text model
    assert not [call for call in calls if call.full_url.endswith("/api/generate")]


def test_describe_needs_an_image():
    result = local_worker.run("describe", "", image=None)
    assert result["ok"] is False
    assert "needs an image" in result["reason"]


def test_the_tool_passes_the_image_through(monkeypatch):
    seen = {}

    def fake_run(task, text, image=None):
        seen["args"] = (task, text, image)
        return {"ok": True, "text": "a screen", "model": "gemma3:270m", "runtime": "ollama",
                "duration_ms": 3}

    monkeypatch.setattr(local_worker, "run", fake_run)
    result = asyncio.run(server.body_local_worker(task="describe", text="",
                                                   image="BASE64PNG"))
    assert result["success"] is True
    assert seen["args"] == ("describe", "", "BASE64PNG")


def test_the_status_no_longer_claims_the_vpn_is_unimplemented():
    status = asyncio.run(server.body_status())
    perception = status["data"]["state_perception"]
    assert "not_implemented" not in perception["vpn_control"]
    assert "privacy_vpn_connect" in perception["vpn_control"]
    assert "local_worker" in perception
    assert status["data"]["vision"]["needs_ocr"] is False
