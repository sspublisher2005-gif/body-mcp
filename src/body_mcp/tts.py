"""Text-to-speech: use what the operating system already provides.

| OS | engine (already installed) | needs a download? |
|---|---|---|
| Windows | SAPI5 via System.Speech (built into Windows) | **no** |
| macOS | `say` (built into macOS) | **no** |
| Linux | `espeak-ng` / `espeak` / `spd-say` (present on most desktops) | **no** |
| any | Piper / Kokoro / edge-tts | yes - optional, user-installed |

Rule: **never install a speech engine that the OS already has.** The engines below are
detected, not installed; a better-sounding engine is only ever *suggested*, never
fetched behind your back. `edge-tts` is remote (it sends the text to Microsoft) and is
therefore never enabled by default.

Playback is done by the OS player (`winsound` / `afplay` / `aplay`) and can always be
stopped. The temporary audio file is deleted afterwards.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import threading
import time

MAX_CHARS = 4000
_state: dict = {"player": None, "path": None, "started_at": None, "engine": None, "voice": None}
_lock = threading.Lock()


def _which(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def detect_engines() -> list[dict]:
    """Every engine we know about, and whether it is already installed."""
    engines = [
        {"name": "windows-sapi", "os": "Windows", "os_provided": True,
         "available": os.name == "nt",
         "path": "System.Speech (PowerShell)" if os.name == "nt" else None,
         "install": None, "remote": False,
         "note": "built into Windows - nothing to install"},
        {"name": "macos-say", "os": "macOS", "os_provided": True,
         "available": sys_platform() == "darwin",
         "path": _which("say") if sys_platform() == "darwin" else None,
         "install": None, "remote": False,
         "note": "built into macOS - nothing to install"},
        {"name": "linux-espeak", "os": "Linux", "os_provided": True,
         "available": bool(_which("espeak-ng", "espeak")),
         "path": _which("espeak-ng", "espeak"),
         "install": None, "remote": False,
         "note": "usually preinstalled (apt install espeak-ng) - check before installing"},
        {"name": "linux-speech-dispatcher", "os": "Linux", "os_provided": True,
         "available": bool(_which("spd-say")),
         "path": _which("spd-say"), "install": None, "remote": False,
         "note": "speech-dispatcher, usually preinstalled"},
        {"name": "piper", "os": "any", "os_provided": False, "available": bool(_which("piper")),
         "path": _which("piper"), "remote": False,
         "install": "optional; GPL-3.0 engine, never bundled by Body-MCP",
         "note": "natural neural voice, but it is GPL - install it yourself if you want it"},
        {"name": "kokoro", "os": "any", "os_provided": False, "available": False,
         "path": None, "remote": False,
         "install": "optional: pip install kokoro (downloads ~80-350 MB of voices)",
         "note": "only if the OS voice is not good enough"},
        {"name": "edge-tts", "os": "any", "os_provided": False, "available": False,
         "path": None, "remote": True,
         "install": "optional: pip install edge-tts",
         "note": "REMOTE: it sends the text to Microsoft - never enabled by default"},
    ]
    return engines


def sys_platform() -> str:
    import sys

    return sys.platform


def preferred_engine() -> tuple[str | None, dict]:
    """The best engine for this machine (OS-provided first)."""
    engines = detect_engines()
    order = (["windows-sapi", "macos-say", "linux-espeak", "linux-speech-dispatcher"]
              if os.name == "nt" else
              ["macos-say", "linux-espeak", "linux-speech-dispatcher", "windows-sapi"])
    by_name = {engine["name"]: engine for engine in engines}
    for name in order:
        engine = by_name.get(name)
        if engine and engine["available"]:
            return name, engine
    return None, {"available": False, "reason": "no speech engine is installed"}


def available(quick: bool = False) -> dict:
    """Is a speech engine usable right now?"""
    name, engine = preferred_engine()
    if not name:
        return {"available": False, "reason": "no speech engine is installed",
                "engines": detect_engines(),
                "install": "Windows: none needed (SAPI is built in); macOS: none needed "
                           "(say is built in); Linux: espeak-ng is usually preinstalled",
                "note": "Body-MCP never installs an engine the OS already provides"}
    info = {"available": True, "engine": name, "os_provided": engine.get("os_provided"),
            "path": engine.get("path"), "remote": engine.get("remote"),
            "note": engine.get("note"), "downloads": False}
    if not quick:
        info["voices"] = _voices(name)
    else:
        info["voices"] = None
    return info


def _voices(engine: str) -> list[str]:
    if engine == "windows-sapi":
        voices = []
        try:
            script = ("Add-Type -AssemblyName System.Speech; "
                      "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                      "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                                 capture_output=True, text=True, timeout=30)
            voices = [line.strip() for line in (out.stdout or "").splitlines() if line.strip()]
        except Exception:
            voices = []
        return voices
    return []


def _synthesize(engine: str, text: str, path: str, voice: str | None) -> str:
    """Render the text to a WAV file. Returns an error string (empty = ok)."""
    if engine == "windows-sapi":
        escaped = text.replace("'", "''")
        voice_line = f"$s.SelectVoice('{voice}'); " if voice else ""
        script = ("Add-Type -AssemblyName System.Speech; "
                  "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  f"{voice_line}"
                  f"$s.SetOutputToWaveFile('{path}'); "
                  f"$s.Speak('{escaped}'); "
                  "$s.SetOutputToNull();")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                 capture_output=True, text=True, timeout=300)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        if not os.path.exists(path):
            detail = (out.stderr or out.stdout or "").strip().splitlines()
            return detail[-1][:200] if detail else "SAPI produced no audio"
        return ""
    if engine == "macos-say":
        command = ["say", "-o", path]
        if voice:
            command += ["-v", voice]
        command.append(text)
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=300)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        return "" if out.returncode == 0 else (out.stderr or "").strip()[:200]
    if engine == "linux-espeak":
        binary = _which("espeak-ng", "espeak")
        command = [binary, "-w", path]
        if voice:
            command += ["-v", voice]
        command.append(text)
        try:
            out = subprocess.run(command, capture_output=True, text=True, timeout=300)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        return "" if out.returncode == 0 else (out.stderr or "").strip()[:200]
    return f"engine {engine!r} cannot synthesise to a file"


def _player_command(path: str) -> list[str] | None:
    """The OS player for a WAV file."""
    if os.name == "nt":
        return None  # winsound is used directly
    for candidate in ("aplay", "paplay", "afplay", "ffplay"):
        found = _which(candidate)
        if found:
            if candidate == "afplay":
                return [found, path]
            if candidate == "ffplay":
                return [found, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
            return [found, path]
    return None


def speak(text: str, voice: str | None = None) -> dict:
    """Speak text with the engine this machine already has."""
    text = (text or "").strip()
    if not text:
        return {"success": False, "message": "nothing to speak", "data": {}}
    if len(text) > MAX_CHARS:
        return {"success": False,
                "message": f"text too long for one utterance ({len(text)} > {MAX_CHARS} chars)",
                "data": {}}
    engine, info = preferred_engine()
    if not engine:
        return {"success": False, "message": "no speech engine is installed",
                "data": {"engines": detect_engines()}}

    fd, path = tempfile.mkstemp(prefix="body_tts_", suffix=".wav")
    os.close(fd)
    start = time.monotonic()
    error = _synthesize(engine, text, path, voice)
    synth_ms = int((time.monotonic() - start) * 1000)
    if error:
        with contextlib.suppress(OSError):
            os.remove(path)
        return {"success": False, "message": f"speech synthesis failed: {error}", "data": {}}

    player = _start_playback(path)
    with _lock:
        _state.update({"player": player, "path": path, "started_at": time.time(),
                       "engine": engine, "voice": voice})
    return {"success": True,
            "message": f"speaking with {engine} (the engine your system already has)",
            "data": {"engine": engine, "os_provided": info.get("os_provided"),
                     "voice": voice, "audio_bytes": os.path.getsize(path),
                     "synthesis_ms": synth_ms,
                     "time_to_playback_ms": int((time.monotonic() - start) * 1000),
                     "verification": "UNCONFIRMED",
                     "note": "the audio was produced and playback started; audible output is "
                             "confirmed by the listener, not by the machine"}}


def _start_playback(path: str):
    """Start playback; returns a handle that can stop it."""
    if os.name == "nt":
        def windows_play():
            try:
                import winsound

                winsound.PlaySound(path, winsound.SND_FILENAME)
            except Exception:
                pass
            finally:
                with contextlib.suppress(OSError):
                    os.remove(path)

        thread = threading.Thread(target=windows_play, daemon=True, name="body-tts")
        thread.start()
        return {"kind": "thread", "proc": thread}

    command = _player_command(path)
    if not command:
        with contextlib.suppress(OSError):
            os.remove(path)
        return None
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)

    def cleanup():
        proc.wait()
        with contextlib.suppress(OSError):
            os.remove(path)

    threading.Thread(target=cleanup, daemon=True, name="body-tts-cleanup").start()
    return {"kind": "process", "proc": proc}


def stop() -> dict:
    """Stop the playback and clean up."""
    with _lock:
        player = _state.get("player")
        path = _state.get("path")
        _state.update({"player": None, "path": None, "started_at": None})
    stopped = False
    if player:
        if player.get("kind") == "process":
            with contextlib.suppress(Exception):
                player["proc"].terminate()
            stopped = True
        else:
            stopped = True
            if os.name == "nt":
                with contextlib.suppress(Exception):
                    import winsound

                    winsound.PlaySound(None, winsound.SND_PURGE)
    if path:
        with contextlib.suppress(OSError):
            os.remove(path)
    return {"success": True,
            "message": "playback stopped" if stopped else "no playback was running",
            "data": {"stopped": stopped, "cleanup": True}}


def status() -> dict:
    with _lock:
        playing = _state.get("player") is not None
        started = _state.get("started_at")
        engine = _state.get("engine")
    info = available()
    return {"playing": playing, "started_at": started, "engine": engine,
            "available": info.get("available"), "engines": detect_engines()}


def installed_engines() -> list[dict]:
    """The engines already present (so nobody installs what the OS provides)."""
    return [engine for engine in detect_engines() if engine["available"]]
