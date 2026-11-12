"""Voice: the engine-aware TTS adapter + the silence handling for the mic path.

The TTS adapter uses the engine the OS already provides (Windows SAPI, macOS
`say`, Linux espeak/spd-say) and never installs one; Piper/Kokoro/edge-tts are
optional and reported, not fetched.
"""
import asyncio
import os

import numpy as np

from body_mcp import ears, server, tts


def test_engine_detection_lists_os_providers_first():
    engines = tts.detect_engines()
    names = [engine["name"] for engine in engines]
    assert "windows-sapi" in names and "macos-say" in names and "linux-espeak" in names
    for engine in engines:
        assert "available" in engine and "install" in engine and "remote" in engine
    # the remote engine is never presented as the default
    edge = next(engine for engine in engines if engine["name"] == "edge-tts")
    assert edge["remote"] is True
    # the GPL engine is flagged so nobody bundles it
    piper = next(engine for engine in engines if engine["name"] == "piper")
    assert "GPL" in (piper["install"] or "")


def test_preferred_engine_is_the_os_one():
    name, info = tts.preferred_engine()
    if os.name == "nt":
        assert name == "windows-sapi"
        assert info["os_provided"] is True
    assert info.get("downloads") is None or info.get("downloads") is False


def test_available_reports_the_reason_when_nothing_is_installed(monkeypatch):
    monkeypatch.setattr(tts, "detect_engines", lambda: [
        {"name": "windows-sapi", "os": "Windows", "os_provided": True, "available": False,
         "path": None, "install": None, "remote": False, "note": ""}])
    info = tts.available()
    assert info["available"] is False
    assert "no speech engine" in info["reason"]


def test_speak_refuses_an_empty_or_huge_text(monkeypatch):
    monkeypatch.setattr(tts, "preferred_engine",
                        lambda: ("windows-sapi", {"available": True, "os_provided": True}))
    assert tts.speak("")["success"] is False
    assert tts.speak("x" * (tts.MAX_CHARS + 1))["success"] is False


def test_speak_reports_a_missing_engine(monkeypatch):
    monkeypatch.setattr(tts, "preferred_engine",
                        lambda: (None, {"available": False, "reason": "none installed"}))
    result = tts.speak("hello")
    assert result["success"] is False
    assert "no speech engine" in result["message"]


def test_speak_synthesises_plays_and_reports(monkeypatch, tmp_path):
    monkeypatch.setattr(tts, "preferred_engine",
                        lambda: ("windows-sapi", {"available": True, "os_provided": True}))
    written = {}

    def fake_synthesize(engine, text, path, voice):
        written["engine"] = engine
        written["text"] = text
        with open(path, "wb") as handle:
            handle.write(b"RIFF" + b"0" * 64)
        return ""

    monkeypatch.setattr(tts, "_synthesize", fake_synthesize)
    monkeypatch.setattr(tts, "_start_playback", lambda path: {"started": True})
    result = tts.speak("hello world")
    assert result["success"] is True
    assert written["engine"] == "windows-sapi"
    assert result["data"]["engine"] == "windows-sapi"
    assert result["data"]["verification"] in ("UNCONFIRMED", "CONFIRMED")


def test_stop_cleans_up():
    result = tts.stop()
    assert result["success"] is True


def test_silence_is_detected_instead_of_inventing_words(monkeypatch):
    monkeypatch.setattr(ears, "record_speech",
                        lambda max_seconds=15, silence_ms=700: (
                            np.zeros(16000, dtype=np.float32),
                            {"started": False, "ended_by": "silence", "seconds": 1.0}))

    def boom(audio, model_size=None):
        raise AssertionError("silence must not reach the transcriber")

    monkeypatch.setattr(ears, "transcribe", boom)

    result = ears.listen(1)
    assert result["success"] is False
    assert result["data"]["silence"] is True
    assert "no speech" in result["message"].lower()


def test_speech_still_transcribes_when_there_is_signal(monkeypatch):
    audio = np.random.default_rng(7).normal(0, 0.2, 16000).astype(np.float32)
    monkeypatch.setattr(ears, "record_speech",
                        lambda max_seconds=15, silence_ms=700: (
                            audio, {"started": True, "ended_by": "silence", "seconds": 1.0}))
    monkeypatch.setattr(ears, "transcribe", lambda a, model_size=None:
                        {"model": "fake", "language": "en", "text": "hello", "segments": []})
    result = ears.listen(1)
    assert result["success"] is True
    assert result["data"]["transcript"] == "hello"
    assert result["data"]["rms"] > 0.005


def test_body_speak_tool_is_permission_gated():
    result = asyncio.run(server.body_speak("hello"))
    assert "success" in result
    stop = asyncio.run(server.body_stop_speaking())
    assert stop["success"] is True
