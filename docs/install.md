# Install & development guide

## Windows (primary platform)

```powershell
git clone https://github.com/sspublisher2005-gif/body-mcp
cd body-mcp
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

The base install is deliberately small: `mcp` + `playwright` only. Optional
capabilities come as extras, so a low-memory machine never pays for what it does
not use:

```powershell
pip install -e ".[desktop]"   # desktop capture + OCR (mss, pytesseract, Pillow)
pip install -e ".[voice]"     # microphone + local speech-to-text (sounddevice, faster-whisper, numpy)
pip install -e ".[all]"       # everything optional
```

Optional, for `eyes_see_desktop` (desktop OCR):

```powershell
winget install -e --id UB-Mannheim.TesseractOCR
# or point pytesseract at a specific build:
# TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

`.env` (optional, git-ignored, see `.env.example`):

```
BODY_MCP_WHISPER_MODEL=small.en   # tiny.en is 5x faster, small.en is the accuracy/speed balance
BODY_MCP_BROWSER_MODE=headed      # headed (default, visible) | headless
BODY_MCP_POLITE_DELAY_MS=1500     # human-like pace between page actions

# v0.2 — execution and concurrency limits
BODY_MCP_MAX_CONCURRENCY=2        # parallel workers (clamped to hard max)
BODY_MCP_HARD_MAX_CONCURRENCY=4     # absolute cap
BODY_MCP_BATCH_DEADLINE_MS=120000 # total deadline for one hands_batch run
BODY_MCP_PARALLEL_DEADLINE_MS=180000 # total deadline for one hands_parallel run
BODY_MCP_TASK_DEADLINE_MS=60000   # per-task deadline in parallel mode
BODY_MCP_BACKOFF_BASE_S=1         # rate-limit backoff base (exponential, jittered)
BODY_MCP_BACKOFF_MAX_S=60         # backoff ceiling

# Test/development isolation
BODY_MCP_CONFIG_DIR=              # overrides %USERPROFILE%\.config\body_mcp
```

First `ears_listen()` call downloads the Whisper model (~484 MB) into the Hugging Face cache (`%USERPROFILE%\.cache\huggingface`). Set `HF_HOME` to relocate it.

## Verify the install

```powershell
python -m body_mcp.doctor     # read-only diagnostics: what works here, what is missing
python -m pytest              # the full suite
python -m ruff check .        # static checks
python scripts/acceptance.py  # real-environment acceptance checks (honest statuses)
python -m body_mcp.server     # speaks MCP over stdio and waits for the client
```

`body doctor` never changes permissions, never acknowledges consent, never
downloads a model and never edits your agent configuration — it only reports.

The acceptance runner states each check as `PASS_REAL`, `PASS_MOCK_ONLY`, `FAIL`,
`BLOCKED` or `NOT_RUN`. Recording audio needs your consent:

```powershell
python scripts/acceptance.py --allow-mic
```

## Drive the browser you already have open

```powershell
python -m body_mcp.cdp_launch --browser chrome      # a browser window with a loopback debug port
# add --user-data-dir <temp> for a disposable profile while testing
```

Then, from the agent: `attach_browser(endpoint="http://127.0.0.1:9222")` →
`select_tab(...)` → normal eyes/hands tools → `detach_browser()`. The port is
unauthenticated while it is open: restart the browser normally afterwards.

## Connect your coding agent (do the consent step first if you want protected actions)

```powershell
python -m body_mcp.consent --acknowledge   # writes consent.json + default permissions.json
```

```powershell
# OpenCode (https://opencode.ai/docs/mcp-servers/)
opencode mcp add body -- python -m body_mcp.server

# Claude Code
claude mcp add body -- python -m body_mcp.server

# Codex CLI
codex mcp add body -- python -m body_mcp.server
```

Or configure manually (OpenCode **V2** schema — note `mcp.servers`, and `disabled` instead of the old `enabled` key):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "body": { "type": "local", "command": ["python", "-m", "body_mcp.server"] }
    }
  }
}
```

## Development loop

```powershell
pip install -e ".[dev]"
python -m pytest -q              # tests
python -m pytest -k restricted   # focused run
python -m ruff check .
```

Tests run headless Chromium against `tests/fixtures/` and mock the microphone/Whisper/Tesseract. No test touches a network or your real screen.

## macOS / Linux

- `sounddevice` and `faster-whisper` work the same.
- Tesseract: `brew install tesseract` / `apt install tesseract-ocr`.
- `reflex_ask` falls back to "not approved" on non-Windows when clients without elicitation ask — upgrade your MCP client (OpenCode, Claude Code) instead of relying on the dialog.

## Footprint

| Component | Size (approx) |
|---|---|
| base install (`mcp` + `playwright`) | ~50–120 MB |
| `[desktop]` extra (mss, pytesseract, Pillow) | ~30–60 MB |
| `[voice]` extra (sounddevice, faster-whisper, numpy) | ~120–400 MB (CPU build) |
| Chromium (ms-playwright) | ~0.28–0.5 GB |
| Whisper `small.en` model (first use) | ~0.48 GB |
| Tesseract (optional) | ~50–80 MB |

Everything above is local. Nothing phones home. Body-MCP itself is free and open
source: no paid tier, no telemetry, no cloud account, no feature behind a
paywall. The optional downloads above are software you install yourself.
