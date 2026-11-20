# Body-MCP — the full report

> What we are creating, why, for whom, how it works, what is real, what is not,
> and what is next. Written to be read by a human or an LLM with the source
> attached. Every claim below is backed by a file, a test or a command.

---

## 1. What we are creating

**Body-MCP is a free, open-source "body" for AI coding agents.**

A coding agent (OpenCode, Claude Code, Codex…) is the **brain**: it plans, writes
files, runs shells, calls other MCP servers, decides. Body-MCP is the **body**:
it gives that brain eyes, ears, hands, a voice, a memory, a research desk, and a
private mode — through the Model Context Protocol, on the user's own machine.

| Part | What it is |
|---|---|
| **Eyes** | read web pages (DOM, text, links, forms), read the desktop (OCR or raw pixels), watch the screen live, see one downscaled image per call |
| **Ears** | microphone → local Whisper transcript, with silence detection and uncertainty flags |
| **Hands** | open / click / type / press / scroll a real browser; batches and parallel runs; typed values are read back |
| **Legs** | launch an allowlisted desktop app |
| **Voice** | speak (Windows Read Aloud, local, no download) and listen |
| **Memory** | local SQLite + FTS5 + hand-editable Markdown notes; no cloud, no embeddings |
| **Research** | Hacker News, GitHub issues, Stack Overflow, Wikipedia, YouTube + public pages, with evidence records and a fallback chain |
| **Private mode** | isolated disposable browsing, optional VPN assistance, and a local content mode where the text never leaves the machine |
| **Local worker** | summarise / extract / redact / classify / describe with a model running on the user's own hardware |
| **Ledger** | EYES → BRAIN → HANDS → VERIFY as evidence; failures become lessons; undo; background tasks |

**78 MCP tools. 287 tests. MIT licence. No paywall, no telemetry, no cloud account.**

---

## 2. Why

Three reasons, in the order they matter:

1. **Agents are blind and deaf by default.** A pure-text agent cannot see the
   page it is told to click, cannot notice that the UI changed, cannot read a
   dialog box, cannot hear the user. Every one of those gaps turns into a guess.
   Body-MCP closes them **without** taking the decision-making away.
2. **The tools that do exist are either closed or cloud-shaped.** The common
   browser-automation stacks need an account, a paid API, or a hosted browser.
   This project is MIT, runs entirely on the user's machine, and downloads
   nothing unless the user asks for it.
3. **Trust has to be engineered, not promised.** Every capability is gated by a
   permission profile, a consent marker and single-use scoped approvals; every
   outcome carries a verification state (CONFIRMED / UNCONFIRMED / PARTIAL /
   FAILED / BLOCKED / CANCELLED); every protected action is audited. The docs
   say what the tool does **not** do.

---

## 3. For whom

| Audience | What they get |
|---|---|
| **A solo developer using a local LLM** (Ollama, LM Studio, llama.cpp) | a body that runs entirely offline: the reasoning stays local, the page text can stay local, the memory stays local |
| **A privacy-conscious user** (journalists, researchers, legal, health) | a private mode with two honest levels: private *browsing* (free) and private *content* (needs a local model), plus the truth that none of it makes you anonymous |
| **A coding agent builder** | a reference body: how to gate a physical capability, how to report an outcome honestly, how to keep a failure as a lesson |
| **A teacher / student** | 287 readable tests and an honest capability matrix to study |

**Not for** people who want an agent that makes purchases, sends mail, or bypasses
logins — those paths are refused by design (ask → approve → one action → verify).

---

## 4. How it fits together

```
you → coding agent (brain) → MCP + permission gate → Body-MCP (body) → browser · desktop · mic · local model
                                            ↑
                        scoped approvals · consent · audit log · events
```

| Layer | File | Job |
|---|---|---|
| Tools | `src/body_mcp/server.py` | the 78 MCP tools; every one returns `{success, message, data}` |
| Permission gate | `permissions.py`, `approvals.py` | profile (`allow/ask/deny`) + consent + single-use, 300 s, action-bound approvals; deny always wins |
| Perception | `eyes.py`, `browser.py`, `watch.py`, `vision.py`, `ocr/` | pages, desktop, live screen, images, OCR plugins |
| Action | `hands.py`, `batch.py`, `parallel.py`, `uia.py`, `legs.py`, `launch.py` | browser actions, native Windows apps, app launching, your own browser |
| Safety | `restrictions.py`, `safety.py`, `reflex.py` | CAPTCHA/paywall/rate-limit detection, secret scrubbing, verification, human questions |
| Memory & learning | `memory.py`, `lessons.py`, `workflow.py`, `undo.py`, `skills.py` | SQLite+notes, failures→lessons, the evidence ledger, undo, reusable skills |
| Research | `sources.py`, `research.py`, `video.py`, `youtube_search.py` | connectors, fallback chain, video captions, honest refusals |
| Privacy | `privacy.py`, `local_worker.py` | private sessions, VPN assistance, the local content path |
| Local models | `models.py` | the measured catalogue and the per-machine ranking |
| Operations | `runtime.py`, `events.py`, `tasks.py`, `console.py`, `doctor.py` | task registry, event stream, background work, local console, diagnostics |

**The work loop** (also in `AGENTS.md`, enforced by the agent's own rules):
EYES → BRAIN (write the decision down) → HANDS (one validated action) → VERIFY
(`reflex_verify`, read-back) → LEARN (a failure becomes a proposed lesson) →
REPORT (evidence chain).

---

## 5. The safety model (the part that must not be watered down)

* **Nothing is downloaded automatically.** No engine, no model, no media. The
  catalogue prints the command or URL, the exact size and the SHA-256.
* **One approval = one action.** `reflex_ask(action=<spec>)` mints an approval
  bound to `tool | capability | target | url | task_id`, valid 300 s, consumed
  atomically. A different target, a different task, a replay, or a missing
  approval all fail closed.
* **Deny wins** — over a fresh approval.
* **Never bypass** a login, CAPTCHA, paywall, rate limit or bot check. Never
  type or store passwords, OTPs or card data. Never rotate identity or switch
  VPN servers to dodge a block.
* **Content is data, never an instruction.** What a page, a tool result or a
  model says can never grant a permission.
* **Honest states only.** `UNCONFIRMED` is not "done". A click that did not
  navigate is not a completed click.
* **Audit log** (plaintext, local, redacted, size-capped with one rotation) and
  an **event stream** for everything that happened.

---

## 6. The private mode — two levels, stated honestly

| Level | What stays local | Needs |
|---|---|---|
| **A — private browsing** | the browsing: own throwaway context, no cookies, nothing persisted, cleanup verified | nothing (free) |
| **B — private content** | the text: redacted + summarised by a local model; the snapshot returns `text: null` | a local model (Ollama) |

With `keep_content_local=True` and **no** local model, the text is **withheld** —
it is never quietly shipped to the agent's provider. `privacy_vpn_connect()`
opens Proton VPN, asks the app's own button to connect, and reports the state
read from the app's window (`connected` / `not connected` / `unknown`). It is
denied until the user sets `vpn_control: allow` in their own profile.

---

## 7. The local models (measured, not guessed)

Two roles: **worker** (private, local: extraction, dedup, scrubbing, summaries)
and **reasoner** (the agent's own thinking, run locally). The body is the body —
a local worker never replaces the brain.

| Tier | Ollama | llama.cpp | RAM | Vision | Tools | Uncensored |
|---|---|---|---|---|---|---|
| 1 — default worker | `qwen3:0.6b` 498 MB | Qwen3-0.6B-Q4_0 409 MB | ~900 MB | ✗ | ✅ | ✗ |
| 1 — smallest text | `gemma3:270m` 278 MB | gemma-3-270m 278 MB | ~700 MB | ✗ | ✗ | ✗ |
| 2 — one-model pick | `qwen3-vl:2b` 1.80 GB | Qwen3-VL-2B + projector 2.14 GB | ~3.0 GB | ✅ | ✅ | ✗ |
| 3 — uncensored | `dolphin3:8b` 4.92 GB | Dolphin-2.9-8B Q2_K 3.03 GB | ~4.4 GB | ✗ | ✅/✗ | ✅ |

Every row carries the **exact byte size and SHA-256** (Hugging Face API / Ollama
registry manifests). `body_local_models()` ranks against the **measured** free
RAM and marks anything that does not fit with the exact shortfall — it never
offers a model that will not run.

**The body can be the eyes of a text-only brain**: `body_local_worker(task=
"describe", image=…)` sends a screenshot to a **local** vision model and returns
the caption as text. It refuses when no local vision model exists — a text-only
model would invent a caption.

---

## 8. What is verified, and how

| Area | Status | How |
|---|---|---|
| Browser eyes/hands vs fixtures + a local HTTP server (429/403/CAPTCHA pages) | **real** | `tests/test_tools.py`, `tests/test_batch_parallel.py` |
| Current-browser CDP attach → select → act → verify → detach | **real** (Chrome 157) | `tests/test_attach_real.py` |
| MCP stdio handshake, tool discovery, tool call, clean shutdown | **real** (subprocess) | `tests/test_mcp_stdio.py` |
| Local TTS (Windows SAPI) | **real** (synthesis + playback start; audible output human-confirmed) | `tests/test_voice.py` |
| Local memory (SQLite + FTS5 + notes) | **real** | `tests/test_memory.py` |
| Privacy session: isolation, no persistence, verified cleanup | **real** | `tests/test_privacy_session.py` |
| Image path without OCR (78 KB JPEG attached) | **real**, on a machine with no Tesseract | `tests/test_eyes_image_path.py`, `tests/test_vision.py` |
| Batch / resume / parallel / checkpoint / approvals | **real** (unit + integration) | `tests/test_batch_parallel.py` |
| Truthful outcomes, stale refs, audit contents | **real** | `tests/test_truthfulness.py` |
| Extension bridge (drive your own Edge/Chrome) | **mock-tested** — never run inside a real browser | `tests/test_bridge.py` |
| `privacy_vpn_connect` (Proton VPN) | **mock-tested** — Proton VPN is not installed here; the button name is unverified | `tests/test_privacy_vpn.py` |
| Local worker / `describe` (Ollama) | **mock-tested** — no Ollama on this machine | `tests/test_local_worker.py` |
| Microphone / Whisper | **mock-tested only** — never run on the user's mic | `tests/test_voice.py` |
| Desktop OCR | **blocked** — Tesseract not installed here | `docs/ocr.md` |
| Video frame decoding | **blocked** — no ffmpeg/OpenCV (a folder of frames also works) | `tests/test_demo_frames.py` |
| YouTube captions | **blocked here** — this IP is currently rate-limited (429); the public timedtext endpoint returned 0 bytes | `tests/test_video.py` |
| Reddit / X / Instagram | **not exercised** — 403 / credentials required | `docs/research-and-interview.md` |
| macOS / Linux | **never executed** (UI Automation is Windows-only) | — |

---

## 9. How to run it

```powershell
git clone <repo> && cd body-mcp
python -m venv .venv; .venv\Scripts\activate
pip install -e ".[desktop,voice,dev]"
python -m playwright install chromium
python -m body_mcp.doctor          # read-only diagnostics + the exact next commands
python -m body_mcp.consent --acknowledge
```

Add it to an agent:

```powershell
opencode mcp add body-dev -- python -m body_mcp.server
claude  mcp add body-dev -- python -m body_mcp.server
codex   mcp add body-dev -- python -m body_mcp.server
```

Optional, free, user-installed: Tesseract (OCR), Ollama (local models), Brave
(private engine), Proton VPN, ffmpeg (video frames).

---

## 10. What is still open

**Needs the user (one command each):** `winget install Ollama.Ollama` →
`ollama pull qwen3:0.6b`; `winget install -e --id UB-Mannheim.TesseractOCR`;
free up ~500 MB of RAM (a 700 MB model must fit); load `extension/` in
Edge/Chrome with "Allow in Incognito"; install Proton VPN and Brave.

**Needs a decision:** the git remote (none is configured — nothing has been
pushed), the repository name and owner, the licence for the public release, the
version to cut (0.3.0 is tagged; the new work is in `[Unreleased]`).

**Needs other hardware:** macOS and Linux runs.

---

## 11. The shape of the next phase

1. **Prove the local path.** Install Ollama, pull `qwen3:0.6b` and `gemma3:270m`,
   then run the real `body_local_worker` and `describe` paths end to end — the
   code is mock-tested only.
2. **Prove the extension bridge** in a real browser (one click by the user).
3. **Prove the private mode** with Brave + Proton VPN + `keep_content_local=True`
   on a machine that can fit the model.
4. **Publish**: remote, licence, version, wheel to PyPI, the docs as a website.
5. **Grow the body**: more research connectors (only where an authorised path
   exists), a better local worker prompt set, a community model catalogue.

---

*Generated from the repository at commit `5305d7f`. 287 tests pass, Ruff is
clean, and the OpenCode MCP server was verified live (v0.3.0, 78 tools).*
