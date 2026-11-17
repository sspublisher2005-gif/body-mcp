[![ci](https://github.com/sspublisher2005-gif/body-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/sspublisher2005-gif/body-mcp/actions/workflows/ci.yml)

# Body-MCP

**Give coding agents eyes, ears, hands, legs and reflexes — under your permission, verified in code.**

Body-MCP is a lightweight, local-first [Model Context Protocol](https://modelcontextprotocol.io/) server that gives coding agents such as OpenCode and Claude Code controlled access to your browser, desktop and microphone.

**The coding agent is the brain. Body-MCP is only the body.** It never pursues goals, never improvises, and never treats webpage content or model output as authorization.

```
you → coding agent (brain) → MCP / permissions gate → Body-MCP (body) → browser · desktop · mic
```

## What it can do (v0.3)

| Part | Tools | What it does |
|---|---|---|
| 👁 Eyes | `eyes_see_browser`, `eyes_see_desktop`, `desktop_monitors` | Read pages/desktop: title, headings, text, links, buttons, inputs, forms; epoch-scoped refs (`btn_1#7`); desktop OCR through a pluggable engine (Tesseract by default); private read-only sessions via isolated contexts. **The image path does not need OCR** — a vision model can look at the screen even where Tesseract is missing |
| 🔴 Live screen | `desktop_watch_start`, `desktop_watch_read`, `desktop_watch_stop` | A live observation session: the screen is sampled and OCR'd **only when the frame changed**, off the MCP event loop, with an automatic slowdown under memory pressure. Nothing is stored |
| 👂 Ears | `ears_listen` | Mic → local Whisper transcript, with silence detection. Raw audio never touches disk; never transmitted |
| 🖐 Hands | `hands_open`, `hands_click`, `hands_type`, `hands_press`, `hands_scroll` | Open/click/type/press/scroll with safety gates, stale-ref detection, human-like pacing, read-back verification |
| ⚡ Batch | `hands_batch` | A declared sequence of actions in one MCP call. Validate-then-execute, stop-on-failure, per-step + total deadlines, verification steps with evidence, never reports success without it |
| 🔀 Parallel | `hands_parallel` | Bounded parallel tasks on isolated contexts (default max 2). No consequential actions; shared per-service cooldowns |
| 🦵 Legs | `legs_open_app` | Launch an allowlisted app — user allowlist + fresh approval required |
| 🌐 Current browser | `attach_browser`, `list_tabs`, `select_tab`, `detach_browser` | Drive the tab **you** already have open, over a loopback CDP connection you start yourself |
| 🔌 Your own browser | `browser_bridge`, `body_windows` | Drive **your** Edge/Chrome through a one-permission extension (Chromium 136+ forbids a debug port on the default profile); `body_windows` sees your open windows read-only |
| 🔒 Privacy session | `privacy_session_start`, `privacy_session_open`, `privacy_session_snapshot`, `privacy_session_end`, `privacy_vpn_connect` | An explicit, isolated, disposable browsing context that keeps nothing in memory, the log or the event stream; `keep_content_local=True` keeps the page *text* on your machine too; the VPN app is driven only with your approval |
| 🧠 Local worker | `body_local_worker`, `body_local_models` | Summarise / extract / redact / classify text with a model running on **your** machine (Ollama or a GGUF) — nothing leaves the box; the catalogue ranks models against your measured RAM |
| 🛡 Reflexes | `reflex_verify`, `reflex_ask` | Verify observable outcomes; ask the human yes/no. One approval = one protected action |
| 📚 Memory | `memory_search`, `memory_write`, `memory_list`, `memory_delete`, `memory_export`, `memory_note` | Local SQLite + FTS5 memory and human-editable Markdown notes. No cloud, no embeddings, no vector DB |
| 🔬 Research | `research_collect` | Bounded, deduplicated evidence records: URL, title, date, excerpt, retrieval method, verification status |
| 🖥 Desktop hands | \desktop_inspect\, \desktop_click\, \desktop_type\, \desktop_read_value\ | Drive NATIVE Windows apps by control name (UI Automation) - no blind coordinates; clicking/typing need approval |
| 🎬 Research video | esearch_video\, esearch_youtube_search\ | Read a video's metadata, chapters and OFFICIAL captions (the audio, no model download); find reference videos |
| 🧠 Workflow | \ody_workflow_start\, \ody_workflow_note\, \ody_workflow_report\, \ody_lessons\ | The ledger of EYES->BRAIN->HANDS->VERIFY, and what we learned from failures |
| 🖥 Console | `body_console_start`, `body_console_stop` | Optional local activity view (loopback + token): real task timeline, cancel and disconnect |
| 🩺 Health | `body_status`, `body_events`, `body_cancel`, `body_profile`, `body_models`, `body_recommend`, `body_voice_engines` | Capability states, live event stream, cancellation, system inventory, backend catalogue, a dry-run recommendation and the available speech engines |
| 🔊 Voice out | `body_speak`, `body_stop_speaking` | Optional Read Aloud with the built-in Windows voice (no download, no network) |

78 tools total. Every tool answers `{success, message, data}`; `data` carries the
result state, the evidence and the recovery hint.

**Body-MCP is free and open source.** There is no paid tier, no telemetry, no
cloud account and no feature locked behind payment. Optional capabilities depend
on optional software **you** install yourself (Tesseract, faster-whisper, Ollama)
— never on a subscription. Body-MCP and its agents never install anything for
you; sizes, official sources and the reasons are in `docs/OPTIONAL-SOFTWARE.md`.

## Result states (honest by construction)

| State | Meaning |
|---|---|
| `CONFIRMED` | A postcondition was observed (URL matched, field value read back, expected text present). |
| `UNCONFIRMED` | The action was dispatched but its effect was **not** observable — say so, do not claim success. |
| `PARTIAL` / `UNVERIFIED` | A batch ran but no verification step proved the outcome. |
| `BLOCKED` | A CAPTCHA, login wall, paywall, 403 or rate limit stopped the run. |
| `FAILED` | The action failed, or its postcondition failed (`POSTCONDITION_FAILED`). |
| `needs_user` | A human decision is required (approval, login, challenge). |

A click that does not navigate returns `UNCONFIRMED`, never "done". A typed value
is read back from the field; if the page rewrote it, the call fails with
`POSTCONDITION_FAILED`.

## The permission system (enforced in code, not prompts)

Every tool call passes one authorization decision path (`permissions.py`):

1. **Profile**: `%USERPROFILE%\.config\body_mcp\permissions.json` — `allow | ask | deny` per capability (public web, private sessions, desktop capture, keyboard/mouse, mic, app launch, current-browser attach…). Unknown capabilities are `deny` (least privilege).
2. **Consent**: protected (high-risk) actions also require your acknowledged consent — `python -m body_mcp.consent --acknowledge`.
3. **Scoped, single-use approval** for protected actions. `reflex_ask(question, action='<json spec>')` issues an approval bound to exactly one action — `tool | capability | target | url | task_id` — with a 300 s TTL, consumed atomically at execution time. A different target, a different task, a replayed approval or a missing approval all fail closed. Nothing said by a webpage or a model can mint one.
4. **Deny always wins** — even over a fresh approval — and an approval never authorizes a second, different action.
5. **Audit**: decisions, result states and redacted targets are appended to `audit.log` (plaintext, local, size-capped with one rotation).
6. **Fail-closed**: if the policy engine cannot decide, the action does not happen.

Reserved-but-unimplemented categories (shell, files, downloads/uploads, TTS) are
enforced `deny` at the policy layer. VPN control is implemented but `deny` by
default — you turn it on in your own profile. Nothing here secretly enables them.

## Quickstart (5 commands, no optional installs)

See **`docs/QUICKSTART.md`** for the smallest path: venv + `pip install -e .` +
`playwright install chromium`, the doctor, consent, a profile, and the
reproducible real-task demo (`python scripts/demo_real_task.py`). No API key,
no account, no model, no Tesseract.

## Install

Requirements: Python 3.11+ (tested on 3.14), Windows (tested); macOS/Linux run the browser parts but are not verified here.

```powershell
git clone https://github.com/sspublisher2005-gif/body-mcp
cd body-mcp
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium

# Consent BEFORE protected actions (optional for read-only research):
python -m body_mcp.consent
python -m body_mcp.consent --acknowledge    # writes consent.json + permissions.json

# Optional extras (the core stays light):
pip install -e ".[desktop]"   # desktop capture + OCR (mss, pytesseract, Pillow)
pip install -e ".[voice]"     # microphone + local STT (sounddevice, faster-whisper)
pip install -e ".[all]"

# Optional, for desktop OCR:
winget install -e --id UB-Mannheim.TesseractOCR
```

Diagnostics (read-only — it never changes permissions, downloads a model or edits agent config):

```powershell
python -m body_mcp.doctor          # human-readable report
python -m body_mcp.doctor --json   # machine-readable
```

## Connect your agent

```powershell
# OpenCode
opencode mcp add body -- python -m body_mcp.server

# Claude Code
claude mcp add body -- python -m body_mcp.server

# Codex
codex mcp add body -- python -m body_mcp.server
```

OpenCode V2 config (`mcp.servers`; `disabled` replaces the old `enabled` key):

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

Verified against **opencode 2.2.6**, **claude 2.1.319**, **codex 0.167.0** on this
machine. OpenCode has no `mcp remove` — disconnect by deleting the `body` entry
from `~/.config/opencode/opencode.jsonc` (back it up first).

See `examples/research_prompt.md` for a safe research prompt to your agent.

## Driving the browser you already have open

Body-MCP can drive **your** Chrome/Edge tab instead of a Playwright-managed one.
The connection is explicit and loopback-only:

```powershell
# 1) YOU start the browser with a debug port (Body-MCP never does this for you)
python -m body_mcp.cdp_launch --browser chrome          # add --port 9222
#    Use --user-data-dir <temp> for a disposable profile while testing.

# 2) The agent asks for approval, then attaches
attach_browser(endpoint="http://127.0.0.1:9222")   # lists your tabs (title/url only)
select_tab(selector="0")                            # or a unique url/title substring
... normal eyes_see_browser / hands_* tools now act on that tab ...
detach_browser()                                    # closes OUR connection only
```

Rules that are enforced in code:

- The endpoint must be `http://127.0.0.1|localhost|::1` — a non-loopback host is refused.
- Attaching and selecting a tab each require their own scoped approval (`chrome_attach` capability). The spec you approve names the exact endpoint/tab.
- DevTools windows are never candidates; unselected tabs are never read or touched.
- `detach_browser()` closes only our CDP session — your browser keeps running.
- The debug port is **unauthenticated**: while it is open, any local process can drive your browser. Restart the browser normally afterwards to drop the port.

## Your own browser, honestly

Body-MCP can drive a browser **it starts itself** (`python -m body_mcp.cdp_launch` +
`attach_browser()`). It **cannot** drive the Edge/Chrome window you opened yourself:
since Chromium 136 the browser ignores `--remote-debugging-port` when the default
profile is used, so there is no endpoint to connect to (verified on this machine:
the process starts *with* the flag and the port still refuses connections).

What works today for your own window is read-only: `body_windows()` reports the
visible window titles (no content, no screenshots). Controlling your everyday window
needs the **extension bridge** - a Chromium extension attaching with `chrome.debugger`
after you click "Allow", over a validated native-messaging channel. That is the one
browser piece still to be built; everything else is in place.

## Seeing (vision mode)

By default the eyes return **text and structure** - no pixels ever enter the model's
context. That is the cheap, exact path for web pages. When text is not enough (a canvas,
an image, a video frame, a game), ask for the pixels:

```
eyes_see_browser(url="…", screenshot=True)   # text AND one downscaled image
eyes_see_desktop(as_image=True)              # the screen/region as one image
desktop_watch_read(as_image=True)            # the latest frame of a live session
```

The image is produced in memory, downscaled (max 1280 px wide) and compressed
(≤ 900 KB), delivered as an extra MCP content block next to the usual JSON, and never
stored. Details: `docs/perception.md`.

## Hearing

```
ears_listen(seconds=8, stop_on_silence=True)
```

Push-to-talk: the recording starts on request and ends shortly after you stop talking.
The transcript comes back as editable text, with the fragments that were recognised at
low confidence listed separately so you can ask the user to confirm them. Raw audio stays
in memory and is zeroed after use.

## Live desktop OCR

```powershell
python scripts\acceptance_desktop.py      # real window -> real capture -> real OCR
```

* `eyes_see_desktop(monitor=1)` captures one screen (or a `region`) and OCRs it.
* `desktop_watch_start(interval=3)` starts a **live observation session**: the screen is
  sampled and OCR'd **only when the frame changed**, in a worker thread, with the sampling
  interval growing automatically when memory is tight. `desktop_watch_read()` returns the
  latest observation; `desktop_watch_stop()` ends it.
* The OCR engine is discovered, never assumed: Tesseract by default (a packaged release
  may bundle it), RapidOCR optional. Without an engine you get the exact install command.
* Screen content is returned on request and never written to disk, the audit log or memory.

Details, licences and the platform status: `docs/ocr.md`.

## Downloading a release

```powershell
python scripts\build_release.py          # -> dist/*.zip + .sha256 + manifest.json
python scripts\build_release.py --list   # the release matrix
```

Body-MCP is MIT and **free**: no paid tier, no telemetry, no cloud account. See
`docs/release.md` for what was built and tested on which platform, and
`THIRD_PARTY_NOTICES.md` for the licences of everything that may be bundled.

## Seeing what the body is doing (optional console)
```powershell
# from inside an agent session:
body_console_start(port=8765)   # returns http://127.0.0.1:8765/?token=...
```

The console is a small local page showing the **real** executor events: task
lifecycle, the action that actually ran, verification results, blockers and
where your approval is needed. It can cancel the running task and disconnect the
browser. It binds to `127.0.0.1` only and requires the session token; the MCP
server works fine without it.

## Persistent local memory

```powershell
# search what the project already learned
memory_search("how do we run the tests?")
# store a verified lesson
memory_write(title="Browser refs are epoch-scoped", content="A ref from an older scan is refused as stale",
             scope="project", type="decision", verified=True)
# human-editable Markdown notes
memory_note("conventions.md", "# Conventions\nRun `python -m pytest -q` before reporting done.")
```

Everything is a local SQLite file (`<config>/memory.db`) plus Markdown notes in
`<config>/notes/`. Credentials are refused. Unverified lessons stay marked as
proposals. Privacy-session browsing never lands here.

## Evidence-based research

`research_collect(urls)` fetches the listed pages in a throwaway context and
returns evidence records: source, URL, title, publication date, excerpt,
retrieval method, content hash, verification status and any limitation. Pages
behind a login, CAPTCHA, paywall or rate limit are reported as blocked — never
bypassed. Only the listed sources are fetched; the tool never claims a platform
was searched exhaustively.

## Privacy sessions

`privacy_session_start()` opens an isolated, disposable browsing context. Its
URLs, titles and content are not written to the audit log, the event stream or
persistent memory; `privacy_session_end()` closes the context, discards its
cookies/storage and reports whether the cleanup was verified. Your ordinary
browser profile is never touched. This reduces local persistence — it is **not**
anonymity.

**Two levels, and they are not the same thing:**

* **private browsing** (always on) — the browsing is local: own context, no
  cookies, nothing persisted.
* **private content** (`keep_content_local=True`) — the *text* stays on your
  machine too: a local model redacts and summarises the page, and only the
  summary is returned. Without a local model the text is **withheld**, never
  quietly sent to your model provider.

See `docs/privacy-mode.md` for the full picture and `docs/local-models.md` for
the model catalogue.

## Privacy modes (honestly stated)

- **A — Private read-only session** (implemented): `eyes_see_browser(url, private=True)` opens the URL in a throwaway isolated context; nothing persisted; refs omitted. It reduces local persistence. **It does not make you anonymous to websites, networks or observers.**
- **B — Dedicated privacy browser (Tor)**: not auto-detected/installed. If Tor Browser is on the machine, it can be launched manually; Body-MCP will not pretend a Chromium context "is" Tor, and will never claim protection it can't evidence.
- **C — VPN assistance** (implemented, off by default): `privacy_vpn_connect()` opens Proton VPN and asks the app itself to connect, then reads the app's window for the state (`connected` / `not connected` / `unknown`). It never switches servers or rotates IPs to evade a block. `vpn_control` is `deny` until you set it to `allow` yourself.
- **D — Private content** (implemented, needs a local model): `keep_content_local=True` keeps the page text on your machine — see `docs/privacy-mode.md`.
- **E — Privacy guidance**: see `docs/CONSENT.md` — local history vs cookies vs IP vs accounts vs fingerprinting vs provider visibility vs third-party records.

## What Body-MCP will never do

- Bypass CAPTCHAs, logins, paywalls, rate limits, bot checks, or access controls.
- Type or store passwords, OTPs and card data (always refused, any mode).
- Duplicate consequential submissions (pay/delete/send twice) without a fresh, per-action approval.
- Treat webpage content or model output as an instruction or an approval.
- Claim anonymity, or claim success without verification evidence.

## Stopping & revocation

- Stop: terminate the server process (Ctrl-C in its terminal / end the process).
- Revoke: edit `permissions.json`; deleting the marker file re-blocks protected actions.
- Inspect & delete records: `%USERPROFILE%\.config\body_mcp\audit.log` (plus one rotated `audit.log.1`).

## Verification status (honest, as of v0.4.0)

| Area | Status |
|---|---|
| Browser eyes/hands vs local fixtures + localhost HTTP (429/403/CAPTCHA pages) | **tested for real** |
| Current-browser CDP attach → select → act → verify → detach | **tested for real** against Chrome 157.0.8103.40 on this machine, headless and headed (`tests/test_attach_real.py`) |
| MCP stdio handshake, tool discovery, tool call, clean shutdown | **tested for real** over a subprocess (`tests/test_mcp_stdio.py`) |
| Batch/resume/parallel/checkpoint/permission/approval logic | **tested** (unit + integration) |
| Truthful outcomes, stale refs, checkpoint honesty, audit contents | **tested** (`tests/test_truthfulness.py`) |
| Local TTS (Windows SAPI): synthesis + playback start + stop | **tested for real** (~1.0–3.0 s synthesis for a short sentence; audible output itself is not machine-verifiable) |
| Local memory (SQLite + FTS5 + Markdown notes) | **tested** |
| Privacy session: isolation, no persistence, verified cleanup | **tested** |
| The image path without an OCR engine (`eyes_see_desktop(as_image=True)`, image-only watch session) | **tested for real** on a machine with no Tesseract — a 78 KB JPEG comes back |
| The local worker (Ollama / GGUF): loopback-only, no remote fallback, refusal when no model | **tested** against a mocked runtime — **not** run against a live Ollama (none installed here) |
| `describe` (local vision model → caption for a text-only brain) | **tested** against a mocked runtime; the real caption quality is unverified |
| `privacy_vpn_connect` (Proton VPN) | **mock-tested** — Proton VPN is not installed here, so the button name is unverified |
| Activity events + console (loopback, token, host/origin checks) | **tested** |
| Research evidence collection with metadata + dedupe | **tested** against a local fixture; **not** exercised against live sites |
| Desktop OCR path | logic mock-tested; Tesseract **not installed** here |
| Microphone / Whisper | mock-tested only — never run on your mic (doctor reports the visible input devices) |
| Live web (Reddit, X, Instagram…) | not exercised; those platforms need their own authorised access path |
| Text-to-speech on non-Windows | not implemented (the default engine is the Windows system voice) |

Run the whole acceptance suite yourself:

```powershell
python scripts/acceptance.py                 # real checks, honest statuses
python scripts/acceptance.py --allow-mic     # + a 5-second microphone recording
python scripts/campaign.py --runs 3          # the full QA campaign -> reports/qa-campaign/
python scripts/measure.py                    # startup, latency and payload sizes
```

The QA campaign results live in `reports/qa-campaign/` (`test-report.md`,
`test-matrix.csv`, `defects.md`, `environment-report.md`).

## Measured performance (scripts/benchmark.py, local fixtures, 5 reps each)

| Mode | Verified ok | Median | p95 | Calls |
|---|---|---|---|---|
| Sequential eyes→type→click→verify | 5/5 | ~399 ms | ~6904 ms* | 4 |
| hands_batch (same task) | 5/5 | ~283 ms | ~655 ms | 2 |
| hands_parallel (2 independent tasks, 1 call) | 5/5 | ~288 ms | ~567 ms | 1 |
| Same 2 tasks sequentially | 5/5 | ~143 ms | ~161 ms | 4 |

\* p90+ includes one Chromium cold start; batch cut MCP round-trips ~50%; parallel's context overhead only pays off on network-bound loads. Machine-dependent — run `python scripts/benchmark.py` yourself.

## Support matrix (what is actually verified)

| Platform | Browser (managed) | Browser (your tab, CDP) | Desktop OCR | Mic/STT | TTS | MCP client |
|---|---|---|---|---|---|---|
| Windows 11 (this machine) | tested | tested (Chrome 157) | logic only (no Tesseract) | mock only | tested (SAPI) | opencode 2.2.6, claude 2.1.319, codex 0.167.0 |
| macOS / Linux | code paths exist, not run | code paths exist, not run | not verified | not verified | not implemented | MCP-standard, unverified |

## Docs

- `docs/architecture.md` — modules and flows
- `docs/safety.md` — the safety spine: enforced in code vs documentation-only
- `docs/CONSENT.md` — user consent and responsible use
- `docs/install.md` — detailed setup
- `docs/opencode.md` — OpenCode setup, first-run checks, troubleshooting
- `examples/research_prompt.md` — a safe research prompt for your agent
- `AGENTS.md` — the standing rules for agents using Body-MCP

## Contributing / License

MIT. See LICENSE. Keep the body small, honest and fail-closed.
