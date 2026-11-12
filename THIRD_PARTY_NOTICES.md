# Third-party notices

Body-MCP itself is MIT licensed (see `LICENSE`). It depends on, and can bundle, the
components below. Every entry states the licence and what actually happens in a release.

## Bundled by a packaged release

| Component | Licence | What is bundled | Redistribution notes |
|---|---|---|---|
| **Tesseract OCR** (engine binary) | Apache-2.0 | `vendor/tesseract/<platform>/` in a packaged release | Apache-2.0 permits redistribution of the binary with the licence text and the NOTICE file. Keep both next to the binary. |
| **tessdata_fast / tessdata** language data | Apache-2.0 | `vendor/tesseract/<platform>/tessdata/*.traineddata` | The `eng` model is required for the default OCR. Additional languages are **downloaded on explicit user request only** and validated by checksum. |
| **Tesseract-OCR Windows installer contents** (UB-Mannheim build) | Apache-2.0 (build scripts MIT) | used only when the user installs the engine themselves | If a release bundles the UB-Mannheim build, its own licence files must be shipped alongside. |

## Installed as Python dependencies (optional extras)

| Component | Licence | Why it is optional |
|---|---|---|
| `mcp` (Model Context Protocol SDK) | MIT | core dependency |
| `playwright` | Apache-2.0 | core dependency (browser control) |
| `mss` | MIT | `[desktop]` - screen capture |
| `pytesseract` | Apache-2.0 | `[desktop]` - OCR wrapper |
| `Pillow` | MIT-CMU | `[desktop]` - image handling |
| `sounddevice` | MIT | `[voice]` - microphone capture |
| `faster-whisper` | MIT (weights: MIT / Apache-2.0 per model) | `[voice]` - local speech-to-text |
| `numpy` | BSD-3 | `[voice]` |
| `rapidocr_onnxruntime` | Apache-2.0 | `[ocr-rapid]` - optional OCR engine |
| `pytest`, `ruff` | MIT | `[dev]` |

## Optional engines a user may install themselves

These are **never bundled** by Body-MCP. The user installs them if they want them; the
project only documents how.

| Component | Licence | Why it is not bundled |
|---|---|---|
| **Piper** (text-to-speech) | **GPL-3.0-or-later** for the engine | Bundling a GPL engine inside an MIT project would impose GPL terms on the combined work. Individual Piper voices carry their own licences - some are non-commercial only - so voices are never redistributed here. Use Windows SAPI (built in) instead, or install Piper yourself under its own licence. |
| **Kokoro** (neural TTS) | Apache-2.0 (code), model weights Apache-2.0 | Optional, larger download (~80–350 MB of voices). Not bundled; install it yourself. |
| **whisper.cpp** | MIT | Optional ASR engine with good multilingual coverage; install it yourself, or use `faster-whisper` from the `[voice]` extra. |
| **sherpa-onnx** | Apache-2.0 | Optional streaming ASR; install it yourself. |
| **edge-tts** | LGPL-3.0 (client) | It sends text to Microsoft's service - remote, not local. Never enabled by default; use only with explicit consent. |

## Data and privacy

Body-MCP itself sends nothing anywhere. The optional engines above are local except
`edge-tts`, which is remote by design and must be opted into explicitly.

## Attribution

* Tesseract OCR — https://github.com/tesseract-ocr/tesseract (Apache-2.0)
* Language data — https://github.com/tesseract-ocr/tessdata (Apache-2.0)
* RapidOCR — https://github.com/RapidAI/RapidOCR (Apache-2.0)
* faster-whisper — https://github.com/SYSTRAN/faster-whisper (MIT)
* whisper.cpp — https://github.com/ggml-org/whisper.cpp (MIT)
* sherpa-onnx — https://github.com/k2-fsa/sherpa-onnx (Apache-2.0)
* Piper — https://github.com/OHF-Voice/piper1-gpl (GPL-3.0-or-later; not bundled)
* Kokoro — https://github.com/thewh1teagle/kokoro-onnx (Apache-2.0; not bundled)
