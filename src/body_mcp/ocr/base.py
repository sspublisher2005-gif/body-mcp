"""OCR provider interface.

An OCR provider turns a PNG screenshot into text. Body-MCP ships with:

  - `tesseract`  — the default: a small, offline, Apache-2.0 engine,
  - `rapidocr`   — optional, only used if it is installed and measures better.

Providers are discovered, never assumed. A missing engine is reported as
unavailable with the exact reason and the install command — the server still starts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class OcrResult:
    """One OCR outcome. `text` may be empty - that is a real result, not a failure."""

    text: str
    provider: str
    language: str = "eng"
    confidence: float | None = None
    duration_ms: int = 0
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"text": self.text, "provider": self.provider, "language": self.language,
                "confidence": self.confidence, "duration_ms": self.duration_ms,
                "lines": self.lines, "warnings": self.warnings}


class OcrProvider:
    """Base class: `name`, `available()`, `recognize(png_bytes, language)`."""

    name = "base"
    label = "base provider"

    def available(self) -> dict:
        return {"provider": self.name, "available": False,
                "reason": "not implemented", "path": None, "languages": []}

    def recognize(self, png_bytes: bytes, language: str = "eng") -> OcrResult:
        raise NotImplementedError

    # -- shared helpers -------------------------------------------------
    @staticmethod
    def _bundled_root() -> str:
        """Where a packaged release keeps its bundled engines."""
        here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(here, "vendor")

    def _platform_tag(self) -> str:
        import platform

        machine = (platform.machine() or "").lower()
        if machine in ("amd64", "x86_64"):
            arch = "x64"
        elif machine in ("arm64", "aarch64"):
            arch = "arm64"
        else:
            arch = machine or "x64"
        system = platform.system().lower()
        if system == "windows":
            return f"windows-{arch}"
        if system == "darwin":
            return f"macos-{arch}"
        return f"linux-{arch}"
