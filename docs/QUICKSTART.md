# Quickstart — the smallest path that works

No installs beyond Python and the two project dependencies. No API key, no
account, no model, no Tesseract, no optional engine.

## 1. Install (about 30 seconds)

```powershell
git clone https://github.com/sspublisher2005-gif/body-mcp
cd body-mcp
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m playwright install chromium
```

That's it. `mcp` and `playwright` are the only two core dependencies; they come
with the `pip install -e .` above.

## 2. Check what is real on your machine

```powershell
.\.venv\Scripts\python.exe -m body_mcp.doctor
.\.venv\Scripts\python.exe -m pytest -q
```

The doctor is read-only. It prints the exact install commands for anything
optional — it never runs them. See `docs/OPTIONAL-SOFTWARE.md`.

## 3. Consent and a profile

```powershell
.\.venv\Scripts\python.exe -m body_mcp.consent --acknowledge
.\.venv\Scripts\python.exe -m body_mcp.profiles browser --apply
```

Two small profiles exist: `browser` (web work only, no native desktop control)
and `windows-desktop` (capture + control, gated by approvals). `--apply` keeps a
backup of your previous `permissions.json`.

## 4. Connect it to your coding agent

```powershell
opencode mcp add body-dev -- .\.venv\Scripts\python.exe -m body_mcp.server
```

Your agent is the brain; Body-MCP is the body.

## 5. Run the reproducible demo

```powershell
.\.venv\Scripts\python.exe scripts/demo_real_task.py
```

It opens a **local fixture page**, inspects it (EYES), records one decision
(BRAIN), clicks a permitted link (HANDS), and proves the page actually changed
(VERIFY). No network, no installs, no real profile touched. Expected output:

```
[EYES]   title='Body-MCP Test Page', links=['Read the full article'], refs issued
[BRAIN]  the article link is the only permitted navigation on this page
[HANDS]  message='clicked via text:role=link - page navigated', title='Body-MCP Article'
[VERIFY] found=True, source=file://.../fixtures/article.html, evidence='Body-MCP Article ...'
RESULT: CONFIRMED  | evidence: reports/validation/real-task-proof.json
```

## What you can do with zero optional software

- read and act on web pages, including your own browser via the extension
  (one click to load it — no download);
- see the desktop as an image, even with no OCR engine (a vision model can look
  at it; a text-only brain needs a local model to caption it);
- search supported public sources with evidence records and honest refusals;
- keep a private browsing session with verified cleanup;
- use memory, lessons, undo, background tasks and the local event console.

The private *content* level (text never leaves the machine) needs a local model
that **you** choose to install. Without one, the body withholds the text instead
of sending it to a remote provider.
