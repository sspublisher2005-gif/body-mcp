# Body-MCP Architecture (v0.3)

```
        you
         │  (speech / text)
         ▼
┌─────────────────────┐        MCP over stdio        ┌──────────────────────┐
│  coding agent        │ ◄──────────────────────────► │  Body-MCP server      │
│  (the brain:         │   38 tools, JSON results     │  (the body: no goals, │
│   planning, reasoning,│                              │   no initiative)      │
│   judgment)           │                              └─────────┬────────────┘
└─────────────────────┘                                         │
                                              ┌───────────────────┼──────────────────┐
                                              ▼                   ▼                  ▼
                                       ┌───────────┐      ┌──────────────┐   ┌────────────┐
                                       │ browser.py │      │  eyes.py     │   │  ears.py   │
                                       │ Playwright │      │  mss + OCR   │   │ sounddevice│
                                       │ + attach.py│      │  (in-memory) │   │ → whisper  │
                                       └───────────┘      └──────────────┘   └────────────┘
                                              │
                     ┌────────────────────────┼────────────────────────┐
                     ▼                        ▼                        ▼
              ┌─────────────┐        ┌──────────────┐         ┌──────────────┐
              │ permissions │        │  batch.py    │         │  events.py   │
              │ +approvals  │        │ parallel.py  │         │  runtime.py  │
              │ (one path)  │        │ checkpoint.py│         │ (activity)   │
              └─────────────┘        └──────────────┘         └──────────────┘
                     │                        │                        │
                     └────────────────────────┼────────────────────────┘
                                              ▼
                        memory.py · research.py · privacy.py · sysprofile.py
                        registry.py · tts.py · console.py · doctor.py
```

## Modules

| Module | Responsibility | Key decisions |
|---|---|---|
| `server.py` | MCP SDK v2 server, **38 tools**, `{success, message, data}` results | Tool count is read back from the MCP server, never hardcoded; blocking work via `anyio.to_thread` |
| `browser.py` | Managed Chromium page + isolated contexts | Refs resolve role+name → label → testid/id/name → text → validated XPath; ambiguity refused; **epoch-scoped refs** (`btn_1#7`) expire on navigation *and* on re-scan; contexts are per-loop (no cross-loop reuse) |
| `attach.py` | Current-browser connection over CDP | Loopback-only endpoint; own approval for attach and for tab selection; DevTools windows excluded; unselected tabs never touched; detach closes only our session |
| `cdp_launch.py` | `python -m body_mcp.cdp_launch` | User-initiated browser launch with a debug port; prints the exposure warning; never called by the server |
| `approvals.py` | Scoped, single-use, expiring approvals | Key = tool \| capability \| target \| url \| task_id; TTL 300 s; atomic consume; no global token |
| `permissions.py` | **Centralized authorization** | `check()` decides (sync), `authorize()` consumes the scoped approval (async); allow/ask/deny profile; consent gate; deny always wins; audit JSONL with redaction, result state and rotation |
| `batch.py` | Executor behind `hands_batch` | Validate-then-execute; per-step timeouts; total deadline; stop-on-failure; per-step approvals; duplicate consequential submissions refused; checkpoints separate verified from merely-attempted steps |
| `parallel.py` | `hands_parallel` | ≤2 workers default (hard max 4), isolated contexts, no refs across pages, shared cooldowns, failures not hidden |
| `checkpoint.py` | Memory-only checkpoints | Query strings stripped, fill text redacted, never persisted, TTL + capacity eviction, `attempted_unverified_steps` |
| `restrictions.py` | Restriction classification + per-service cooldown registry | 429/Retry-After, 403, CAPTCHA, paywall, auth walls; exponential backoff with jitter; shared across workers |
| `events.py` | Execution event bus | Events are produced by the executor; bounded ring buffer; redacted, short summaries; evidence references only |
| `runtime.py` | Task identity, lifecycle, cancellation | Cooperative cancellation checked between steps; task ids appear in events, audits and approvals |
| `console.py` | Optional local Body Console | `127.0.0.1` only, session token required, Host/Origin validated, fixed routes, bounded bodies; cancel + disconnect buttons |
| `memory.py` | Local persistent memory | SQLite + FTS5 (LIKE fallback), Markdown notes, scopes, versions, secret refusal, no embeddings, local only |
| `research.py` | Evidence-oriented collection | Bounded pages/text/time, dedupe by URL and content hash, blocked sources reported honestly |
| `privacy.py` | Privacy sessions | Own ephemeral context; nothing in audit/events/memory; cleanup verified on end |
| `sysprofile.py` | Read-only system inventory | CPU/RAM/disk/GPU/optional modules/agent CLIs; cached locally; never uploads, never installs |
| `registry.py` | Model & harness catalogue + dry-run recommender | Records licences, privacy, cost and real availability; installs nothing |
| `tts.py` | Optional local Read Aloud | Windows SAPI (no download, no network); playback stoppable; audio temp file deleted |
| `ears.py` | Mic → faster-whisper | Silence detected instead of inventing words; audio zeroed after use; never persisted |
| `eyes.py` | Desktop OCR (fallback) | In-memory screenshots only; tesseract discovered, never assumed |
| `legs.py` | `legs_open_app` | Allowlisted plain app names only; fresh scoped approval; Start-Process with stdin detached |
| `reflex.py` | `reflex_verify` + `reflex_ask` | Elicitation → Windows dialog → fail closed; only a yes here mints an approval |
| `safety.py` | Sensitive / restriction / dangerous-button detectors | Case-insensitive regex; auditable; no network |
| `config.py` | `.env` settings, deadlines, backoff, concurrency limits | stdlib-only parsing |
| `consent.py` / `doctor.py` | User-facing consent flow / diagnostics | Human-only acts; doctor is read-only (never changes permissions or downloads anything) |

## Data flows

**Browser research**: `hands_open` → `eyes_see_browser` → structure + refs → brain picks one action → `hands_click/type` → `reflex_verify`. The brain gets structure, refs and text — never raw screenshots from the browser path.

**Current browser**: `python -m body_mcp.cdp_launch` (user) → `attach_browser` (approval) → `list_tabs` → `select_tab` (approval) → normal eyes/hands on that tab → `detach_browser`.

**Ears**: `sounddevice` records 16 kHz mono float32 → RMS check (silence stops the flow) → `faster-whisper` (`vad_filter=True`) → audio zeroed in `finally`. Nothing persisted.

**Evidence**: `research_collect` → throwaway context → bounded extraction → evidence records (url, title, date, excerpt, method, hash, status) → the agent does the synthesis.

## Refs

Refs are assigned by document order on every `eyes_see_browser()` call: buttons → `btn_N#epoch`, inputs → `input_N#epoch`, links → `link_N#epoch`. The epoch changes on every navigation **and** every rebuild, so a ref from an older scan is refused as stale instead of silently retargeting a different element. Re-scan before acting.

## Failure model

- Optional dependency missing (tesseract, sounddevice, faster-whisper, mss, playwright): server still starts; the affected tool returns `{"success": false, "data": {"hint": "..."}}`.
- Restricted page detected: every `hands_*` refuses; `eyes_see_browser` prefixes its message with `STOP`.
- Approval missing/expired/mismatched: fail closed, the exact required spec is returned.
- Browser closed or disconnected: the tool reports it; nothing is retried blindly.
- Postcondition failed: the tool reports `FAILED` / `POSTCONDITION_FAILED` with evidence, never "done".
