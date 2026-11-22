# Self-healing plan — when a coding agent's work fails

Researched 2026-11-22 with the body: HN Algolia, the body's own
`research_youtube_search` / `research_video`, and the existing source.

## 1. Evidence (what the ecosystem actually does)

| Source | Observed mechanism |
|---|---|
| HN 46990146 — Tako AI | "When generated code fails — wrong parameter, rate limit, schema change — it **traps the stack trace, feeds the error back to the LLM with context, and rewrites the code**." Also: "zero hallucinations: it writes code, executes it, and returns the **raw result**"; 107 endpoints solved by **dynamic spec discovery**, not cramming tools into the prompt. |
| HN 46229687 — Peek | `peek doctor --fix` plus a **complete error catalog** (PEEK-XXX) — repair is driven by a stable code, not a fuzzy description. |
| HN 47200719 — OpenGem | **8-category error classifier**, cooldown + jittered backoff. Note: their account-rotation is deliberately NOT copied — we never rotate identity to evade a limit. |
| `research_youtube_search` (body, proven over MCP) | found "How to Create a Self Healing Code Agent" (LangChain, 24k views). `research_video` honestly reported **0 caption lines** — no transcript, so no claim is made from it. |
| Our `src/body_mcp/lessons.py:1-20` | already an error catalog: stable codes (`STALE_REF`, `APPROVAL_REQUIRED`, `BLOCKED_BY_CAPTCHA`, …) with fix hints, stored as **proposed** lessons until confirmed. |

**Conclusion:** self-healing is not a new product. It is a *closed loop* we already
have 80% of: stable error codes → hint → research → proposed fix → agent applies →
verify → promote lesson. What is missing is (a) one entry point that assembles the
diagnosis, and (b) an instruction that makes the agent use it.

## 2. Design rules (non-negotiable)

1. **The body never fixes the user's project.** It has no file/shell tools
   (`shell: deny`, `local_files: deny` in `permissions.py`). It supplies evidence
   and a proposed fix; the **brain** (coding agent) applies it.
2. **No silent retry loops.** Max 3 attempts; each failure must change something
   (a new ref, a different source, a corrected argument) — never "try again".
3. **Approvals are never auto-granted.** A consequential fix needs a fresh
   `reflex_ask` spec; deny wins; one approval = one action.
4. **A lesson stays proposed** until a human or a successful retry confirms it.
5. **Blocks stay blocks.** A login/CAPTCHA/paywall/rate limit is a `needs_user`
   decision (already in `human_choice.py`), never something to heal around.
6. **Never install anything** to fix a failure (D17). Suggest the command only.

## 3. The feature: `body_failure_context(code, tool, message)`

One call returns everything the agent needs to fix the *right* thing:

- **what happened** — error code, tool, message, verification state;
- **known fix** — the hint from `lessons.HINTS` for that code (error catalog);
- **past lessons** — `body_lessons(tool=...)` entries, marked proposed/verified;
- **research route** — which `research_*` tool to use for external causes;
- **the loop** — propose fix → ask approval → apply → `reflex_verify` → promote.

Why one tool: agents skip multi-step procedures (observed this session — an agent
reached for `webfetch` instead of the body's own research tools). A single entry
point is the same trick as `body_capabilities()` at startup.

## 4. Where it lives

- `src/body_mcp/healing.py` — assemble the diagnosis from existing helpers (no new
  storage, no new state).
- `server.py` — one tool `body_failure_context`, registered like the others.
- `SKILL.md` + `AGENTS.md` — an "ON FAILURE" section: call the tool, then follow
  the loop. This is the part that makes it automatic.
- `tests/test_healing.py` — limits, no-silent-retry, and that blocks stay blocks.

## 5. Verification (done after implementation)

- full suite (321+), Ruff clean;
- the real MCP stdio guard (the tool must not crash over MCP — that was #1–#3);
- a deliberately failing call → `body_failure_context` → correct hint + needs_user
  preserved for a blocked source.

## 6. Explicitly out of scope

No new repo (it would split the LEARN loop and duplicate install/permissions/CI).
No auto-apply, no auto-install, no account rotation, no CAPTCHA solving, no
credential use, no "retry until it works".
