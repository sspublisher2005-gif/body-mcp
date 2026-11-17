# Releases

Body-MCP is MIT licensed, free, local-first and has **no paid tier, no telemetry and no
cloud account**. A release is a zip with the source tree, the entry points and (optionally)
a bundled OCR engine.

```powershell
python scripts\build_release.py            # build for this machine
python scripts\build_release.py --list     # the release matrix
python scripts\build_release.py --platform windows-x64
```

## What a build produces

| File | Content |
|---|---|
| `dist/body-mcp-<version>-<platform>.zip` | the source tree (src, docs, examples, scripts, tests), `pyproject.toml`, `README.md`, `AGENTS.md`, `LICENSE`, `THIRD_PARTY_NOTICES.md` and, if present, the bundled OCR engine |
| `dist/body-mcp-<version>-<platform>.zip.sha256` | the checksum (verify with `Get-FileHash`) |
| `dist/body-mcp-<version>-<platform>.json` | the manifest: file list with sizes and SHA-256, the OCR engine state, the install steps, the licence |

Install from a release:

```powershell
Expand-Archive body-mcp-0.4.0-windows-x64.zip
cd body-mcp-0.4.0-windows-x64
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m playwright install chromium
python -m body_mcp.doctor          # verifies the installation
```

## The bundled OCR engine

The engine is **optional and never downloaded automatically**. A release may carry
`vendor/tesseract/<platform>/` (Apache-2.0) with the `eng` language data; the build
records whether it was bundled:

```json
"ocr_bundled": false,
"ocr_engines": {"tesseract": {"available": false, "reason": "..."},
                 "rapidocr": {"available": false, "reason": "..."}}
```

Other languages are installed by the user (or a language pack they explicitly select),
never silently. See `docs/ocr.md` and `THIRD_PARTY_NOTICES.md` for the licences.

## Release matrix - what was **actually** built and tested

| Platform | Build | Integration tested | Notes |
|---|---|---|---|
| **windows-x64** | yes (this machine) | **yes** - 154 unit/integration tests pass, MCP stdio handshake verified, real Chrome CDP attach verified, desktop capture verified | OCR **blocked** (no Tesseract on this machine) |
| macos-arm64 | configuration prepared | **no** | must be built and tested on an Apple Silicon machine |
| macos-x64 | configuration prepared | **no** | same |
| linux-x64 | configuration prepared | **no** | must be built on a real desktop session |

**No release is advertised as downloadable-and-working for a platform whose integration
tests were not run.** The Windows artifact was built and exercised here; the other three
are prepared configurations only.

## Verified artifact (Windows x64, this machine)

| Item | Value |
|---|---|
| artifact | `dist/body-mcp-0.4.0-windows-x64.zip` |
| size | 204 KB |
| sha256 | `9f0bd45b0320ba92d66e9a3b323ca32822e530386fff837afbe1acc5d11ec923` |

Reproduce with `python scripts\build_release.py` - the sha256 changes when the source
changes, which is the point of shipping it next to the artifact.

## Licensing decisions that shaped the release

- **Piper is GPL-3.0-or-later** and some of its voices are non-commercial: it is
  **never bundled**. Users who want it install it themselves under its own licence.
- **Kokoro, whisper.cpp, sherpa-onnx and RapidOCR are Apache-2.0/MIT**: they may be
  bundled, but Body-MCP does not bundle them by default either - it points at them.
- **Tesseract + tessdata (Apache-2.0)** may be bundled with the licence and NOTICE files
  next to the binary.
- `edge-tts` talks to a remote service and is **never** enabled by default.
