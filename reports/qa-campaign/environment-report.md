# Environment report — Body-MCP QA campaign

**Collected:** 2026-11-10 on the campaign machine, read-only (no settings changed, no
software installed, no model downloaded).

## 1. Runtime

| Item | Value |
|---|---|
| OS | Windows 11 (10.0.26300-SP0), AMD64 |
| Python | 3.14.7 — `C:\Users\shash\AppData\Local\Programs\Python\Python314\python.exe` (global, **not** a venv) |
| CPU | 4 logical cores |
| RAM | 3.8 GB total, 462–529 MB free during the campaign (the user's own Chrome plus two MCP servers were running) |
| GPU | not detectable (no `nvidia-smi`, no GPU libraries) — reported as `unknown`, never as "usable" |
| Disk | free space probed for the user profile and the model cache |
| Second environment | `D:\Projects\body parts of agents\.venv` (the `body-dev` MCP server copy), used for the synced re-test |

## 2. Installed dependencies

| Package | Status | Notes |
|---|---|---|
| `mcp` | present, **2.3.0** | `MCPServer` v2 API (`mcp.server.mcpserver`) |
| `playwright` | present | Chromium binary at `…\ms-playwright\chromium-1254\chrome-win64\chrome.exe` |
| `mss`, `pytesseract`, `Pillow` | present | desktop capture/OCR; now **optional extras** in `pyproject.toml` |
| `sounddevice`, `faster_whisper`, `numpy` | present | voice; optional extras. The Whisper **model weights are not downloaded** |
| `pytest`, `ruff` | present | dev extras |
| `pynput` | **removed** | declared as a dependency but never imported anywhere |

## 3. External executables

| Executable | Status | Notes |
|---|---|---|
| Chrome 157.0.8103.40 | present at `C:\Program Files\Google\Chrome\Application\chrome.exe` | used for the real CDP attach test (headless **and** headed) |
| Edge 157.0.4341.42 | present at `C:\Program Files\Microsoft\Edge\Application\msedge.exe` | not exercised (Chrome covered the same code path) |
| Tesseract | **missing** | blocks the real desktop OCR test |
| `opencode` 2.2.6 | present | MCP client; the registered `body-dev` server |
| `claude` 2.1.319 | present | MCP client |
| `codex` 0.167.0 | present | MCP client |
| `nvidia-smi` | missing | GPU detection falls back to "unknown" |

## 4. Configuration state

| Item | Value |
|---|---|
| Config dir | `C:\Users\shash\.config\body_mcp` (`BODY_MCP_CONFIG_DIR` overrides it) |
| `permissions.json` | not created yet — defaults apply (`public_web` allow, `consequential`/`app_launch`/`chrome_attach` ask) |
| `consent.json` | **not acknowledged** → protected actions are refused (fail-closed by design) |
| `audit.log` | present (7 642 bytes, plaintext, local only) |
| `memory.db` | created by the campaign only inside throwaway config dirs; the real memory store is untouched by the tests |
| Installed `body-mcp` distribution | **0.1.0** (stale) vs source tree **0.3.0** — the global install shadows the source tree; the venv copy (`D:\…`) carries the current code |

## 5. Devices

| Device | Status |
|---|---|
| Microphone | 8 input devices visible to `sounddevice`; **not exercised** (recording needs the user's consent) |
| Audio output | present — Windows SAPI synthesised 2 voices (Microsoft David Desktop, Microsoft Zira Desktop); playback start/stop verified, audible output is not machine-verifiable |
| Desktop session | interactive (screenshots capture; OCR blocked by the missing Tesseract) |

## 6. External blockers

| Blocker | Effect | Fix |
|---|---|---|
| Tesseract not installed | desktop OCR unverifiable | `winget install -e --id UB-Mannheim.TesseractOCR` |
| Whisper model not downloaded + no recording consent | live STT unverifiable | `pip install -e ".[voice]"`, then `python scripts/acceptance.py --allow-mic` |
| No network-based test performed by design | live-site behaviour unverified | run `python scripts/acceptance.py --public-url https://example.com` when you want a real fetch |
| macOS/Linux not present | cross-platform claims unverified | run the suite on those platforms (the code paths exist) |
| Global `body-mcp` install is 0.1.0 | the globally installed server is older than the source | `pip install -e .` in the venv you actually use |

## 7. What was **not** touched

- No global agent configuration was modified (the OpenCode `body-dev` entry and its backup
  were left as they were).
- No system software was installed or updated.
- No model weights were downloaded.
- The user's own Chrome profile, tabs and history were never read; every CDP test used a
  disposable `--user-data-dir` and terminated the browser afterwards.
- No commits, pushes, deployments or publications were performed.
