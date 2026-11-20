# The backlog — every open item, with how to prove it closed

Every line here is a real gap in this repository, not a wish list. Each item
states **what**, **where**, **why it matters**, and **the verification** that
closes it. Work them top to bottom; do not claim an item closed without its
verification.

Legend: 🔴 blocks a real user · 🟠 weakens a promise · 🟡 polish

---

## P0 — the promise that is only half-proven

### 1. 🔴 The local worker has never run against a real model
**What:** `body_local_worker` and `task="describe"` are **mock-tested only** —
no Ollama exists on the machine where they were written. The HTTP contract
(`/api/generate` with `images`), the model selection and the caption quality
are unverified.
**Where:** `src/body_mcp/local_worker.py`, `tests/test_local_worker.py`.
**Why it matters:** the private-content feature ("the text never leaves your
machine") is the headline claim of the private mode. If the call shape is wrong,
the claim is false.
**Verification (do NOT install anything — see D17):**
```
# Suggest the commands below to the user; never run them yourself.
# If the user HAS installed Ollama and pulled the models, verify:
ollama list                                  # must show qwen3:0.6b + qwen3-vl:2b
python scripts/acceptance_private_mode.py    # must show the worker available
# then, through the MCP server:
body_local_worker(task="summarise", text=<a real page>)   -> success, local: true
body_local_worker(task="describe", image=<base64 png>)    -> a caption
```
If the user has not installed them, **stop and report the gap** with the exact
commands (`winget install Ollama.Ollama`, `ollama pull qwen3:0.6b`,
`ollama pull qwen3-vl:2b` - the model the agent uses, never ours to install)
and the sizes from `docs/OPTIONAL-SOFTWARE.md`.
Never claim this item closed.
**Acceptance:** the tool returns `local: true` with a real model name, and the
caption describes the actual screen. If Ollama's `/api/generate` rejects the
`images` field, switch to `/api/chat` (which documents images) and re-test.

### 2. 🔴 The extension bridge has never run in a real browser
**What:** `browser_bridge` drives the user's own Edge/Chrome through the MV3
extension in `extension/`. It is mock-tested; no browser has ever loaded it.
**Where:** `extension/`, `src/body_mcp/bridge.py`, `tests/test_bridge.py`.
**Why it matters:** Chrome 136+ ignores `--remote-debugging-port` on the default
profile, so the bridge is the **only** way to drive a user's everyday browser.
If it does not work, "your own browser" is a dead feature.
**Verification:** load `extension/` in Edge or Chrome (developer mode → load
unpacked), open a tab, click the extension, allow in incognito, then
`browser_bridge(action="tabs")` → `browser_bridge(action="read")` →
`browser_bridge(action="navigate", url=...)`. Every call must return the real
tab's content.
**Acceptance:** a real page read back from the user's own tab, with a
screenshot attached.

### 3. 🔴 The VPN path is unverified against the real app
**What:** `privacy_vpn_connect()` clicks Proton VPN's "Quick Connect" and reads
the state from the app's window. Proton VPN is **not installed** on the machine
where this was written; the button name is version-specific.
**Where:** `src/body_mcp/privacy.py` (`vpn_connect`), `tests/test_privacy_vpn.py`.
**Why it matters:** a private mode that claims a VPN it never connected is
worse than one that admits it cannot.
**Verification:** install Proton VPN, set `"vpn_control": "allow"` in
`%USERPROFILE%\.config\body_mcp\permissions.json`, run `privacy_vpn_connect()`.
**Acceptance:** the reported state matches what the Proton app shows (compare
by eye), and the tool reports `unknown` rather than `connected` when the app
does not say so. If the button is named differently, extend `VPN_CONNECT_LABELS`
— never a fuzzy match.

### 4. 🔴 Desktop OCR is untested on a real engine
**What:** the OCR path is mock-tested; Tesseract is not installed here. The
capture is real, the recognition is not.
**Where:** `src/body_mcp/ocr/`, `src/body_mcp/eyes.py`.
**Verification (only if the user installed it — never install it yourself):**
`eyes_see_desktop()` → real text; `desktop_watch_start()` → the changed-frame
text. Otherwise report the blocked state and suggest
`winget install -e --id UB-Mannheim.TesseractOCR` with the size from
`docs/OPTIONAL-SOFTWARE.md`.
**Acceptance:** recognised text matches what is on screen, and the safety scan
(`sensitive_mode`) still fires.

---

## P1 — the free, local promise needs the one command

### 5. 🟠 No local model fits a small machine
**What:** the smallest catalogue entry needs ~700 MB RAM (`gemma3:270m`) and the
machine had 494–564 MB free. `body_local_models()` correctly refuses to
recommend anything, but a user on a 4 GB laptop sees "nothing fits".
**Where:** `src/body_mcp/models.py`, `docs/local-models.md`.
**Options:** (a) document a swap-and-close checklist; (b) add a genuinely
smaller option (a ~200 MB text worker) if one exists with an honest size and
licence; (c) add a "lowest-memory mode" that trades quality for a smaller
model and says so.
**Verification:** `body_local_models()` on a machine with < 700 MB free must
print the exact shortfall and the cheapest option that would fit.

### 6. 🟠 The live watcher (image-only mode) is new and barely tested
**What:** `desktop_watch_start(ocr=False)` was added so the body can watch a
screen without OCR. It is unit-tested; it has never watched a real screen.
**Where:** `src/body_mcp/watch.py`, `src/body_mcp/server.py`.
**Verification:** start a session with `ocr=False`, change something on screen,
poll `desktop_watch_read(as_image=True)` → a changed frame arrives and
`observations` increments; the frame must differ from the previous one.

### 7. 🟡 The `describe` caption quality is still unmeasured
**What:** the prompt asks for 5 factual bullets, and the GitHub Actions runner
proved `qwen3-vl:2b` can return a caption — but nobody has measured whether the
caption actually matches the screen.
**Where:** `src/body_mcp/local_worker.py` (`PROMPTS["describe"]`).
**Verification:** describe 10 real screenshots (an editor, a login page, a
spreadsheet, a video call) and check that no caption contains text that is not
on the screen. If the model invents detail, say so in the docs.
**Note:** `gemma3:270m` was wrongly listed as a vision model; a real runner
proved it text-only ("Multimodal data provided, but model does not support
multimodal requests"). The catalogue and the model picker now refuse it.

---

## P2 — publication

### 8. 🟠 Nothing is published; there is no remote
**What:** 7 commits, no git remote, no PyPI upload, no GitHub repo. The wheel
builds (181 KB) and installs clean (78 tools discovered).
**Needs from the user:** repository name, owner, licence for the public
release, and the decision to publish the wheel to PyPI.
**Verification after it is done:** `python scripts/clean_install_check.py` from
a fresh clone → 6/6; `pip install body-mcp` in a clean venv → `python -m
body_mcp.doctor` → ok.

### 9. ✅ CLOSED — the version was cut
**Done 2026-11-13:** `pyproject.toml` and `__version__` are `0.4.0`, the
`[Unreleased]` block became `[0.4.0] - 2026-11-13`, the README table says
v0.4.0, tag `v0.4.0` is on GitHub with a release and four assets.

### 10. 🟡 The QA reports describe the old feature set
**What:** `reports/qa-campaign/` (test-report.md, test-matrix.csv, defects.md,
environment-report.md, qa-reconciliation.md) was written for the 0.3.0
campaign. The private mode, the local worker, the image path and the VPN are
not in it.
**Action:** run a fresh campaign (`python scripts/campaign.py --runs 3`) and
update the reports, or add a dated addendum — do not rewrite history.

---

## P3 — honest limits that stay honest

### 11. 🟡 YouTube captions are unavailable from this network
**What:** the public `timedtext` endpoint returned **0 bytes** (proof-of-origin
token) and the watch page now answers **429** for this IP. The code reports
`BLOCKED` honestly; no workaround is implemented.
**Options:** the captions panel via the controlled browser (the browser is
already there); `yt-dlp` + a local Whisper model (needs the user's consent for
the download and the mic-free local decode); or leave it blocked and say so.
**Never:** retry aggressively or rotate the IP to get past a rate limit.

### 12. 🟡 Reddit, X and Instagram are not accessible
**What:** Reddit's public API answers 403 anonymously; X and Instagram need
authorised API access or a logged-in user session.
**Action:** keep the honest refusals; add connectors only for paths that are
authorised. No scraping around the blocks.

### 13. 🟡 macOS and Linux have never been executed
**What:** the project claims cross-platform support for the browser parts;
only Windows has been run. UI Automation, TTS and the window list are
Windows-only by design.
**Action:** run `pytest -q` on macOS and Linux and report what breaks; make
the platform-specific modules import-safe on POSIX (`windows.py`, `uia.py`,
`tts.py`).

### 14. 🟡 TTS output is not machine-verifiable
**What:** synthesis and playback start are tested; "the user heard the words"
is not. It was confirmed once by a human.
**Action:** keep the wording ("playback started"), never "the user heard it".

---

## P4 — hardening

### 15. 🟠 `permissions.check` vs `permissions.authorize`
**What:** three tools used a *check* that could never consume a scoped
approval (`desktop_click`, `desktop_type`, `browser_bridge`) and were
therefore unusable under the default profile. Fixed. **Check the rest**: any
tool gating on a capability whose profile value is `ask` must use
`authorize()`, or it can never run.
**Verification:** grep for `permissions.check(` and compare every capability
against `DEFAULT_CAPABILITIES` in `permissions.py` — anything that defaults to
`ask` must be `authorize()`.

### 16. 🟡 `body_status` must stay true
**What:** it claimed `vpn_control: not_implemented` after the VPN shipped.
Every capability line is a promise to the agent.
**Action:** after adding a tool, update `body_status` in the same commit.
**Verification:** a test that asserts each capability string matches the code
that implements it (at least: the VPN, the local worker, the image path, the
OCR state).

### 17. 🟡 The audit log and the event stream
**What:** both are implemented and tested, but nothing checks that they stay
bounded and redacted over a long session.
**Verification:** run a long session, then check `audit.log` size, rotation and
that no page text or secret leaked into it.

---

## Definition of done (for every item)

1. A **test** that fails before the change and passes after it (or a command
   whose output changes).
2. `python -m pytest -q` → all green, no warnings.
3. `python -m ruff check .` → clean.
4. The docs updated in the same commit (`docs/`, `README.md`, `CHANGELOG.md`).
5. A line in the report saying **what was verified and how** — and if it could
   not be verified here, say exactly that.
