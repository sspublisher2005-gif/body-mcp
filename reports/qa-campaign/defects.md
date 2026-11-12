# Defects found in the Body-MCP QA campaign

Every defect below was reproduced, fixed in the shared enforcement/execution path, covered by
a regression test and re-verified (3 campaign runs + the full pytest suite).

---

## DEF-001 — Reusing a task id cleared its cancellation, so a cancelled task still ran

* **Severity / priority:** Medium (reliability + user control — "stop" did not stop)
* **Component:** `src/body_mcp/runtime.py`, `src/body_mcp/batch.py`
* **Reproduction:**
  1. `runtime.registry.request_cancel("cancel-me")` while the task is not running yet, or
     cancel a task and re-run it with the same `task_id`.
  2. `hands_batch([...], task_id="cancel-me")`.
  3. Observed: `data.status == "completed"`, `data.verification.status == "UNVERIFIED"` —
     the batch ran to the end although the user had asked for cancellation.
* **Expected:** the executor sees the pending cancellation, stops at the first step boundary
  and reports `status == "cancelled"`, `verification.status == "CANCELLED"`.
* **Root cause:** `TaskRegistry.create()` overwrote the whole task record when a task id was
  reused, resetting `cancel_requested` to `False`. `request_cancel()` also dropped a cancel
  request for a task id that did not exist yet.
* **Fix:** `create()` now updates an existing task in place and preserves its cancellation
  flag; `request_cancel()` records a pending cancellation for an unknown task id.
* **Regression test:** `tests/test_task_lifecycle.py::test_cancelled_batch_reports_cancelled_not_completed`
  and `::test_reusing_a_task_id_keeps_the_cancel_request`.
* **Post-fix verification:** campaign REC-02 changed from `FAIL (status=completed)` to
  `PASS_REAL` in all three runs.

---

## DEF-002 — The console never showed the attached tab (unawaited coroutine)

* **Severity / priority:** Medium (the activity view lied about the browser state)
* **Component:** `src/body_mcp/attach.py`, `src/body_mcp/console.py`
* **Reproduction:** start the console, attach to a browser tab, read `/api/state`.
  Observed: `"attached_tab": null` plus a `RuntimeWarning: coroutine 'attached_status' was
  never awaited` in the test output.
* **Expected:** the console reports the attached tab's title and URL.
* **Root cause:** `attach.attached_status()` was declared `async` although it never awaited
  anything; the console called it synchronously, so the coroutine was created and discarded.
* **Fix:** `attached_status()` and `status_text()` are now plain functions; every caller
  (`console.py`, `doctor.py`, `server.py`) was updated.
* **Regression test:** the console suite now runs warning-free and campaign CON-02 asserts a
  200 response with real state.
* **Post-fix verification:** the `RuntimeWarning` is gone from the pytest output; 144 tests
  pass with no warnings of that kind.

---

## DEF-003 — `body_status` imported heavy optional packages, costing ~3 seconds per call

* **Severity / priority:** Low (performance; also risks loading large models at start-up)
* **Component:** `src/body_mcp/server.py`, `src/body_mcp/tts.py`
* **Reproduction:** call `body_status` and time it.
  Observed: ~3.2 s per call, with `faster-whisper` (ctranslate2 + onnxruntime) imported
  just to answer "is it installed".
* **Expected:** a status call is cheap (hundreds of milliseconds) and no large module is
  imported.
* **Root cause:** `body_status` used `__import__(name)` for the optional-dependency check and
  `tts.available()` spawned a PowerShell process to list voices.
* **Fix:** `importlib.util.find_spec()` for availability, and `tts.available(quick=True)`
  for the status path (no PowerShell spawn).
* **Regression test:** `scripts/measure.py` (timing) and `tests/test_tools.py::test_body_status_reports_capabilities`.
* **Post-fix verification:** `body_status` dropped from ~3 200 ms to ~250 ms.

---

## DEF-004 — The model registry spawned three node CLIs on every call

* **Severity / priority:** Low (performance; risks a 40 s stall on a slow machine)
* **Component:** `src/body_mcp/registry.py`
* **Reproduction:** call `body_models()` / `body_recommend()` repeatedly.
  Observed: every call ran `opencode --version`, `claude --version` and `codex --version`
  (node start-up), each with an 8 s timeout.
* **Expected:** a status call returns quickly and repeatedly.
* **Root cause:** no caching and an 8 s timeout per CLI.
* **Fix:** 5 s timeout plus a 5-minute cache of the detected versions.
* **Regression test:** campaign SYS-02 (recommender) — stable runtime across the 3 runs.
* **Post-fix verification:** the campaign run time stayed at ~20 s per run.

---

## DEF-005 — `file://` URLs with spaces compared as different (percent-encoding)

* **Severity / priority:** Low (false "UNCONFIRMED" verdicts on paths with spaces)
* **Component:** `src/body_mcp/hands.py`
* **Reproduction:** open a `file://` URL whose path contains a space (e.g.
  `D:\Projects\body parts of agents\tests\fixtures\test_page.html`) and check
  `data.verification.status`.
  Observed: `UNCONFIRMED` although the requested and observed pages were identical.
* **Expected:** `CONFIRMED`.
* **Root cause:** `url_verification()` compared the raw paths; the browser reports them
  percent-encoded.
* **Fix:** both paths are unquoted before comparison.
* **Regression test:** covered by `tests/test_truthfulness.py::test_open_reports_unconfirmed_when_landed_elsewhere`
  (it failed on the D: copy with a spaced path and passes after the fix).

---

## Unresolved / not fixed (documented, not silently ignored)

* **Desktop OCR is unverified** — Tesseract is not installed. Not a code defect; the
  capability is reported as `BLOCKED` by the campaign and by `body doctor`.
* **Live microphone/STT is unverified** — needs the user's consent and the Whisper model.
  Reported as `NOT_RUN`/`BLOCKED`.
* **Audible TTS output is not machine-verifiable** — synthesis and playback start/stop are
  proven; whether a human hears it is not.
