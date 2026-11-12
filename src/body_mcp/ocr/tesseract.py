"""Tesseract OCR provider (default engine).

Discovery order (first hit wins):
  1. `BODY_MCP_TESSERACT_CMD` / `TESSERACT_CMD` (explicit path or command)
  2. a bundled engine in a packaged release: `vendor/tesseract/<platform>/tesseract[.exe]`
  3. `tesseract` on PATH
  4. the standard install locations of the platform

Language data is looked up next to the binary (`tessdata/`), in `TESSDATA_PREFIX`, and in
the platform's system locations. `tessdata_fast` is preferred when both are present because
it is the small/fast model set.

The engine is called directly (no pytesseract dependency) so a packaged release needs
nothing but the binary and its language data.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
import time

from .base import OcrProvider, OcrResult

TIMEOUT_SECONDS = 60


class TesseractProvider(OcrProvider):
    name = "tesseract"
    label = "Tesseract (offline, Apache-2.0)"

    def _candidates(self) -> list[str]:
        found: list[str] = []
        for env_name in ("BODY_MCP_TESSERACT_CMD", "TESSERACT_CMD"):
            value = os.environ.get(env_name)
            if value and os.path.isfile(value):
                found.append(value)
        bundled = os.path.join(self._bundled_root(), "tesseract", self._platform_tag(),
                               "tesseract.exe" if os.name == "nt" else "tesseract")
        if os.path.isfile(bundled):
            found.append(bundled)
        on_path = shutil.which("tesseract")
        if on_path:
            found.append(on_path)
        if os.name == "nt":
            program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
            program_files_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
            local = os.environ.get("LOCALAPPDATA", "")
            for root in (program_files, program_files_x86):
                found.append(os.path.join(root, "Tesseract-OCR", "tesseract.exe"))
            if local:
                found.append(os.path.join(local, "Programs", "Tesseract-OCR", "tesseract.exe"))
        else:
            for path in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract",
                         "/usr/bin/tesseract", "/opt/local/bin/tesseract"):
                if os.path.isfile(path):
                    found.append(path)
        return found

    def _tessdata_dirs(self, binary: str | None) -> list[str]:
        dirs: list[str] = []
        prefix = os.environ.get("TESSDATA_PREFIX")
        if prefix:
            dirs.append(prefix)
        if binary:
            base = os.path.dirname(binary)
            dirs.append(os.path.join(base, "tessdata"))
            dirs.append(os.path.join(base, "..", "tessdata"))
        if os.name == "nt":
            program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
            dirs.append(os.path.join(program_files, "Tesseract-OCR", "tessdata"))
        else:
            dirs.append("/usr/share/tesseract-ocr/5/tessdata")
            dirs.append("/usr/share/tesseract-ocr/4.00/tessdata")
            dirs.append("/usr/local/share/tessdata")
        return [d for d in dirs if os.path.isdir(d)]

    def _languages(self, binary: str | None) -> list[str]:
        found: set[str] = set()
        for directory in self._tessdata_dirs(binary):
            try:
                for name in os.listdir(directory):
                    if name.endswith(".traineddata"):
                        found.add(name.replace(".traineddata", ""))
            except OSError:
                continue
        return sorted(found)

    def binary(self) -> str | None:
        for candidate in self._candidates():
            if os.path.isfile(candidate):
                return candidate
        return None

    def available(self) -> dict:
        binary = self.binary()
        if not binary:
            return {"provider": self.name, "available": False, "path": None, "languages": [],
                    "reason": "the Tesseract OCR binary was not found",
                    "install": ("winget install -e --id UB-Mannheim.TesseractOCR"
                                if os.name == "nt" else
                                "brew install tesseract (macOS) / apt install tesseract-ocr (Linux)"),
                    "or": "install the bundled engine from a packaged release, or set "
                          "BODY_MCP_TESSERACT_CMD to the executable"}
        languages = self._languages(binary)
        version = ""
        try:
            out = subprocess.run([binary, "--version"], capture_output=True, text=True,
                                 timeout=15)
            version = (out.stdout or "").strip().splitlines()[0][:120] if out.stdout else ""
        except Exception:
            version = ""
        return {"provider": self.name, "available": True, "path": binary,
                "languages": languages, "version": version,
                "tessdata_dirs": self._tessdata_dirs(binary),
                "reason": None,
                "note": None if languages else
                        "the engine is installed but no language data (*.traineddata) was found - "
                        "OCR will fail until at least 'eng' data is present"}

    def recognize(self, png_bytes: bytes, language: str = "eng") -> OcrResult:
        binary = self.binary()
        if not binary:
            return OcrResult(text="", provider=self.name, language=language,
                             warnings=["the Tesseract OCR binary was not found"])
        start = time.monotonic()
        fd, path = tempfile.mkstemp(prefix="body_ocr_", suffix=".png")
        os.close(fd)
        try:
            with open(path, "wb") as f:
                f.write(png_bytes)
            out = subprocess.run([binary, path, "stdout", "-l", language],
                                 capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return OcrResult(text="", provider=self.name, language=language,
                             warnings=[f"OCR timed out after {TIMEOUT_SECONDS}s"])
        except Exception as exc:
            return OcrResult(text="", provider=self.name, language=language,
                             warnings=[f"{type(exc).__name__}: {exc}"])
        finally:
            with contextlib.suppress(OSError):
                os.remove(path)
        duration = int((time.monotonic() - start) * 1000)
        if out.returncode != 0:
            return OcrResult(text="", provider=self.name, language=language,
                             duration_ms=duration,
                             warnings=[(f"tesseract exited with {out.returncode}: "
                                      f"{(out.stderr or '').strip()[:200]}")])
        text = (out.stdout or "").strip()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return OcrResult(text=text, provider=self.name, language=language,
                         duration_ms=duration, lines=lines)
