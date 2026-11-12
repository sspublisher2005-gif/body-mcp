"""OCR provider registry.

`get_provider()` returns the best available provider; `providers()` reports the
truth about every engine on this machine (available, path, languages, reason).
"""
from __future__ import annotations

from .base import OcrProvider, OcrResult
from .rapidocr import RapidOcrProvider
from .tesseract import TesseractProvider

PROVIDERS: dict[str, OcrProvider] = {
    "tesseract": TesseractProvider(),
    "rapidocr": RapidOcrProvider(),
}
DEFAULT_ORDER = ("tesseract", "rapidocr")


def providers() -> list[dict]:
    """Availability of every known provider (no side effects)."""
    return [provider.available() for provider in PROVIDERS.values()]


def available_providers() -> list[str]:
    return [name for name in DEFAULT_ORDER
            if PROVIDERS[name].available().get("available")]


def get_provider(name: str | None = None) -> tuple[OcrProvider | None, dict]:
    """Return (provider, info). `info` explains the choice or the refusal."""
    if name:
        provider = PROVIDERS.get(name)
        if provider is None:
            return None, {"available": False,
                          "reason": f"unknown OCR provider {name!r}",
                          "known": list(PROVIDERS)}
        info = provider.available()
        if not info.get("available"):
            return None, info
        return provider, info
    for candidate in DEFAULT_ORDER:
        provider = PROVIDERS[candidate]
        info = provider.available()
        if info.get("available"):
            return provider, info
    return None, {"available": False,
                  "reason": "no OCR engine is installed",
                  "install": ("winget install -e --id UB-Mannheim.TesseractOCR"
                              if __name__ != "__main__" else ""),
                  "checked": providers()}


__all__ = ["OcrProvider", "OcrResult", "PROVIDERS", "providers", "available_providers",
           "get_provider"]
