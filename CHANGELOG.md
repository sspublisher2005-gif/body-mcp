# Changelog

All notable changes to Body-MCP. The format follows Keep a Changelog; the project
follows semantic versioning.

## [Unreleased]

### Added
- **The local worker** (`body_local_worker`): summarise / extract / redact / key /
  classify text with a model running on the user's own machine — Ollama (loopback
  only) or a GGUF through `llama-cpp-python`. Nothing is downloaded automatically
  and there is **no remote fallback**: without a local model the tool refuses and
  says what to install.
- **Private content** (`privacy_session_start(keep_content_local=True)`): the page
  text is redacted and summarised locally; the snapshot returns a summary and
  `text: null`. Without a local model the text is **withheld** instead of being
  sent to the model provider. `body_privacy_preflight()` reports whether this is
  possible on the machine.
- **The model catalogue** (`body_local_models`): 11 measured models across two
  runtimes (Ollama + llama.cpp) with exact byte sizes and SHA-256, per-machine
  ranking against the *measured* free RAM, and an explicit "does not fit" verdict
  with the exact shortfall.
- **VPN control** (`privacy_vpn_connect`): opens Proton VPN, asks the app itself
  to connect (exact button name only) and reports the state read from the app's
  window (`connected` / `not connected` / `unknown`). Denied by default — the
  user enables `vpn_control` in their own profile.

### Fixed
- **The body could not see without OCR.** `eyes_see_desktop(as_image=True)` bailed
  out when no OCR engine was installed and *threw the screenshot away* — the body
  was blind even to a vision-capable model. The image is now attached regardless;
  only the text needs OCR.
- `desktop_watch_start` refused to start without an OCR engine. It now takes
  `ocr=False` for an image-only session (frames captured and compared, nothing
  recognised).
- `body_status` claimed `vpn_control` was "not_implemented" and hid the local
  worker. Both are now reported truthfully.
- `desktop_click`, `desktop_type` and `browser_bridge` used a permission *check*
  that could never consume a scoped approval, so they were unusable under the
  default profile. They now use `authorize()` and return the `required_action`
  spec, so the documented "reflex_ask → retry" flow actually works.
- `research_video` reported a rate-limited page as FAILED; a 403/429 is now
  BLOCKED, as the state table says.
- The clean-install check installed whatever wheel was lying in `dist/` - it proved
  nothing about the current code (74 tools instead of 78). It now builds the wheel
  from the current source first.
- `models.verify()` returned `ok: true` for a file with the wrong size or hash
  (the dict spread overwrote the failure flag).
- The model ranking could put a model that did not fit the machine first; models
  that fit are now always ranked above models that do not.
- The Dolphin rows claimed an Apache-2.0 licence; the base weights are under
  Meta's Llama Community Licence.

### Added (continued)
- `body_local_worker(task="describe", image=...)`: a **local** vision model
  describes a screenshot so a text-only brain can act on it. It refuses when no
  local vision model is installed — a text-only model would invent a caption.
- `demo_learn` now accepts a **folder of images** (the tool used to suggest
  "hand over the frames" without supporting it) and can read a frame with a local
  vision model when Tesseract is missing.
- `python -m body_mcp.doctor` now lists every missing piece as copy-pasteable
  commands ("Next steps") and reports the local-worker state.

### Docs
- `docs/privacy-mode.md` (new): private browsing vs private content, the local
  worker, the VPN, and what the private mode will never do.
- `docs/local-models.md`: both runtimes, the tiers, the verified digests, and how
  a local vision model becomes the eyes of a text-only brain.
- `docs/perception.md`: the three image gates that used to make the body blind.
- `THIRD_PARTY_NOTICES.md`: the model licences (Gemma terms, Llama Community).

## [0.3.0] - 2026-11-12

### Added
- **Current-browser access**: `attach_browser` / `list_tabs` / `select_tab` /
  `detach_browser` over a loopback CDP connection, plus the **extension bridge**
  (`browser_bridge`) that drives the user's own browser through a one-click,
  narrowly permissioned extension (Chrome native messaging, token + origin checked).
- **Live desktop observation**: `desktop_watch_start/read/stop` - frames are hashed and
  only changed frames are OCR'd; OCR runs off the event loop; the sampling interval grows
  under memory pressure.
- **Pluggable OCR**: Tesseract (default) and RapidOCR (optional), with real discovery
  (env var, bundled engine, PATH, platform locations).
- **Vision mode**: `eyes_see_browser(screenshot=True)`, `eyes_see_desktop(as_image=True)`,
  `desktop_watch_read(as_image=True)` attach one downscaled image (max 1280 px, 900 KB cap).
- **Human-like hearing**: `ears_listen` records until the speaker stops (end-of-speech
  detection), reports silence as silence, and flags low-confidence fragments.
- **Native desktop control**: `desktop_inspect` / `desktop_click` / `desktop_type` /
  `desktop_read_value` drive real Windows apps through UI Automation (by control name).
- **Research engine**: per-source connectors (Hacker News, Reddit, GitHub issues,
  Stack Overflow, Wikipedia, YouTube) with a capability registry, a fallback chain
  (API -> public page -> next source), rate limiting and honest refusals.
- **Video evidence**: `research_video` (metadata, chapters, official caption tracks) and
  `research_youtube_search` (reference videos).
- **Interview**: `reflex_interview` (structured multi-question elicitation) with a
  standard question set (budget, category, pain points, light/heavy, must-haves).
- **Workflow ledger**: `body_workflow_start/note/report` records
  EYES -> BRAIN -> HANDS -> VERIFY as evidence.
- **Skills**: `body_skill_save/list/replay` store a verified, replayable procedure;
  `body_similarity_check` keeps adapted output genuinely new.
- **Lessons**: `body_lessons` - every failure leaves a proposed lesson with a fix.
- **Background work**: `body_task_start/status/cancel` runs long batches off the call.
- **Undo**: `body_undo` / `body_undo_list` restore typed values and navigations.
- **Roles**: `body_roles` / `body_role_start` / `body_role_finish` - the team as contracts
  with budgets; `body_stop_all` is the emergency stop.
- **Diagnostics**: `python -m body_mcp.doctor` (read-only), `python -m body_mcp.cdp_launch
  --status/--stop/--cleanup`, `scripts/acceptance*.py`, `scripts/campaign.py`,
  `scripts/build_release.py`, `scripts/measure.py`, `scripts/research_live.py`.
- **Docs**: `docs/architecture.md`, `docs/safety.md`, `docs/perception.md`, `docs/ocr.md`,
  `docs/desktop.md`, `docs/extension-bridge.md`, `docs/workflow.md`,
  `docs/research-and-interview.md`, `docs/automation.md`, `docs/release.md`,
  `docs/opencode.md`, `examples/test_prompt.md`.

### Changed
- Approvals are now **scoped**: bound to tool, capability, target, url and task id,
  single-use, 300 s TTL, consumed atomically at execution time.
- References are **epoch-scoped** (`btn_1#7`): a ref from an older scan is refused
  instead of retargeting a different element.
- Results carry **verification states** (CONFIRMED / UNCONFIRMED / PARTIAL / FAILED /
  BLOCKED / CANCELLED) with evidence and recovery advice.
- Desktop capture uses `mss.MSS`; the OCR engine is invoked directly (no pytesseract
  dependency in the hot path).
- Core install is now just `mcp` + `playwright`; OCR, voice and the fast whisper
  models are optional extras.
- The test suite shares one event loop (Playwright's driver is closed properly):
  no more "unclosed transport" warnings, and the suite is ~4x faster.

### Fixed
- Reusing a task id cleared its cancellation request (DEF-001).
- The activity console never showed the attached tab - an un-awaited coroutine (DEF-002).
- `body_status` imported heavy optional packages, costing ~3 s per call (DEF-003).
- The model registry spawned three node CLIs per call (DEF-004).
- `file://` paths containing spaces compared as different URLs (DEF-005).
- The QA campaign could not label a mock-only result (DEF-006).
- A fixed CDP profile caused silent browser reuse (DEF-007).
- `netstat` did not show the DevTools listener, so the loopback check read "no
  listeners" (DEF-008).
- The shared test event loop leaked into background threads (DEF-009).
- The real-browser tests were skipped unless an env var was set (DEF-010).
- The system profile imported heavy packages, stalling the live-session sampler (DEF-011).
- `research_any` shadowed the `sources` module with its own parameter (DEF-012).

### Not yet verified
- Desktop OCR (no Tesseract on the build machine), live speech-to-text (no model),
  video caption retrieval (the public endpoint needs a proof-of-origin token),
  the extension inside a real browser (needs the user's one-click load),
  macOS and Linux execution.
