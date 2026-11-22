# Validation report — the 7-point checklist

Every row states what was done and the proof. Nothing here is claimed without a
command output, a file, or a CI job.

| # | Checklist item | Status | Proof |
|---|---|---|---|
| 0 | Placeholder URLs and stale docs | ✅ **done** | `git grep -n 'github.com/you'` → 0 hits. `README.md`, `docs/install.md`, `pyproject.toml` use `github.com/sspublisher2005-gif/body-mcp`. Release docs and `extension/manifest.json` say 0.4.0. |
| 1 | GitHub Actions matrix, Windows + Ubuntu green | ✅ **done** | `.github/workflows/ci.yml`: explicit matrix with `fail-fast: false`, per-OS browser install, platform skip for the one real-display test. Three real CI bugs found and fixed: missing `numpy` in the dev extra (collection error on both OSes), `file:////` URL construction in a test (Ubuntu verification), and an environment-dependent `recommend()` assertion. Final run **44130022952: both `test (windows-latest)` and `test (ubuntu-latest)` = success**. |
| 2 | Two small default profiles | ✅ **done** | `src/body_mcp/profiles/browser.json` and `windows-desktop.json`; CLI `python -m body_mcp.profiles <name> --show\|--apply` (keeps a `.bak` of the previous permissions); 8 tests in `tests/test_profiles.py`. |
| 3 | Minimal installation path + reproducible demo | ✅ **done** | `docs/QUICKSTART.md` (5 commands, no optional installs) and `scripts/demo_real_task.py` (local fixture, no network). |
| 4 | One real task: inspect → act → verify | ✅ **done** | `python scripts/demo_real_task.py` output: `[EYES] title='Body-MCP Test Page'…`, `[HANDS] 'clicked via text:role=link - page navigated'`, `[VERIFY] found=True, source=file://…/fixtures/article.html`, `RESULT: CONFIRMED`. Machine-readable proof: `reports/validation/real-task-proof.json`. |
| 5 | Bridge and major integrations against real components | ⚠️ **partly done** | Found and fixed a real bug: a test wrote a **pytest temp path** into the real Chrome/Edge native-messaging registry, which would have broken the bridge for a real user. Registry re-registered to the real manifest; the native host subprocess now refuses an unknown extension id as designed. **Still needs a human click**: load `extension/` in a real browser and connect a tab. The bridge itself remains mock-tested until then. **Real-component proofs now green on GitHub runners** (run 44686643385): OCR with Tesseract, ffmpeg + OCR learning, the text worker with `qwen3:0.6b`, and `describe` with `qwen3-vl:2b`. A runner exposed and we fixed a false claim: `gemma3:270m` is text-only, not vision. |
| 6 | Invite developers / record repeat use and fixes | ✅ **done** | `CONTRIBUTING.md` has a 90-second test, six concrete workflows to choose from, what to report (including the verification state and a second-run check), and the no-install rule. `.github/ISSUE_TEMPLATE/workflow-test.yml` is a structured report form. A public invitation issue is open on GitHub. |

## Bugs found and fixed while working the checklist

1. **Placeholder URLs** in `pyproject.toml` (Homepage / Documentation / Issues) — not caught by the earlier docs-only scan.
2. **Invented capability** `public_web_private` in the browser profile — the test that compares against `DEFAULT_CAPABILITIES` caught it immediately.
3. **CI collection error**: `numpy` is imported by two test modules but was only in the `voice`/`all` extras, not `dev`.
4. **Ubuntu-only verification failure**: test fixture URLs were built as `"file:///" + absolute_path`, which is four slashes on POSIX; Playwright normalises them. Fixed once in `url_verification()` (production code) rather than at 24 call sites.
5. **Environment-dependent test**: `recommend()` was asserted to return a non-empty list, but on a clean machine the honest answer is `recommended: None`.
6. **A test corrupted the real browser configuration** (see item 5). This is the highest-value integration find: it would have made the bridge fail for a real user while all tests passed.

## Honest limits that remain

- The extension bridge, local worker, `describe`, Proton VPN, Tesseract OCR,
  faster-whisper and ffmpeg are **still unproven against their real counterparts**
  on this machine. No software or model was installed to prove them, by design
  (`docs/DECISIONS.md` D17). They are reported as mock-tested or blocked.
- Reddit / X / Instagram / YouTube captions remain blocked by platform policy
  (403 / credentials / 429), not by code.
- PyPI publication still needs the user to add a GitHub publisher on pypi.org.

## Update 2026-11-22 - auto-use, regression guard, wider CI

- **The failure you spotted is fixed:** an agent no longer has to guess among 81 tools. `body_capabilities()` is the one first call (what works here, what is blocked, WHEN to use each group), and `body_focus('browser'|'windows-desktop'|'research')` narrows `tools/list` from 81 to 30 with `notifications/tools/list_changed`; hidden tools stay callable. `SKILL.md` + `AGENTS.md` make the EYES->BRAIN->HANDS->VERIFY loop and the 'use the body, not webfetch' rule automatic.
- **The regression guard exists:** `tests/test_stdio_all_tools.py` calls 70 tools over a real MCP subprocess with a hard per-call timeout, so the #1-#3 class of bug (crashes only through the MCP layer) fails CI by name instead of hiding. Also asserts the {success,message,data} contract on bad arguments (tester #10).
- **CI widened:** 3 OSes x Python 3.11/3.12/3.13/3.14 + a separate packaging/stdio job. Run 44935676400: **13/13 jobs green**.
- Tester #12 fixed (`summarize`/`summarise` both accepted). #11 (cosmetic strings) remains open and is documented in `docs/BACKLOG.md`.
