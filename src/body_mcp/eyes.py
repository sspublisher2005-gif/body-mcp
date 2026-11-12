"""Desktop observation: screen capture + OCR through the provider registry.

Capture is separated from OCR so a live session can decide *whether* the screen changed
before spending CPU on recognition. Screenshots live in memory only - nothing is written
to disk unless the user asks for it.

Capture adapters:
  - MSS (default, cross-platform): monitors and regions,
  - a documented refusal when the OS denies capture (headless session, missing permission).

Windows display scaling is handled by MSS (it reports physical pixels); macOS needs Screen
Recording permission, Linux needs an X/Wayland display - both surface as a truthful error.
"""
from __future__ import annotations

import hashlib
import os

from . import safety
from .ocr import get_provider, providers

MAX_REGION_PIXELS = 20_000_000


def _mss_session():
    """mss session (the newer mss.MSS API, with a fallback for older releases)."""
    import mss

    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def monitors() -> list[dict]:
    """The connected screens (index, size, primary flag)."""
    try:
        import mss  # noqa: F401
    except Exception as exc:
        return {"error": f"mss is not installed: {exc}"}
    try:
        with _mss_session() as sct:
            out = [{"index": i, "left": m["left"], "top": m["top"],
                    "width": m["width"], "height": m["height"],
                    "primary": i == 1}
                   for i, m in enumerate(sct.monitors)]
    except Exception as exc:
        return {"error": f"screen enumeration failed: {type(exc).__name__}: {exc}"}
    return {"monitors": out}


def capture_png(monitor: int = 1, region: tuple[int, int, int, int] | None = None) -> dict:
    """Capture a screen or region as PNG bytes (in memory only).

    region = (left, top, width, height) in physical pixels.
    """
    try:
        import mss
        import mss.tools
    except Exception as exc:
        return {"ok": False, "reason": f"mss is not installed: {exc}"}
    try:
        with _mss_session() as sct:
            targets = sct.monitors
            if monitor < 0 or monitor >= len(targets):
                return {"ok": False,
                        "reason": f"monitor {monitor} does not exist "
                                  f"({len(targets) - 1} is the highest index)"}
            box = targets[monitor]
            if region is not None:
                left, top, width, height = region
                if width <= 0 or height <= 0:
                    return {"ok": False, "reason": "region must have a positive width and height"}
                if width * height > MAX_REGION_PIXELS:
                    return {"ok": False,
                            "reason": f"region too large ({width * height} pixels)"}
                box = {"left": left, "top": top, "width": width, "height": height}
            shot = sct.grab(box)
            png = mss.tools.to_png(shot.rgb, shot.size)
    except Exception as exc:
        return {"ok": False,
                "reason": f"screen capture failed: {type(exc).__name__}: {exc}. "
                          "Body-MCP needs an interactive desktop session with screen-capture "
                          "permission (macOS: Screen Recording; Linux: a real display)."}
    return {"ok": True, "png": png, "bytes": len(png),
            "region": {"left": box["left"], "top": box["top"],
                       "width": box["width"], "height": box["height"]}}


def frame_hash(png: bytes) -> str:
    """Cheap perceptual-ish fingerprint of a frame (SHA-256 of the raw bytes)."""
    return hashlib.sha256(png).hexdigest()[:32]


def ocr_status() -> dict:
    """Which OCR engines are usable right now, and why."""
    return {"providers": providers(),
            "selected": get_provider()[0].name if get_provider()[0] else None}


def see_desktop(monitor: int = 1, language: str = "eng",
                region: tuple[int, int, int, int] | None = None,
                provider_name: str | None = None, as_image: bool = False) -> dict:
    """Capture one screen/region and OCR it (and optionally attach the image).

    The image does NOT depend on OCR: with as_image=True the screenshot is
    attached even when no OCR engine is installed (a vision model can still look
    at it). Only the text needs OCR.
    """
    shot = capture_png(monitor=monitor, region=region)
    if not shot.get("ok"):
        return {"success": False, "message": shot["reason"], "data": {}}
    provider, info = get_provider(provider_name)
    if provider is None and not as_image:
        return {"success": False,
                "message": f"no OCR engine available: {info.get('reason')}",
                "data": {"capture_ok": True, "install": info.get("install"),
                         "providers": info.get("checked"),
                         "note": "the screenshot was captured in memory and discarded"}}
    if provider is None:
        scan = {"sensitive": False, "restricted": False}
        payload = {"success": True,
                   "message": ("desktop captured; NO OCR ENGINE so there is no text - the "
                               "image is attached for a vision model"),
                   "data": {"text": "", "provider": None, "language": language,
                            "confidence": None, "ocr_ms": 0,
                            "capture": shot["region"], "screenshot_bytes": shot["bytes"],
                            "safety": scan, "sensitive_mode": False, "restricted": False,
                            "warnings": [f"no OCR engine: {info.get('reason')}"],
                            "install": info.get("install"),
                            "note": "the screenshot was processed in memory and never "
                                    "written to disk"}}
    else:
        result = provider.recognize(shot["png"], language=language)
        scan = safety.scan_text(result.text)
        payload = {"success": True,
                "message": f"desktop captured and OCR'd with {result.provider}",
                "data": {"text": result.text,
                         "provider": result.provider,
                         "language": result.language,
                         "confidence": result.confidence,
                         "ocr_ms": result.duration_ms,
                         "capture": shot["region"],
                         "screenshot_bytes": shot["bytes"],
                         "safety": scan,
                         "sensitive_mode": scan["sensitive"],
                         "restricted": scan["restricted"],
                         "warnings": result.warnings,
                         "note": "the screenshot was processed in memory and never written to disk"}}
    if as_image:
        from . import vision

        return vision.with_image(payload, vision.prepare_image(shot["png"]))
    return payload


def ocr_text(png_bytes: bytes, language: str = "eng", provider_name: str | None = None) -> dict:
    """OCR an in-memory PNG (used by the live watcher)."""
    provider, info = get_provider(provider_name)
    if provider is None:
        return {"ok": False, "reason": info.get("reason"), "text": "", "provider": None}
    result = provider.recognize(png_bytes, language=language)
    return {"ok": not result.warnings, "text": result.text, "provider": result.provider,
            "confidence": result.confidence, "duration_ms": result.duration_ms,
            "lines": result.lines, "warnings": result.warnings}


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")
