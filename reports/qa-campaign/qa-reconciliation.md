# QA reconciliation — independent verification of the campaign report

**Date:** 2026-11-11 (updated after the OCR/live-screen work and the warning fix)
**Verified by:** a separate pass over the raw artefacts (no test was re-run unless it was
needed to settle a material question)
**Inputs:** `reports/qa-campaign/test-report.md`, `test-matrix.csv` (current) and
`test-matrix-original-2026-11-10.csv` (the CSV as it was during the original campaign),
`defects.md`, `environment-report.md`, `scripts/campaign.py`, `scripts/acceptance.py`,
`scripts/verify_opencode_runtime.py`, `scripts/cdp_security_check.py`

## 1. Why the numbers did not add up (and what the truth is)

The original `test-report.md` stated **150 executions** but its status table added up to
**153** (144 + 3 + 3 + 3). Parsing the original CSV shows why:

| Original matrix (raw rows) | Count |
|---|---|
| execution records | **150** |
| unique scenarios | **50** (each executed exactly 3×) |
| PASS_REAL | 144 |
| PASS_MOCK_ONLY | **0** |
| BLOCKED | 3 |
| NOT_RUN | 3 |
| test_type `real` | 150 |

The 3 executions that the report called "PASS_MOCK_ONLY" (scenario **VOI-04**, the
synthetic-silence check) were **recorded in the CSV as PASS_REAL / test_type=real**, because
`campaign.py`'s helper could only emit `PASS_REAL` or `FAIL`. The report then counted those
same three rows twice: once inside the 144 and again as a separate "3 PASS_MOCK_ONLY".

**Corrected status of the original run (2026-11-10):**
141 real + 3 mock-only + 3 blocked + 3 not-run = **150 executions** (not 153).

### DEF-006 — the campaign could not label a mock-only execution (fixed)

* `scripts/campaign.py::check()` gained an explicit `status=` parameter.
* VOI-04 is now recorded as `PASS_MOCK_ONLY` / `test_type=mock_only`.
* The campaign was re-run (3 runs) and the **corrected** matrix written to
  `test-matrix.csv`; the original file is preserved verbatim as
  `test-matrix-original-2026-11-10.csv`.

### Corrected matrix (2026-11-11, re-run)

| Metric | Value |
|---|---|
| execution records | **165** |
| unique scenarios | **55** (each executed exactly 3×) |
| runs per scenario | 3 for every scenario (no scenario under- or over-executed) |
| PASS_REAL | 153 |
| PASS_MOCK_ONLY | 3 |
| PASS_LOCAL_INTEGRATION | 0 |
| FAIL | **0** |
| BLOCKED | 6 (desktop OCR × 3, live-screen session without an engine × 3) |
| NOT_RUN | 3 (live microphone × 3) |
| duplicate rows | 0 |
| rows without an `actual_result` | 0 |
| feature areas | 18 |

The five scenarios added after the first campaign are the new capabilities: `DES-01`
(real screen capture, PASS_REAL), `OCR-01` (engine discovery is honest, PASS_REAL),
`OCR-02` (live observation session - **BLOCKED**, because no OCR engine is installed, which
is the correct behaviour: a watch session without an engine has nothing to report),
`VIS-01` (a page delivered as text **and** an image through a real MCP client, PASS_REAL)
and `VIS-02` (an empty image is refused, not shipped, PASS_REAL).

**Counting method:** one CSV row = one execution of one scenario in one run. A scenario is
identified by `test_id`; `run_number` distinguishes the three repetitions. Nothing is
inferred from the printed summary — `scripts/reconcile_matrix.py` parses the file and prints
the distribution, the per-scenario status breakdown, duplicate detection and run-number
checks. The campaign's own summary line is compared against the parse.

## 2. Feature-by-feature reconciliation (original vs corrected)

| Feature area | Original claim | Corrected (raw rows) | Note |
|---|---|---|---|
| MCP protocol | 21 | 21 (7 scenarios × 3) | unchanged |
| Security | 18 | 18 (6 scenarios × 3) | unchanged |
| Batch | 12 | 12 (4 × 3) | unchanged |
| Permissions | 12 | 12 (4 × 3) | unchanged |
| Console | 12 | 12 (4 × 3) | unchanged |
| Eyes + Hands | 18 | 18 (6 × 3) | unchanged |
| Memory | 9 | 9 (3 × 3) | unchanged |
| Voice out | 6 | 6 (2 × 3) | unchanged |
| Voice in | 6 | 6 (2 × 3) | **3 of these are mock-only (VOI-04) and 3 are NOT_RUN (VOI-03)** |
| Current browser | 6 | 6 (2 × 3) | unchanged |
| Parallel | 6 | 6 (2 × 3) | unchanged |
| Recovery | 6 | 6 (2 × 3) | unchanged |
| System | 6 | 6 (2 × 3) | unchanged |
| Events / Research / Privacy | 3 each | 3 each | unchanged |
| Desktop (OCR) | 3 | 3 | all BLOCKED |
| **Total** | **144 + 3 + 3 + 3 = 153 (wrong)** | **141 + 3 + 3 + 3 = 150 (correct)** | |

The original report's per-feature numbers were individually right; only the global split
double-counted the three mock-only rows.

## 3. Evidence: what was re-verified now vs what is historical

| Claim | Status | How |
|---|---|---|
| 50 scenarios × 3 runs, 0 failures | **re-verified** | campaign re-run on 2026-11-11 → 150 rows, 0 FAIL |
| MCP handshake/tool discovery (38 tools) | **re-verified** | `scripts/verify_opencode_runtime.py` (real subprocess) |
| OpenCode runtime = current code | **re-verified** (see §4) | same script |
| CDP security (loopback, disposable profile, owned cleanup) | **re-verified** (see §5) | `scripts/cdp_security_check.py` → 7/7 PASS_REAL |
| Approval scoping / deny-wins / replay refusal | re-verified | campaign PERM-01…04 (3 runs each) |
| Batch / parallel / restriction handling | re-verified | campaign BAT-*, PAR-*, SEC-02 |
| Desktop OCR | **still BLOCKED** | Tesseract absent (re-confirmed) |
| Live microphone STT | **still NOT_RUN** | consent not given, Whisper model absent |
| Baseline "69 passed" at session start | **historical** | from the session log, not re-run |
| Per-test durations in the original CSV | **historical** | the corrected CSV has fresh durations |

## 4. The real OpenCode runtime (verified now)

Read from `~/.config/opencode/opencode.jsonc` (the `body-dev` entry, untouched by this work):

```
command: ["D:\\Projects\\body parts of agents\\.venv\\Scripts\\python.exe", "-m", "body_mcp.server"]
```

| Item | Verified value |
|---|---|
| executable | `D:\Projects\body parts of agents\.venv\Scripts\python.exe` |
| module loaded | `D:\projects\body parts of agents\src\body_mcp\__init__.py` (editable install → the live source tree) |
| version reported by `body_status` | **0.3.0** |
| tools discovered over stdio | **38** |
| handshake | OK, 2.8–5.9 s (includes the MCP SDK import) |
| `body_profile` over the same channel | python 3.14.7, 4 cores, ~497 MB RAM free |

**Root cause of the "0.1.0 vs 0.3.0" worry:** the *global* interpreter
(`C:\Users\shash\AppData\Local\Programs\Python\Python314`) has an **editable** install of
body-mcp pointing at `C:\Users\shash\body-mcp`; its recorded distribution metadata still
says **0.1.0** because the version was bumped in `pyproject.toml` after the last
`pip install -e .`. The code that runs is current in both cases — only the metadata string
is stale. Fix: run `pip install -e .` once in each environment you actually use (no
download, metadata only). Nothing in the OpenCode configuration was modified.

## 5. CDP security findings (verified now, 7/7 PASS_REAL)

| Check | Result |
|---|---|
| disposable profile by default | PASS — `…\.config\body_mcp\cdp-profile\p<port>-<ts>` (unique per launch) |
| debug endpoint reachable on loopback | PASS — `http://127.0.0.1:<port>/json/version` |
| bound address | PASS — `Get-NetTCPConnection` reports **127.0.0.1** only |
| profile in use | PASS — the disposable one, never the personal Chrome profile |
| unauthenticated endpoint | PASS (documented trust boundary, not a pass of security) |
| `--status` | PASS — reports the open port and states that it is unauthenticated |
| `--stop` | PASS — the port stops answering; browser processes that were ours are killed |

### Findings and hardening applied during this verification

1. **Fixed profile reuse (real defect).** The launcher used one fixed profile directory, so a
   second launch silently attached to the browser that was already running with it and the
   new debug port never opened. The profile directory is now unique per launch.
2. **Explicit loopback binding.** `--remote-debugging-address=127.0.0.1` is now passed, and
   the bound address is verified with `Get-NetTCPConnection`.
3. **Owned-process cleanup.** `--stop` now finds every process whose command line contains
   *our* profile directory (Windows may hand the browser over to a child process), kills
   them (taskkill plus a WMI `Terminate` fallback for orphans) and deletes the profile
   directory. Your own browser is never touched.
4. **Status command.** `--status` shows whether a debug port is open, on which address, and
   which process owns it.

### Remaining trust boundary (unchanged, and honest)

Binding to 127.0.0.1 is **not** authentication: **any process running as any local user can
drive that browser while the port is open.** The mitigations are (a) the port only exists
while you started the debug browser, (b) it uses a disposable profile by default, so no
personal session/cookies are exposed, (c) `--stop` closes it again, and (d) `--status` tells
you when it is open. Do not open the port on a shared or untrusted machine, and do not use
`--user-data-dir <your personal profile>` on one.

## 6. Defect ledger after this verification

| ID | Severity | State |
|---|---|---|
| DEF-001 task-id reuse wiped the cancel flag | Medium | fixed + regression test |
| DEF-002 console never showed the attached tab (unawaited coroutine) | Medium | fixed |
| DEF-003 `body_status` imported heavy packages (3.2 s per call) | Low | fixed (~250 ms) |
| DEF-004 model registry spawned 3 node CLIs per call | Low | fixed |
| DEF-005 `file://` paths with spaces compared unequal | Low | fixed |
| DEF-006 campaign could not label a mock-only execution | Low | fixed + matrix regenerated |
| DEF-007 fixed CDP profile caused silent browser reuse | Medium | fixed (unique profile per launch) |
| DEF-008 `netstat` did not show the DevTools listener → false "no listeners" | Low | fixed (`Get-NetTCPConnection`) |
| DEF-009 the suite opened a new event loop per test → Playwright's driver was left unclosed (12 warnings) and Chromium was relaunched 154 times | Medium | fixed (one session-scoped loop): **154 passed → 156 passed, 0 skipped, 0 warnings, 276 s → 138 s** |
| DEF-010 the two real-browser tests were skipped unless an env var was set | Low | fixed — they now run automatically when Chrome/Edge is installed |
| DEF-011 `sysprofile.collect()` imported heavy optional packages (faster-whisper, playwright) on every call, which blocked the live-session sampler | Medium | fixed (`find_spec` instead of importing) |
| DEF-012 the eyes could not hand the model any pixels at all | Medium (capability gap) | fixed — **vision mode**: `eyes_see_browser(screenshot=True)`, `eyes_see_desktop(as_image=True)`, `desktop_watch_read(as_image=True)` deliver one downscaled image (max 1280 px, ≤900 KB JPEG) as an extra MCP content block next to the structured text; verified through a real MCP client (20 471-byte JPEG at 1280×720) |
| DEF-013 the microphone always burned the full recording window, so a short answer cost 8 s of silence and silence could be transcribed into invented words | Medium | fixed — **end-of-speech detection**: recording stops ~700 ms after the user stops talking, silence is reported as silence, and low-confidence fragments are flagged for confirmation |

## 7. Confirmed vs unverified capabilities

**Verified against the real component in this pass:** MCP handshake/discovery/errors/clean
stdout; OpenCode runtime version + source path; CDP attach security (loopback binding,
disposable profile, owned cleanup, unauthenticated-endpoint disclosure); approval scoping;
batch/parallel/restriction behaviour; console token/Host/Origin checks; memory persistence
across processes; research evidence + dedupe; privacy-session cleanup; local TTS synthesis
and playback stop.

**Not verified (and not claimed):** desktop OCR (Tesseract absent); live microphone
transcription (no consent, no model); macOS/Linux behaviour; live-web workflows.

**Confirmed by a human, not by the machine:** the local text-to-speech output is audible.
The machine could only prove that audio was synthesised and that playback started; the user
confirmed hearing it ("I can hear the voice saying hello"). Read-aloud is therefore
reported as *machine-verified + human-confirmed* rather than "unverified".

## 8. Commands executed during this verification

```powershell
python scripts\reconcile_matrix.py reports\qa-campaign\test-matrix.csv
python scripts\reconcile_matrix.py reports\qa-campaign\test-matrix-original-2026-11-10.csv
python scripts\campaign.py --runs 3 --out reports\qa-campaign      # regenerated matrix
python scripts\verify_opencode_runtime.py
python scripts\cdp_security_check.py
python -m ruff check .
python -m pytest -q
```

## 9. Verdict

**PASS WITH LIMITATIONS.** The campaign's *totals* were wrong by 3 (153 claimed vs 150
executed) because a mock-only result was double-counted; the underlying executions were real
and are now labelled correctly. The OpenCode runtime loads the current code (0.3.0, 38
tools) — no stale runtime. The CDP path is hardened and its security properties are now
verified rather than asserted. Two capabilities remain unverified because a dependency or a
permission is missing, not because code is missing.

No historical evidence was rewritten: the original matrix is preserved as
`test-matrix-original-2026-11-10.csv`, and `test-report.md` keeps its original numbers with
a correction notice pointing here.
