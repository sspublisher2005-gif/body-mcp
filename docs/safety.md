# Safety model — Body-MCP v0.3

Body-MCP's reflexes exist to protect you from the agent, and the agent from acting blindly. This document describes exactly what is enforced in **code** (not just advised for the brain).

## Enforced in code (tested)

| Control | Enforcement point | Proof |
|---|---|---|
| Sensitive fields never typed (password/OTP/card) | `hands_type`, batch resolver, parallel resolver, `safety.is_sensitive_field` | tests: batch pw refusal, parallel pw refusal |
| Sensitive values masked in page observations | `eyes_see_browser` / snapshot builders | `value: "***"` when sensitive |
| Dangerous clicks (`pay`/`delete`/`send`/…) need **fresh** `reflex_ask` approval; one approval = one click | `hands_click`, `hands.py`, batch engine; approval consumed **before** the click, atomically | tests: approved-then-click, second identical click refused |
| Approvals are **scoped** (tool, capability, target, url, task) and single-use; replay/cross-task/cross-target refused | `approvals.py` (`ApprovalStore`), `permissions.authorize` | `tests/test_approvals.py` (9 tests: single use, expiry, cross-task, cross-target, 8-way concurrent consume grants exactly once) |
| `check()` never consumes an approval — only the executor does | `permissions.check` vs `permissions.authorize` | test_permission_check_never_consumes_an_approval |
| Batched dangerous actions never ride on one approval; per-step approval | batch engine gate + sig dedup | test: second identical consequential step blocked |
| Non-idempotent/duplicate consequential submissions refused | batch executor | test: duplicate_submission_refused |
| CAPTCHA / 429 / 403 / paywall → automation stops | `hands_open`, `hands_click/type/press/scroll`, batch goto, `restrictions.py` | localhost fixtures 429/403/challenge |
| Rate-limit cooldowns shared across workers; `Retry-After` honored | `restrictions` registry + batch/parallel pre-checks | test: second call pre-empted; counter stays 1 |
| Login/paywall/verification walls → manual completion only | restriction classification; resume requires cleared page | test: challenge → needs_user → clear → resume completes |
| credential-embedded URLs refused; `file://` limited to CWD; schemes limited to http/https/file | `browser.check_url` | test_safety |
| Prompt-injection pages confer no permissions; page text is data | permission layer only; no code path grants perms from content | test_injection |
| Audit JSONL with redacted targets, result state and error code (no secrets/query strings) | `permissions.record_audit`, `redact_target`, `_summarize_evidence` | test_permissions audit + redaction; test_truthfulness audit records |
| Audit log is bounded (2 MB default, one rotation) and stays local | `permissions._rotate_audit_if_needed` | `BODY_MCP_AUDIT_MAX_BYTES` |
| Permission revocation is immediate | profile re-read per call | test: deny flip under same process |
| Consent required for protected actions; fail-closed without it | `permissions.check` consent gate | tests: needs_consent blocked |
| `deny` beats fresh approval (user deny wins) | `permissions.authorize` | test_deny_beats_fresh_approval |
| App launch: allowlist + approval; name injection blocked | `legs.open_app` | tests incl. path injection |
| Current-browser attach: loopback-only endpoint, own approval for attach and for tab selection, DevTools windows excluded, unselected tabs never touched, detach closes only our session | `attach.py` | `tests/test_attach.py` (7 tests) + `tests/test_attach_real.py` (real Chrome, headless and headed) |
| Refs expire on navigation **and** on re-scan (epoch-scoped ref tokens) | `browser._bump_navigation`, `snapshot_page`, `browser.ref_is_known` | test: a ref from an earlier snapshot is refused as stale instead of retargeting |
| No result is reported as done without a postcondition | `hands_type` (reads the value back), `hands_click` (navigation check), `batch` (verification block) | `tests/test_truthfulness.py` (10 tests) |
| Checkpoints distinguish the last **verified** step from steps that merely ran | `checkpoint.create(attempted_unverified=...)`, `batch._make_checkpoint` | test_checkpoint_separates_verified_from_attempted |

## Enforcement status: NOT built / not verified

- Desktop OCR: mock-tested only; Tesseract absent on this machine.
- Microphone/Whisper: mock-tested only.
- Live sites: no network-based test coverage (by design: tests use fixtures/localhost).
- VPN control, shell, local files, downloads/uploads, TTS: **no tool exists**; policy-reserved `deny`; nothing can invoke them.
- Windows message-box fallback of `reflex_ask`: real on your desktop; elicitation path is used when the client supports it.

## Verification evidence standard

A tool action returning without exception is **not** success.

Single tools report `data.verification.status`:

| Status | When |
|---|---|
| `CONFIRMED` | `hands_open`: landed on the requested URL. `hands_type`: the field value was read back and matches. `hands_click`: the page navigated. |
| `UNCONFIRMED` | The action was dispatched but nothing observable proved the effect (e.g. a click that did not navigate) — the agent must call `reflex_verify()`. |
| `FAILED` | The postcondition failed (`POSTCONDITION_FAILED`: the field did not keep the text). |

`hands_batch` outcomes: `completed` | `failed` | `blocked` | `needs_user` | `retry_scheduled`,
plus a `verification` block: `CONFIRMED` (a verify step passed) or `UNVERIFIED` (no verify
step ran — the batch says so in its message instead of claiming success).

## Threat covered → countermeasure

| Threat | Countermeasure | Where |
|---|---|---|
| Agent reads/types passwords, OTPs, card data | Sensitive-field typing **refused**; sensitive values masked in eyes output | `hands.py`, `safety.is_sensitive_field`, `browser.py` |
| Agent clicks Pay/Delete/Send/Publish without asking | Dangerous-label click refused without a fresh **scoped** `reflex_ask()` approval; the approval is consumed atomically at execution time and cannot be replayed or reused for another target/task | `safety.is_dangerous_label`, `approvals.py`, `hands.py`, `reflex.py` |
| Agent pushing through CAPTCHA/rate-limit/paywall/login walls | Restriction scan after every page load and before every `hands_*` action; `eyes_see_browser` prefixes `STOP`; user must complete the step manually | `safety.RESTRICTION_PATTERNS`, `browser.py`, `hands.py`, `server.py` |
| Credential theft via URLs | `check_url()` refuses `user:pass@host` and non-http(s)/file schemes; `file://` limited to the working directory | `browser.check_url` |
| Overbroad filesystem browsing | Only `file://` under CWD + MCP client's normal tools | `browser.check_url` |
| Raw audio/images leaking | Audio processed in RAM, zeroed before return, never written; screenshots in RAM only | `ears.py`, `eyes.py` |
| Secrets in memory | No env/API keys exist; `.env` is local, git-ignored, and only ever read for BRAIN settings (whisper model, browser mode, delay) | `config.py`, `.gitignore` |
| Prompt injection via page text | Page text is returned as **data**; dangerous actions still need human approval; restriction/sensitive pages flip the mode block | `safety.py`, all action tools |
| A page or model output forging an approval | Approvals are minted only inside `reflex.ask()` after the human answers; the store holds a hash of the action spec, and nothing else can write to it | `approvals.py`, `reflex.py` |
| Another task reusing this task's approval | The task id is part of the approval key; a mismatch fails closed | `approvals.normalize_action`, `tests/test_approvals.py` |
| A local attacker driving the user's browser through the debug port | The port is only opened by an explicit user command and is loopback-only; `body doctor` warns while it is open; `detach_browser()` closes our session | `cdp_launch.py`, `attach.py`, `doctor.py` |
| Runaway retries / blind clicking | Brain-side rule (AGENTS.md): 3 retries max, `reflex_verify` after every action | `AGENTS.md` |

## Enforcement status: NOT built / not verified

- Desktop OCR: mock-tested only; Tesseract absent on this machine.
- Microphone/Whisper: mock-tested only.
- Live sites: no network-based test coverage (by design: tests use fixtures/localhost).
- VPN control, shell, local files, downloads/uploads, TTS: **no tool exists**; policy-reserved `deny`; nothing can invoke them.
- Windows message-box fallback of `reflex_ask`: real on your desktop; elicitation path is used when the client supports it.

## Verification evidence standard

A tool action returning without exception is **not** success. `hands_batch` outcomes:
`completed` (all steps + verifications passed) | `failed` (step failed + reason) | `blocked` (safety stop) | `needs_user` (human action required: CAPTCHA/login/approval) | `retry_scheduled` (rate limit). No outcome is reported `completed` without verification evidence (`evidence.last_verify.found == true`).

## Threat covered → countermeasure

| Threat | Countermeasure | Where |
|---|---|---|
| Agent reads/types passwords, OTPs, card data | Sensitive-field typing **refused**; sensitive values masked in eyes output | `hands.py`, `safety.is_sensitive_field`, `browser.py` |
| Agent clicks Pay/Delete/Send/Publish without asking | Dangerous-label click refused without a **fresh** `reflex_ask()` approval (5-min TTL, one click consumed) | `safety.is_dangerous_label`, `browser._approval`, `hands.py`, `reflex.py` |
| Agent pushing through CAPTCHA/rate-limit/paywall/login walls | Restriction scan after every page load and before every `hands_*` action; `eyes_see_browser` prefixes `STOP`; user must complete the step manually | `safety.RESTRICTION_PATTERNS`, `browser.py`, `hands.py`, `server.py` |
| Credential theft via URLs | `check_url()` refuses `user:pass@host` and non-http(s)/file schemes; `file://` limited to the working directory | `browser.check_url` |
| Overbroad filesystem browsing | Only `file://` under CWD + MCP client's normal tools | `browser.check_url` |
| Raw audio/images leaking | Audio processed in RAM, zeroed before return, never written; screenshots in RAM only | `ears.py`, `eyes.py` |
| Secrets in memory | No env/API keys exist; `.env` is local, git-ignored, and only ever read for BRAIN settings (whisper model, browser mode, delay) | `config.py`, `.gitignore` |
| Prompt injection via page text | Page text is returned as **data**; dangerous actions still need human approval; restriction/sensitive pages flip the mode block | `safety.py`, all action tools |
| Runaway retries / blind clicking | Brain-side rule (AGENTS.md): 3 retries max, `reflex_verify` after every action | `AGENTS.md` |

## What Body-MCP will never do

Not now, not "temporarily", not "just this once":

1. Solve, click through, or otherwise respond to CAPTCHAs or human-verification challenges.
2. Bypass logins or any authentication — the human authenticates, always.
3. Evade bot detection, IP limits, rate limits, or paywalls — including proxies, rotating user agents, or fake fingerprints.
4. Store, print, transmit, or retain passwords, OTPs, card data, recovery codes, or auth cookies.
5. Continue acting on a page showing an access restriction.

## Reflexes in detail

**Sensitive mode** (password/OTP/payment/login patterns in visible text):
- `eyes_see_browser` flags the page and tells the brain not to read or type sensitive fields.
- `hands_type` refuses fields whose type/name/autocomplete matches card/password/OTP patterns.
- Fields are always returned masked (`***`).

**Restricted mode** (captcha/unusual-traffic/429/paywall/… patterns):
- All `hands_*` actions return a refusal with instructions to stop.
- `hands_open` refuses the page.
- Recovery requires the human to complete the gate manually, then the brain re-scans.

**Dangerous-button approval** (`pay`, `buy`, `delete`, `send`, `post`, `publish`, `confirm`, `download`, `transfer`, `submit`):
- `hands_click` requires a fresh `reflex_ask()` approval, TTL 300 s.
- The approval is bound to one action (`tool | capability | target | url | task_id`), consumed
  atomically when the action executes, and unusable for a different target, task or page.

## Reporting a safety failure

If any of these stops working (e.g. a page slips through that should have flipped a mode), treat it as a security bug: open an issue without posting secrets, page content that includes personal data, or reproduction pages containing credentials.
