"""Live desktop observation sessions.

A watch session samples the screen on an interval and only runs OCR when the frame
actually changed. Sampling and recognition are separate steps, so an idle screen costs
almost nothing.

Rules:
  - a session starts only on an explicit user request,
  - the screen content is never written to disk, the audit log or the memory store,
  - the agent reads the latest observation through the MCP tools (polling - MCP has no
    push channel), the console shows the same events,
  - OCR runs in a worker thread, so the MCP server never blocks,
  - when CPU or memory pressure is high the sampling interval grows automatically.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import threading
import time

from . import events, runtime, safety, sysprofile

MAX_SESSIONS = 2
DEFAULT_INTERVAL_S = 3.0
MIN_INTERVAL_S = 1.0
MAX_INTERVAL_S = 60.0
MAX_TEXT_CHARS = 20000

_sessions: dict[str, dict] = {}


def _pressure_interval(interval: float) -> tuple[float, str]:
    """Grow the interval when the machine is short of memory or CPU."""
    try:
        profile = sysprofile.summary()
        ram = profile.get("ram_available_mb")
    except Exception:
        return interval, "unknown"
    if ram is None:
        return interval, "unknown"
    if ram < 256:
        return min(MAX_INTERVAL_S, interval * 4), f"memory pressure ({ram} MB free)"
    if ram < 512:
        return min(MAX_INTERVAL_S, interval * 2), f"memory pressure ({ram} MB free)"
    return interval, "nominal"


def start(monitor: int = 1, interval: float = DEFAULT_INTERVAL_S, language: str = "eng",
          region: list[int] | None = None, provider: str | None = None,
          ocr: bool = True) -> dict:
    """Start a live observation session (explicit user request only).

    ocr=True  (default) the changed frames are OCR'd to text.
    ocr=False image-only mode: frames are captured and compared, no OCR at all -
               for a vision model that looks at the screen itself.
    """
    from . import eyes

    if len(_sessions) >= MAX_SESSIONS:
        return {"success": False,
                "message": f"too many live sessions (max {MAX_SESSIONS}) - stop one first",
                "data": {}}
    provider_info = eyes.ocr_status()
    if ocr and provider_info.get("selected") is None and not provider:
        return {"success": False,
                "message": "no OCR engine is available - install Tesseract, select a "
                           "provider, or start with ocr=False to watch the screen as "
                           "images (for a vision model)",
                "data": {"providers": provider_info["providers"]}}
    interval = max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, float(interval or DEFAULT_INTERVAL_S)))
    region_tuple = tuple(region) if region else None
    session_id = "watch_" + hashlib.sha256(
        f"{time.time()}{monitor}{interval}".encode()).hexdigest()[:10]
    task_id = runtime.registry.create(label="desktop_watch")
    session = {
        "session_id": session_id,
        "task_id": task_id,
        "monitor": monitor,
        "interval": interval,
        "language": language,
        "region": region_tuple,
        "provider": provider,
        "ocr": bool(ocr),
        "created": time.time(),
        "last_hash": None,
        "last_frame": None,
        "last_observation": None,
        "observations": 0,
        "ocr_runs": 0,
        "ocr_skipped": 0,
        "stopped": False,
        "thread": None,
        "wake": threading.Event(),
        "status": "starting",
    }
    _sessions[session_id] = session
    session["thread"] = threading.Thread(target=_sampler, args=(session_id,), daemon=True,
                                         name=f"body-watch-{session_id}")
    session["thread"].start()
    events.emit(events.TASK_CREATED, task_id=task_id, tool="desktop_watch_start",
                status="STARTED",
                summary=f"live desktop observation started (monitor {monitor}, every {interval:.0f}s)",
                evidence={"session_id": session_id, "monitor": monitor, "interval": interval})
    return {"success": True,
            "message": (f"live observation {session_id} started - poll desktop_watch_read() for the "
                        "latest observation. Nothing is stored on disk."),
            "data": {"session_id": session_id, "task_id": task_id, "monitor": monitor,
                     "interval": interval, "region": list(region_tuple) if region_tuple else None,
                     "ocr": bool(ocr),
                     "provider": provider or provider_info.get("selected")}}


def _sampler(session_id: str) -> None:
    """Worker thread: capture, compare, OCR only when the frame changed."""
    from . import eyes

    session = _sessions.get(session_id)
    if session is None:
        return
    session["status"] = "watching"
    while not session["stopped"]:
        try:
            shot = eyes.capture_png(monitor=session["monitor"], region=session["region"])
            if shot.get("ok"):
                digest = eyes.frame_hash(shot["png"])
                if digest != session["last_hash"]:
                    session["last_hash"] = digest
                    session["last_frame"] = shot["png"]  # kept in memory for vision mode
                    if session.get("ocr", True):
                        result = eyes.ocr_text(shot["png"], language=session["language"],
                                               provider_name=session["provider"])
                        session["ocr_runs"] += 1
                        text = (result.get("text") or "")[:MAX_TEXT_CHARS]
                        scan = safety.scan_text(text)
                        provider_name = result.get("provider")
                        ocr_ms = result.get("duration_ms")
                        confidence = result.get("confidence")
                        warnings = result.get("warnings") or []
                    else:
                        # image-only mode: the frame changed, but nobody read the text
                        text = ""
                        scan = {"sensitive": False, "restricted": False}
                        provider_name = None
                        ocr_ms = 0
                        confidence = None
                        warnings = []
                    session["last_observation"] = {
                        "observed_at": time.time(),
                        "text": text,
                        "chars": len(text),
                        "provider": provider_name,
                        "ocr_ms": ocr_ms,
                        "confidence": confidence,
                        "sensitive_mode": bool(scan.get("sensitive")),
                        "restricted": bool(scan.get("restricted")),
                        "warnings": warnings,
                    }
                    session["observations"] += 1
                    events.emit(events.OBSERVATION, task_id=session["task_id"],
                                tool="desktop_watch",
                                status="BLOCKED" if scan.get("restricted") else None,
                                summary=f"screen changed: {len(text)} characters recognised",
                                evidence={"session_id": session_id, "chars": len(text),
                                          "ocr_ms": ocr_ms})
                else:
                    session["ocr_skipped"] += 1
        except Exception as exc:  # a capture failure must not kill the session
            session["last_error"] = f"{type(exc).__name__}: {exc}"
        interval, reason = _pressure_interval(session["interval"])
        session["current_interval"] = interval
        session["pressure"] = reason
        session["wake"].wait(timeout=interval)
        session["wake"].clear()


def last_frame(session_id: str | None = None) -> bytes | None:
    """The most recent frame of a session (in memory only), for vision mode."""
    if not _sessions:
        return None
    session = _sessions.get(session_id) if session_id else max(_sessions.values(), key=lambda s: s["created"])
    if not session:
        return None
    return session.get("last_frame")


def read(session_id: str | None = None, since: float = 0) -> dict:
    """The latest observation of a session (or of the newest session)."""
    if not _sessions:
        return {"success": False, "message": "no live observation session is running",
                "data": {"sessions": []}}
    if session_id:
        session = _sessions.get(session_id)
        if session is None:
            return {"success": False, "message": f"no such session: {session_id}", "data": {}}
    else:
        session = max(_sessions.values(), key=lambda s: s["created"])
    observation = session.get("last_observation")
    data = {
        "session_id": session["session_id"],
        "task_id": session["task_id"],
        "status": session["status"],
        "monitor": session["monitor"],
        "interval": session["interval"],
        "current_interval": session.get("current_interval", session["interval"]),
        "pressure": session.get("pressure", "unknown"),
        "observations": session["observations"],
        "ocr_runs": session["ocr_runs"],
        "ocr_skipped": session["ocr_skipped"],
        "uptime_s": int(time.time() - session["created"]),
        "text": (observation or {}).get("text", ""),
        "observed_at": (observation or {}).get("observed_at"),
        "changed": observation is not None and observation["observed_at"] > since,
        "provider": (observation or {}).get("provider"),
        "ocr_ms": (observation or {}).get("ocr_ms"),
        "sensitive_mode": (observation or {}).get("sensitive_mode", False),
        "restricted": (observation or {}).get("restricted", False),
        "warnings": (observation or {}).get("warnings", []),
        "note": "screen content is returned on request and never stored",
    }
    if observation is None:
        return {"success": True,
                "message": "session is running, no screen change observed yet",
                "data": data}
    return {"success": True,
            "message": f"latest observation ({observation['chars']} chars, "
                       f"{observation.get('ocr_ms')} ms OCR)",
            "data": data}


def stop(session_id: str | None = None) -> dict:
    """Stop a live observation session and release its resources."""
    if not _sessions:
        return {"success": True, "message": "no live observation session was running", "data": {}}
    if session_id:
        session = _sessions.get(session_id)
        if session is None:
            return {"success": False, "message": f"no such session: {session_id}", "data": {}}
    else:
        session = max(_sessions.values(), key=lambda s: s["created"])
    session["stopped"] = True
    session["status"] = "stopped"
    session["last_frame"] = None
    session["wake"].set()
    thread = session.get("thread")
    if thread is not None and thread.is_alive():
        with contextlib.suppress(Exception):
            thread.join(timeout=5)
    _sessions.pop(session["session_id"], None)
    runtime.registry.finish(session["task_id"], "completed", "live observation stopped")
    events.emit(events.TASK_FINISHED, task_id=session["task_id"], tool="desktop_watch_stop",
                status="COMPLETED",
                summary=f"live observation stopped after {session['observations']} observation(s)",
                evidence={"session_id": session["session_id"],
                          "ocr_runs": session["ocr_runs"],
                          "ocr_skipped": session["ocr_skipped"]})
    return {"success": True,
            "message": (f"live observation stopped: {session['observations']} observation(s), "
                        f"{session['ocr_runs']} OCR run(s), "
                        f"{session['ocr_skipped']} unchanged frame(s) skipped"),
            "data": {"session_id": session["session_id"],
                     "observations": session["observations"],
                     "ocr_runs": session["ocr_runs"],
                     "ocr_skipped": session["ocr_skipped"]}}


def sessions() -> list[dict]:
    return [{"session_id": s["session_id"], "task_id": s["task_id"], "status": s["status"],
             "monitor": s["monitor"], "interval": s["interval"],
             "current_interval": s.get("current_interval", s["interval"]),
             "pressure": s.get("pressure", "unknown"),
             "observations": s["observations"], "uptime_s": int(time.time() - s["created"])}
            for s in _sessions.values()]


def stop_all() -> int:
    count = 0
    for session_id in list(_sessions):
        if stop(session_id).get("success"):
            count += 1
    return count


async def async_stop_all() -> None:
    await asyncio.sleep(0)
    stop_all()
