"""Ears: record microphone audio and transcribe it locally with faster-whisper.

Raw audio is processed in memory and NEVER written to disk or transmitted.
If sounddevice or faster-whisper is unavailable, the MCP server keeps running
and ears_listen returns a clear error.
"""


def record_mic(seconds: int):
    """Record mono float32 at 16 kHz from the default microphone."""
    import numpy as np
    import sounddevice as sd

    seconds = max(1, min(120, int(seconds)))
    try:
        audio = sd.rec(int(seconds * 16000), samplerate=16000, channels=1,
                       dtype="float32")
        sd.wait()
    except Exception as exc:
        raise RuntimeError(f"microphone capture failed: {exc}") from exc
    return np.asarray(audio).reshape(-1)


def transcribe(audio, model_size: str | None = None) -> dict:
    """Transcribe recorded audio with the selected local STT provider.

    Providers: faster-whisper (default), whisper.cpp, sherpa-onnx - see body_mcp.voice.
    Nothing is downloaded automatically and a heavy model is only loaded when there
    is enough free memory.
    """
    from . import voice

    result = voice.transcribe_array(audio, model=model_size)
    if not result.get("ok"):
        raise RuntimeError(result.get("error") or "transcription failed")
    return {"model": result.get("model") or model_size or "unknown",
            "language": result.get("language") or "unknown",
            "text": result.get("text") or "",
            "segments": result.get("segments") or [],
            "provider": result.get("provider")}


def record_speech(max_seconds: int = 15, silence_ms: int = 700,
                   threshold: float = 0.008, block_ms: int = 100):
    """Record until the speaker stops talking (or the time limit is reached).

    This is the human behaviour a push-to-talk button has: it waits for you to start
    and stops a moment after you stop, instead of always burning a fixed window.
    Returns (audio, meta) where meta says what ended the capture.
    """
    import time

    import numpy as np
    import sounddevice as sd

    max_seconds = max(1, min(120, int(max_seconds)))
    block_ms = max(20, min(500, int(block_ms)))
    blocks: list = []
    started = False
    quiet_ms = 0
    ended_by = "max_seconds"
    rate = 16000

    def callback(indata, frames, time_info, status):  # noqa: ARG001
        blocks.append(indata.copy())

    stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32",
                            blocksize=int(rate * block_ms / 1000), callback=callback)
    try:
        stream.start()
        deadline = time.monotonic() + max_seconds
        while time.monotonic() < deadline:
            time.sleep(block_ms / 1000.0)
            if not blocks:
                continue
            chunk = blocks.pop(0)
            level = float(np.sqrt(np.mean(np.square(chunk)))) if chunk.size else 0.0
            if level >= threshold:
                started = True
                quiet_ms = 0
            elif started:
                quiet_ms += block_ms
                if quiet_ms >= silence_ms:
                    ended_by = "silence"
                    break
        else:
            ended_by = "max_seconds"
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        # keep whatever was captured
        while blocks:
            blocks.pop(0)

    audio = np.concatenate([np.asarray(b, dtype="float32").reshape(-1) for b in blocks]) \
        if blocks else np.zeros(0, dtype="float32")
    return audio, {"started": started, "ended_by": ended_by, "seconds": len(audio) / rate,
                   "threshold": threshold, "silence_ms": silence_ms}


def _rms(audio) -> float:
    """Root-mean-square level of the recording (0.0 = pure silence)."""
    try:
        import numpy as np

        array = np.asarray(audio, dtype="float32")
        if array.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(array))))
    except Exception:
        return 0.0


def listen(seconds: int = 8, stop_on_silence: bool = True) -> dict:
    """Record the user and transcribe them locally.

    With `stop_on_silence` the recording ends shortly after the user stops talking
    (like a push-to-talk button), instead of always burning the whole window.
    """
    try:
        if stop_on_silence:
            audio, meta = record_speech(max_seconds=seconds)
            if not meta["started"]:
                return {"success": False,
                        "message": "no speech detected (nothing above the noise floor was "
                                   "heard before the limit)",
                        "data": {"silence": True, "rms": 0.0, **meta}}
            seconds_used = meta["seconds"]
        else:
            audio, meta = record_mic(seconds), {"started": True, "ended_by": "max_seconds",
                                               "seconds": float(seconds)}
            seconds_used = float(seconds)
    except RuntimeError as exc:
        return {"success": False, "message": str(exc),
                "data": {"hint": "check that a microphone is connected and permitted; "
                                 "sounddevice needs no drivers on Windows"}}
    except ImportError as exc:
        return {"success": False, "message": f"sounddevice unavailable: {exc}",
                "data": {"hint": "pip install sounddevice"}}
    level = _rms(audio)
    if level < 0.005:
        # silence: transcribing it would only invent words
        import contextlib

        with contextlib.suppress(Exception):
            audio.fill(0.0)
        return {"success": False,
                "message": ("no speech detected (the recording was essentially silent). "
                            "Speak after starting the recording, or check the microphone "
                            "input level."),
                "data": {"rms": round(level, 6), "silence": True,
                         "hint": "raise the input gain or move closer to the microphone"}}
    try:
        result = transcribe(audio)
    except ImportError as exc:
        return {"success": False,
                "message": f"faster-whisper unavailable: {exc}",
                "data": {"hint": "pip install faster-whisper (first run downloads the model into the HF cache)"}}
    except Exception as exc:
        return {"success": False, "message": f"transcription failed: {type(exc).__name__}: {exc}",
                "data": {"hint": "try BODY_MCP_WHISPER_MODEL=tiny.en, check disk space and HF cache"}}
    finally:
        # scrub raw audio from memory before returning (never written to disk)
        import contextlib
        with contextlib.suppress(Exception):
            audio.fill(0.0)
    uncertain = [s.get("text") for s in result.get("segments", [])
                 if s.get("confidence") is not None and s["confidence"] < 0.6]
    return {"success": True,
            "message": "audio transcribed locally; raw audio was never stored",
            "data": {"transcript": result["text"],
                     "language": result["language"],
                     "model": result["model"],
                     "provider": result.get("provider"),
                     "rms": round(level, 6),
                     "seconds": seconds_used,
                     "ended_by": meta.get("ended_by"),
                     "uncertain": uncertain,
                     "uncertain_note": "these fragments were recognised with low confidence - "
                                       "ask the user to confirm them",
                     "segments": result["segments"]}}
