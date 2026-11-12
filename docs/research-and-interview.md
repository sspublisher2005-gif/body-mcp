# Research, the interview, and who owns which work

## 1. The interview (the agent's job — the body only asks)

`reflex_interview()` asks the user several questions at once and returns the answers.
The standard set (`body_mcp.interview.question_set()`):

1. **Budget** — one-off build, monthly running cost, or both?
2. **Category** — research/analysis, content, automation, an agent, a tool?
3. **What went wrong** — which coding agents/tools have you used, and what exactly failed?
4. **How much they get in the way** — too slow, too noisy, wrong answers, hard to steer?
5. **Light or heavy** — what machine, how much RAM, may it download models?
6. **Must be true** — the one outcome that makes it worth it.
7. **Must never happen** — data leaving the machine, actions taken without you?
8. **Where it runs** — laptop, server, browser tab, phone?
9. **What you already have** — accounts, keys, subscriptions this may use.
10. **When it is done** — what would you do with it on day one?

Rules: the answers are the user's words — do not invent what they did not say; an empty
answer is an empty answer, not a "probably".

## 2. Deep research — what the body can actually read

`research_sources()` is the live matrix; `research_source(source, query)` returns
evidence records (title, url, author, date, score/comments, excerpt, retrieval method,
limitation).

| Source | Readable? | How | Measured on this machine |
|---|---|---|---|
| **Hacker News** | ✅ | public Algolia API, no key | **works**: 3 records for "coding agent context window" with points/dates/urls |
| **Reddit** | ⚠️ | public JSON, no key | **HTTP 403** from this machine (anonymous access blocked). Sanctioned routes: the official API with a free app, or the user's own logged-in session via the extension bridge |
| **GitHub issues** | ✅ | public REST search, no key (10 req/min) | works (unit-proven; API path identical to HN) |
| **Stack Overflow** | ✅ | public API, no key at low volume | works |
| **Wikipedia** | ✅ | public API, no key | works |
| **YouTube** | ✅ | public pages + official caption tracks | works (search + metadata; caption *fetch* blocked by YouTube's proof-of-origin token) |
| **Any public page** | ✅ | `research_collect` | works |
| **X** | ❌ | no public search API without developer credentials | refused with the reason (never substituted) |
| **Instagram** | ❌ | needs a Meta business-verified app | refused with the reason |
| **Private groups / DMs** | ❌ | - | refused by design |

What the body cannot do for research: a general web **search engine** adapter (that needs
a provider decision — a free keyless one or a paid one), and "what users like / pain
points" mining that needs those platforms' APIs. Everything else is evidence records the
agent reads and interprets.

## 3. Who owns which work

| Work | Owner | Why |
|---|---|---|
| Plan, write files, run shells, call other MCP servers, decide | **the coding agent** (the brain) | the body must not become a second planner; it also has no shell/file tools on purpose |
| Interview the user | agent asks, `reflex_interview` carries it | the body cannot decide what matters |
| Deep research: fetch, structure, dedupe, cite | **Body-MCP** | perception + evidence |
| Watch / read / listen | **Body-MCP** | `research_video`, `eyes_see_browser(screenshot=True)`, `ears_listen` |
| Choose the tools for this machine | **Body-MCP** (advice) → agent decides | `body_models` + `body_recommend` give reasons; the agent chooses |
| Act (browser, desktop, native apps, your own browser) | **Body-MCP** | the hands |
| Verify and report | **Body-MCP** (evidence) → agent writes the answer | `reflex_verify`, `body_workflow_report` |
| Learn from failures | **Body-MCP** (records lessons) → agent generalises | `body_lessons`; a proposal becomes a fact only when confirmed |
| Safety: permissions, approvals, refusals | **Body-MCP** | enforced in code, not in prompts |

## 4. The three gaps and where they landed

1. **Research layer** → **done** (`sources.py`: HN, Reddit, GitHub issues, Stack Overflow,
   Wikipedia, YouTube + explicit refusals for X/Instagram; unit-tested, rate-limited,
   key-free). Still open: a general search-engine adapter and live-web test coverage.
2. **`reflex_interview`** → **done** (`interview.py`: MCP elicitation form with one field
   per question, Windows-dialog fallback, standard question set).
3. **Caption/audio path** → **partly**: the official caption track is found (and `research_video`
   returns it when YouTube's endpoint answers); from this machine the endpoint returns
   0 bytes, so the honest alternatives are (a) the captions panel through the browser
   (readable via `eyes_see_browser`), or (b) local Whisper over a fetched track - which
   needs `yt-dlp` plus a model, i.e. your explicit consent. Not done automatically.
