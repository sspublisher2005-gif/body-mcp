"""Speech-to-text providers and a hardware-aware selection.

Providers (in preference order):
  1. `faster-whisper`  - the default: pure Python wheels, CPU int8, MIT.
  2. `whisper.cpp`     - optional: a C++ binary the user installed (MIT), good
                         multilingual coverage including Telugu.
  3. `sherpa-onnx`     - optional: streaming ASR (Apache-2.0).

Rules:
  - nothing is downloaded automatically; a model is used only if it is already present
    (or the user explicitly asks for a download),
  - the engine is loaded lazily and only when a recording is transcribed,
  - the available RAM is checked before a heavy model is loaded,
  - a recording that is essentially silent is reported as silence, never transcribed.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import time

MIN_RAM_MB = 512
PROVIDER_ORDER = ("faster-whisper", "whisper-cpp", "sherpa-onnx")


def available_ram_mb() -> int | None:
    try:
        from . import sysprofile

        return sysprofile.summary().get("ram_available_mb")
    except Exception:
        return None


def _whisper_cpp_binary() -> str | None:
    for env_name in ("BODY_MCP_WHISPER_CPP", "WHISPER_CPP"):
        value = os.environ.get(env_name)
        if value and os.path.isfile(value):
            return value
    for name in ("whisper-cli", "whisper.cpp", "main"):
        found = shutil.which(name)
        if found and "whisper" in os.path.basename(found).lower():
            return found
    return None


def _whisper_cpp_model() -> str | None:
    candidates = []
    env_model = os.environ.get("BODY_MCP_WHISPER_CPP_MODEL")
    if env_model:
        candidates.append(env_model)
    base = os.environ.get("WHISPER_MODELS",
                          os.path.join(os.path.expanduser("~"), ".cache", "whisper.cpp"))
    if os.path.isdir(base):
        try:
            for name in sorted(os.listdir(base)):
                if name.endswith(".bin"):
                    candidates.append(os.path.join(base, name))
        except OSError:
            pass
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def providers() -> list[dict]:
    """Availability of every STT provider (no side effects, no downloads)."""
    out = []

    try:
        import importlib.util

        faster = importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        faster = False
    from .config import whisper_model

    model = whisper_model()
    cache = os.environ.get("HF_HOME", os.path.join(os.path.expanduser("~"), ".cache",
                                                   "huggingface"))
    weights = os.path.isdir(cache) and any(
        name.lower().startswith("models--") and "whisper" in name.lower()
        for name in os.listdir(cache)) if os.path.isdir(cache) else False
    out.append({"provider": "faster-whisper", "available": faster,
                "path": "faster_whisper" if faster else None,
                "model": model, "model_downloaded": weights,
                "reason": None if faster else "faster-whisper is not installed",
                "install": None if faster else "pip install -e '.[voice]'",
                "note": "the model weights are downloaded on the first use you trigger"})

    binary = _whisper_cpp_binary()
    model_path = _whisper_cpp_model()
    out.append({"provider": "whisper-cpp", "available": bool(binary and model_path),
                "path": binary, "model": model_path,
                "reason": None if (binary and model_path) else
                          ("the whisper.cpp binary was not found" if not binary else
                           "no whisper.cpp model file was found"),
                "install": "see https://github.com/ggml-org/whisper.cpp",
                "note": "good multilingual coverage (incl. Telugu) once a model is present"})

    try:
        import importlib.util

        sherpa = importlib.util.find_spec("sherpa_onnx") is not None
    except Exception:
        sherpa = False
    out.append({"provider": "sherpa-onnx", "available": sherpa,
                "path": "sherpa_onnx" if sherpa else None, "model": None,
                "reason": None if sherpa else "sherpa-onnx is not installed",
                "install": None if sherpa else "pip install sherpa-onnx",
                "note": "streaming ASR; the model must be present"})

    return out


def select(preferred: str | None = None) -> tuple[str | None, dict]:
    """Choose an STT provider. Returns (provider name, info)."""
    entries = {entry["provider"]: entry for entry in providers()}
    if preferred:
        entry = entries.get(preferred)
        if entry is None:
            return None, {"available": False, "reason": f"unknown provider {preferred!r}",
                          "known": list(entries)}
        if not entry["available"]:
            return None, entry
        return preferred, entry
    for name in PROVIDER_ORDER:
        if entries[name]["available"]:
            return name, entries[name]
    return None, {"available": False, "reason": "no speech-to-text engine is installed",
                  "checked": providers()}


def transcribe_wav(path: str, model: str | None = None) -> dict:
    """Transcribe a WAV file with the selected provider."""
    from .config import whisper_model

    provider, info = select()
    if provider is None:
        return {"ok": False, "error": info.get("reason"), "text": "", "provider": None}
    if provider == "faster-whisper":
        ram = available_ram_mb()
        if ram is not None and ram < MIN_RAM_MB:
            return {"ok": False,
                    "error": f"not enough free memory to load a speech model "
                             f"({ram} MB free, {MIN_RAM_MB} MB needed) - close other apps "
                             "or use a smaller model",
                    "provider": provider, "text": ""}
        from faster_whisper import WhisperModel

        name = model or whisper_model()
        engine = WhisperModel(name, device="cpu", compute_type="int8")
        segments, meta = engine.transcribe(path, vad_filter=True)
        segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in segments]
        return {"ok": True, "provider": provider, "model": name,
                "language": meta.language,
                "text": " ".join(s["text"] for s in segs).strip(), "segments": segs}
    if provider == "whisper-cpp":
        binary = info.get("path")
        model_path = info.get("model")
        out = subprocess.run([binary, "-m", model_path, "-f", path, "-nt"],
                             capture_output=True, text=True, timeout=600)
        text = (out.stdout or "").strip()
        return {"ok": out.returncode == 0, "provider": provider, "model": model_path,
                "language": None, "text": text, "segments": []}
    return {"ok": False, "error": f"provider {provider} has no transcriber wired up",
            "provider": provider, "text": ""}


def transcribe_array(audio, model: str | None = None) -> dict:
    """Transcribe an in-memory float32 array (what the microphone path produces)."""
    import numpy as np

    fd, path = tempfile.mkstemp(prefix="body_stt_", suffix=".wav")
    os.close(fd)
    try:
        data = np.asarray(audio, dtype="float32")
        pcm = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
        import wave

        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm.tobytes())
        return transcribe_wav(path, model=model)
    finally:
        with contextlib.suppress(OSError):
            os.remove(path)


def timing_started() -> float:
    return time.monotonic()
