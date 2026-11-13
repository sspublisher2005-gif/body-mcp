# Body-MCP QA campaign — test report

> **Correction notice (2026-11-11).** The status table below originally read
> "144 PASS_REAL + 3 PASS_MOCK_ONLY + 3 BLOCKED + 3 NOT_RUN", which adds up to 153 while the
> report says 150 executions. The raw CSV of that run contained **no** PASS_MOCK_ONLY rows:
> the three mock-only executions were recorded as PASS_REAL and then counted twice in the
> table. The true split of the original run is **141 real + 3 mock-only + 3 blocked +
> 3 not-run = 150**. The original matrix is preserved as
> `test-matrix-original-2026-11-10.csv`; a corrected matrix (same 50 scenarios × 3 runs)
> was produced on 2026-11-11. Full reconciliation, including the OpenCode runtime check and
> the CDP security findings: **`qa-reconciliation.md`**. The numbers below are left as the
> historical record; the correction is documented, not silently rewritten.

**Date:** 2026-11-10
**Repository:** `C:\Users\shash\body-mcp` (working tree; no commits, nothing pushed)
> **Since 2026-11-13 the canonical repository is `D:\Projects\body parts of agents`** —
> the C: copy was removed after the full tree (with its git history) was moved there
> and re-verified there (287 tests green). The path below is the historical record of
> the campaign; every other file in this report refers to that same tree.
**Machine:** Windows 11 (10.0.26300), Python 3.14.7, 4 logical cores, ~460–530 MB RAM free of 3.8 GB
**Version under test:** body-mcp 0.3.0 (`src/body_mcp/__init__.py`)
**Campaign runner:** `scripts/campaign.py` (self-contained, real components only)
**Matrix:** `reports/qa-campaign/test-matrix.csv` (150 rows = 50 scenarios × 3 runs)

## 1. Baseline before the campaign

| Check | Command | Baseline |
|---|---|---|
| Unit + integration suite | `python -m pytest -q` | **69 passed** (v0.2 baseline, before this session's changes) |
| Static checks | `python -m ruff check .` | 3 pre-existing errors in the unfinished `attach.py` |
| Working tree | `git status --short` | 41 changed files, **no commits** (nothing was committed or pushed in this session) |

Baseline failures recorded separately from new ones: the only pre-existing failures were
the three Ruff errors in `attach.py` (unused imports) — fixed in this session.

## 2. Final results

| Metric | Value |
|---|---|
| Distinct scenarios | 50 |
| Total executions | 150 (3 runs per scenario) |
| PASS_REAL | 144 |
| PASS_MOCK_ONLY | 3 |
| PASS_LOCAL_INTEGRATION | 0 |
| FAIL | 0 |
| BLOCKED | 3 (desktop OCR — Tesseract missing, one per run) |
| NOT_RUN | 3 (live microphone — needs the user's consent, one per run) |
| Scenarios repeated 3× | 50 |
| Confirmed defects | 4 (all fixed and retested) |
| pytest suite | **144 passed, 2 skipped** |
| Ruff | **All checks passed** |

### Feature coverage (18 feature areas, 50 scenarios)

| Feature area | Scenarios | Result |
|---|---|---|
| MCP protocol | 7 | PASS_REAL ×21 |
| Eyes / Hands / browser | 6 | PASS_REAL ×18 |
| Security (secrets, injection, URL policy) | 4 | PASS_REAL ×12 |
| Batch | 4 | PASS_REAL ×12 |
| Parallel | 2 | PASS_REAL ×6 |
| Recovery (crash, cancellation) | 2 | PASS_REAL ×6 (after DEF-001 fix) |
| Permissions / approvals | 5 | PASS_REAL ×15 |
| Current browser (real Chrome over CDP) | 4 | PASS_REAL ×12 |
| Console (local HTTP UI) | 4 | PASS_REAL ×12 |
| Events | 1 | PASS_REAL ×3 |
| Memory | 3 | PASS_REAL ×9 |
| Research | 1 | PASS_REAL ×3 |
| Privacy session | 1 | PASS_REAL ×3 |
| System profile / model router | 2 | PASS_REAL ×6 |
| Voice output (TTS) | 2 | PASS_REAL ×6 |
| Voice input (STT) | 2 | PASS_MOCK_ONLY ×3, NOT_RUN ×3 |
| Desktop (OCR) | 1 | BLOCKED ×3 |

## 3. Commands executed

```powershell
# baseline and final suite
python -m pytest -q
python -m ruff check .

# real-environment acceptance checks (honest per-check statuses)
python scripts/acceptance.py
python scripts/acceptance.py --allow-mic        # not run: needs consent

# the QA campaign (3 runs, writes the matrix)
python scripts/campaign.py --runs 3 --out reports/qa-campaign

# measurements
python scripts/measure.py

# diagnostics (read-only)
python -m body_mcp.doctor
python -m body_mcp.doctor --json
```

## 4. Real vs mocked vs blocked

**Real (executed against the real component):**

- MCP handshake, tool discovery, tool call, unknown-tool error, wrong-argument-type error,
  stdout cleanliness and clean shutdown — against a **real server subprocess** over stdio.
- Browser: page read, element discovery, click + verification, ambiguity refusal, stale-ref
  refusal, restricted-page stop, private read-only session, delayed-element page, and
  recovery after closing the page — against **real Chromium (Playwright)**.
- Current browser: attach → select → type → detach against **real Chrome 157 over CDP**;
  the browser kept running after detach, and a non-loopback endpoint was refused.
- Console: real HTTP requests to the loopback server — 401 without a token, 403 for a foreign
  `Host` header, 403 for a foreign `Origin`, 200 with real state.
- Memory: real SQLite + FTS5 file, read back from a **second process**.
- Research: real page retrieval with metadata and content-hash deduplication.
- Privacy session: real isolated context, cleanup verified.
- TTS: real Windows SAPI synthesis (≈124 KB WAV, 1.1–3.0 s) and a real playback start/stop.

**Mock-only (1 scenario):** silence detection in `ears.listen` — a synthetic zero buffer is
injected instead of microphone audio (the live microphone is a separate NOT_RUN case).

**Blocked (1 scenario):** desktop screenshot + OCR — Tesseract is not installed on this
machine (`winget install -e --id UB-Mannheim.TesseractOCR`).

**Not run (1 scenario):** live microphone capture + local transcription — requires the user's
explicit consent to record, and `faster-whisper` is not installed either.

## 5. Defects found and fixed in this campaign

See `defects.md` for the full record (DEF-001 … DEF-004). Summary:

| ID | Severity | Defect | Fix | Regression test |
|---|---|---|---|---|
| DEF-001 | Medium | Reusing a task id reset its cancellation flag, so a cancelled task ran to completion | `runtime.TaskRegistry.create()` now preserves the cancel request; `request_cancel()` remembers a cancel for a task that has not started yet | `tests/test_task_lifecycle.py::test_cancelled_batch_reports_cancelled_not_completed` |
| DEF-002 | Medium | `attach.attached_status()` was `async` but called without `await` from the console → the console always showed "no attached tab" and leaked a coroutine warning | made it synchronous (it never awaited anything) | `tests/test_console_events.py` (warning-free run) + campaign CON-02 |
| DEF-003 | Low | `body_status` imported heavy optional packages (faster-whisper → ctranslate2 + onnxruntime) just to answer "is it installed" → 3.2 s per status call | `importlib.util.find_spec` instead of importing; TTS check made "quick" | measured: body_status 3200 ms → ~250 ms |
| DEF-004 | Low | `registry._version()` spawned `opencode/claude/codex --version` on every call (node start-up) | 5 s timeout + 5-minute cache | campaign runtime 25 s/run → stable |

## 6. Measurements

| Measurement | Value | Method |
|---|---|---|
| Server start + initialize handshake | ~2.7–3.2 s | `scripts/measure.py` (subprocess, includes the MCP SDK import) |
| `tools/list` | +5 ms | same |
| `body_status` call | ~250 ms (was ~3.2 s before DEF-003) | same |
| Tool schemas | 38 tools, 18 349 bytes total (~482 bytes/tool) | same |
| `body_status` payload | ~3 950 bytes | same |
| TTS synthesis | 1.1–3.0 s for one sentence (124 KB WAV) | campaign VOI-01, 3 runs |
| Campaign wall time | 59 s for 150 executions (3 runs × 50 scenarios) | `scripts/campaign.py --runs 3` |
| Full pytest suite | 88 s / 144 passed | `python -m pytest -q` |
| Available RAM during the campaign | 462–529 MB | `body_profile` (GlobalMemoryStatusEx) |

**Limitations of these numbers:** the machine is a low-memory Windows laptop with a busy
desktop (the user's own Chrome plus two MCP servers were running), so timings vary by tens
of percent between runs. No latency percentiles were computed because each scenario ran
only three times.

## 7. Remaining risks and limitations

1. **Desktop OCR is untested end to end** — Tesseract is absent. The Python path is
   mock-tested only; the real pipeline is unverified.
2. **Live speech recognition is untested** — no consent was given to record, and the
   Whisper model is not downloaded. The synthetic-silence path is verified.
3. **Audible TTS output cannot be machine-verified** — the WAV is produced and playback
   starts and stops, but whether a human hears it is not proven by the machine.
4. **No live-web coverage** — every network test used local fixtures. No external site,
   search API, Reddit/X/Instagram integration exists or was tested; `research_collect` only
   fetches URLs the caller supplies.
5. **Only Windows is verified.** macOS/Linux paths exist but were not executed.
6. **The CDP debug port is unauthenticated while open.** The campaign and the real-browser
   test always used a disposable `--user-data-dir` and terminated the browser afterwards.
7. **Flaky-timing risk:** each pytest test creates its own event loop, so Chromium is
   relaunched per test (≈1.5–2 s); the suite is dominated by browser start-up, not by
   test logic.

## 8. Reproduction

```powershell
cd C:\Users\shash\body-mcp
python -m pytest -q                                   # 144 passed, 2 skipped
python -m ruff check .                                # All checks passed
python scripts/campaign.py --runs 3 --out reports\qa-campaign   # rewrites test-matrix.csv
python scripts/acceptance.py                          # real-environment summary
python -m body_mcp.doctor                             # environment report
```

The campaign writes into a **throwaway config directory** (`BODY_MCP_CONFIG_DIR`), so it
never touches the real `permissions.json`, consent marker, audit log or memory database.
