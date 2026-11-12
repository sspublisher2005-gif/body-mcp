# The automation program: what Body-MCP does, and what is still blocked

This is the honest map of the master prompt against the code that exists.

## 1. Research engine (done, with a fallback chain)

| Source | API | Public page | Auth | Rate limit | Pagination | Data | ToS note | Health/fallback |
|---|---|---|---|---|---|---|---|---|
| Hacker News | ✅ Algolia | ✅ | none | polite 1/s | hits | title, points, comments, author, date | read-only | browser fallback |
| Reddit | ⚠️ JSON (403 here) | ✅ | none | anonymous | limited | title, score, comments, subreddit | no scraping of private subs | browser fallback |
| GitHub issues | ✅ REST | ✅ | none (60/h) | 10/min | per_page | title, body, comments, state | public repos | browser fallback |
| Stack Overflow | ✅ API | ✅ | none (low volume) | polite | pagesize | title, score, answers | community Q&A | browser fallback |
| Wikipedia | ✅ API | ✅ | none | polite | srlimit | title, snippet | encyclopedia | browser fallback |
| YouTube | ✅ pages | ✅ | none | polite | results | title, channel, views, age, captions | official captions only | captions via DOM |
| Any public page | ✅ | ✅ | none | polite | - | text, links, images | read-only | - |
| X / Instagram | ❌ | ⚠️ | **credentials** | - | - | - | no scraping | user's own session via the extension bridge |

`research_any()` implements the routing: try the API → if closed, read the public page in
the browser → if that fails, try the next relevant source → compare → **report what could
not be accessed** (every attempt is listed in `tried`). No CAPTCHA/login/paywall bypass, no
identity rotation, no retrying a blocked request.

## 2. Demonstration learning (pipeline done, blocked on this machine)

`demo_learn(video_path)`:

1. **frames + timestamps** — ffmpeg if installed, else OpenCV/imageio → otherwise
   **BLOCKED** with the exact missing dependency;
2. **screen text** — the OCR provider per frame → **BLOCKED** without Tesseract
   (never invented text);
3. **audio** — transcribed locally with the configured STT engine (skipped and reported
   when no model is present);
4. **steps** — consecutive frames whose text changed become ONE step (idle frames and
   mistakes are not steps); each step records the screen, the visible control names and
   the text (semantic, not coordinates);
5. **questions** — the unclear parts become targeted questions ("exact or adapted?",
   "publish or draft?", "what must stay the same?", "what if it fails?");
6. **skill draft** — saved as an unverified skill; it is never replayed until confirmed.

## 3. Skills (versioned, replayable, checkable)

`body_skill_save` / `body_skill_list` / `body_skill_replay`:

* a skill = name + goal + steps + **why** + verified flag, stored in the local memory
  (scope `workflow`, type `skill`);
* **exact replay** (`body_skill_replay`) runs the recorded steps in order, with the same
  targets, the same content, the same permission gate and the same verification - it
  never substitutes a new topic or new wording;
* an **unverified** skill is refused: the agent must check it first;
* **adapted execution** is the agent's job (new script, new caption, new topic); the body
  supports it with `body_similarity_check` - it compares the new text with what was
  produced before and says "too similar" / "new enough".

## 4. The team (roles as contracts, not separate models)

`body_roles` lists the roles; `body_role_start` opens a **contract** per role with its
tools, its permission, its budget (max actions, max seconds) and what it must produce;
`body_role_finish` closes it with the evidence. The connected agent stays the
orchestrator and the brain — it plans, decides and calls the other MCP servers.

Roles: research, source_connector, planning, workflow_learning, skill_engineering,
execution, coding, qa, security, evaluation, reporting.

`body_stop_all()` is the emergency stop: it cancels the background tasks and closes the
open contracts (it never touches your files).

## 5. Safety and limits (not negotiable)

* least privilege per capability, approval gates, audit log with redaction;
* read-only research mode; dry-run previews via `body_workflow_report`;
* reversible where practical: `body_undo` (typed values, navigation) and the skill library
  keeps working skills instead of overwriting them;
* no credential collection, no private groups, no paywall/CAPTCHA bypass;
* the browser alone cannot control your computer: the desktop path needs the installed,
  authorised local component (UI Automation), and that is what `desktop_*` uses.

## 6. Honest gaps (not code, but this machine)

| Gap | Why | Fix |
|---|---|---|
| Desktop OCR | Tesseract is not installed | `winget install -e --id UB-Mannheim.TesseractOCR` |
| Live speech-to-text | no Whisper model downloaded | `pip install -e ".[voice]"` + your consent |
| YouTube caption *fetch* | the public timedtext endpoint returns 0 bytes here (proof-of-origin token) | read the captions panel through the browser, or use the extension bridge |
| Video frame decoding | no ffmpeg/OpenCV installed | `winget install ffmpeg` (free) |
| Reddit API | HTTP 403 for anonymous access | the official API (free app) or the browser fallback |
| X / Instagram | no public API without credentials | the official APIs, or your own session via the extension |
| Publishing/scheduling on social platforms | not implemented and not authorised | the browser can drive a logged-in session **only** through the extension bridge, and always with your approval |

**No claim of guaranteed virality, growth or revenue** is made anywhere in this project.
