"""OCR providers and live desktop observation (no engine required for the unit tests)."""
import asyncio

from body_mcp import eyes, ocr, server, watch


def test_provider_registry_reports_every_engine_truthfully():
    providers = ocr.providers()
    names = {p["provider"] for p in providers}
    assert {"tesseract", "rapidocr"} <= names
    for entry in providers:
        assert "available" in entry
        if not entry["available"]:
            assert entry.get("reason"), "an unavailable engine must say why"


def test_get_provider_refuses_when_nothing_is_installed(monkeypatch):
    class Stub:
        def __init__(self, reason):
            self.reason = reason

        def available(self):
            return {"available": False, "reason": self.reason}

    monkeypatch.setitem(ocr.PROVIDERS, "tesseract", Stub("not installed"))
    monkeypatch.setitem(ocr.PROVIDERS, "rapidocr", Stub("not installed"))
    provider, info = ocr.get_provider()
    assert provider is None
    assert "installed" in info["reason"]


def test_tesseract_discovery_prefers_the_explicit_env_path(tmp_path, monkeypatch):
    fake = tmp_path / "tesseract.exe"
    fake.write_bytes(b"MZ")
    monkeypatch.setenv("BODY_MCP_TESSERACT_CMD", str(fake))
    provider = ocr.PROVIDERS["tesseract"]
    assert provider.binary() == str(fake)
    info = provider.available()
    assert info["available"] is True
    assert info["path"] == str(fake)


def test_tesseract_reports_a_missing_engine_with_the_install_command(monkeypatch):
    monkeypatch.delenv("BODY_MCP_TESSERACT_CMD", raising=False)
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    provider = ocr.PROVIDERS["tesseract"]
    monkeypatch.setattr(provider, "_candidates", lambda: [])
    info = provider.available()
    assert info["available"] is False
    assert "Tesseract" in info["reason"]
    assert info["install"]


def test_see_desktop_without_an_engine_returns_the_install_hint(monkeypatch):
    monkeypatch.setattr(eyes, "capture_png",
                        lambda monitor=1, region=None: {"ok": True, "png": b"PNG",
                                                        "bytes": 3, "region": {}})
    monkeypatch.setattr(eyes, "get_provider", lambda name=None: (None, {"available": False,
                                                                       "reason": "no engine"}))
    result = eyes.see_desktop()
    assert result["success"] is False
    assert "no OCR engine" in result["message"]
    assert result["data"]["capture_ok"] is True


def test_capture_failure_is_reported_truthfully(monkeypatch):
    monkeypatch.setattr(eyes, "capture_png",
                        lambda monitor=1, region=None: {"ok": False,
                                                        "reason": "screen capture failed"})
    result = eyes.see_desktop()
    assert result["success"] is False
    assert "screen capture failed" in result["message"]


def test_frame_hash_changes_only_when_the_frame_changes():
    assert eyes.frame_hash(b"a") == eyes.frame_hash(b"a")
    assert eyes.frame_hash(b"a") != eyes.frame_hash(b"b")


def test_watch_session_lifecycle_without_an_engine(monkeypatch):
    monkeypatch.setattr(eyes, "ocr_status", lambda: {"selected": "tesseract", "providers": []})
    frames = [b"frame-1", b"frame-1", b"frame-2"]

    def fake_capture(monitor=1, region=None):
        data = frames.pop(0) if frames else b"frame-2"
        return {"ok": True, "png": data, "bytes": len(data), "region": {}}

    monkeypatch.setattr(eyes, "capture_png", fake_capture)
    calls = []

    def fake_ocr(png_bytes, language="eng", provider_name=None):
        calls.append(png_bytes)
        return {"ok": True, "text": f"text for {png_bytes.decode()}", "provider": "tesseract",
                "duration_ms": 5, "confidence": 0.9, "lines": [], "warnings": []}

    monkeypatch.setattr(eyes, "ocr_text", fake_ocr)
    monkeypatch.setattr(watch, "MIN_INTERVAL_S", 0.05)
    watch.stop_all()

    started = watch.start(monitor=1, interval=0.05)
    assert started["success"] is True
    session_id = started["data"]["session_id"]

    import time

    deadline = time.time() + 15
    read = {}
    while time.time() < deadline:
        time.sleep(0.2)
        read = watch.read(session_id)
        if read.get("data", {}).get("ocr_skipped", 0) >= 1:
            break
    assert read.get("success") is True
    assert read["data"]["observations"] >= 1
    assert read["data"]["ocr_skipped"] >= 1, "an unchanged frame must not re-run OCR"
    assert len(calls) < 3, "OCR must not run for every identical frame"

    stopped = watch.stop(session_id)
    assert stopped["success"] is True
    assert watch.sessions() == []


def test_watch_requires_an_engine(monkeypatch):
    monkeypatch.setattr(eyes, "ocr_status", lambda: {"selected": None, "providers": []})
    result = watch.start()
    assert result["success"] is False
    assert "no OCR engine" in result["message"]


def test_watch_tools_are_exposed():
    assert asyncio.run(server.desktop_monitors())["success"] in (True, False)
    result = asyncio.run(server.desktop_watch_start())
    assert "success" in result
    assert asyncio.run(server.desktop_watch_read())["success"] in (True, False)
    assert asyncio.run(server.desktop_watch_stop())["success"] is True
