"""RapidOCR provider (optional alternative).

Not enabled by default: it is only used when it is actually installed AND the user
selects it. Kept behind the same provider interface so it can be compared against
Tesseract on real screens (see docs/ocr.md).
"""
from __future__ import annotations

import time

from .base import OcrProvider, OcrResult


class RapidOcrProvider(OcrProvider):
    name = "rapidocr"
    label = "RapidOCR (ONNX runtime, Apache-2.0)"

    def _engine(self):
        try:
            from rapidocr_onnxruntime import RapidOCR
        except Exception:
            return None
        try:
            return RapidOCR()
        except Exception:
            return None

    def available(self) -> dict:
        try:
            import importlib.util

            if importlib.util.find_spec("rapidocr_onnxruntime") is None:
                return {"provider": self.name, "available": False, "path": None, "languages": [],
                        "reason": "rapidocr_onnxruntime is not installed",
                        "install": "pip install -e '.[ocr-rapid]'"}
        except Exception:
            return {"provider": self.name, "available": False, "path": None, "languages": [],
                    "reason": "rapidocr_onnxruntime is not installed",
                    "install": "pip install -e '.[ocr-rapid]'"}
        engine = self._engine()
        if engine is None:
            return {"provider": self.name, "available": False, "path": None, "languages": [],
                    "reason": "the RapidOCR engine could not be created",
                    "install": "pip install -e '.[ocr-rapid]'"}
        return {"provider": self.name, "available": True, "path": "rapidocr_onnxruntime",
                "languages": ["eng", "ch", "japan", "korean"], "reason": None,
                "note": "models are bundled with the package; the first run downloads nothing"}

    def recognize(self, png_bytes: bytes, language: str = "eng") -> OcrResult:
        engine = self._engine()
        if engine is None:
            return OcrResult(text="", provider=self.name, language=language,
                             warnings=["RapidOCR is not installed"])
        start = time.monotonic()
        try:
            import io

            import numpy as np
            from PIL import Image

            image = np.array(Image.open(io.BytesIO(png_bytes)).convert("RGB"))
            result, _ = engine(image)
        except Exception as exc:
            return OcrResult(text="", provider=self.name, language=language,
                             warnings=[f"{type(exc).__name__}: {exc}"])
        duration = int((time.monotonic() - start) * 1000)
        lines: list[str] = []
        confidences: list[float] = []
        for item in result or []:
            try:
                lines.append(str(item[1]))
                confidences.append(float(item[2]))
            except Exception:
                continue
        mean_confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
        return OcrResult(text="\n".join(lines), provider=self.name, language=language,
                         confidence=mean_confidence, duration_ms=duration, lines=lines)
