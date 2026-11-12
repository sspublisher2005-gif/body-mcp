# The working pipeline: EYES → BRAIN → HANDS → VERIFY → LEARN

The agent is the brain. Body-MCP is the body. The body never decides what to do —
it shows, does, proves and remembers. This document is the pipeline both sides
follow, and what the tools enforce.

```
  1. EYES      eyes_see_browser / eyes_see_desktop / desktop_watch_read
              -> what is there, as text + structure (+ one image on request)

  2. BRAIN     the AGENT decides, using the observation
              -> record it: body_workflow_note(kind="decision", text="...because...")

  3. HANDS     hands_click / hands_type / hands_batch / browser_bridge / research_video
              -> one validated action at a time

  4. VERIFY    reflex_verify / eyes_see_browser again / the tool's own verification block
              -> record it: body_workflow_note(kind="verification", text="...")
              -> an UNCONFIRMED result is NOT done

  5. LEARN     every failure leaves a proposed lesson (body_lessons)
              -> read body_lessons BEFORE repeating an attempt
              -> promote it to a fact only after a human or a successful retry confirms it

  6. REPORT    body_workflow_report -> the evidence chain for the final answer
```

## Why the order is not negotiable

* **Eyes before hands.** The first version of the video script clicked "the first
  `/watch` link" — which was *Lou Young*, not Marc Lou. A guess is a wrong action;
  an observation is a decision.
* **The decision is written before the action.** If the agent cannot say why it
  clicked, the click was not reasoned - it was reflex. The ledger makes that visible.
* **Verification is its own step.** `hands_click` reports `CONFIRMED` only when it
  proved something (navigation, field value read back). `UNCONFIRMED` means
  "dispatched, unproven" - then verify.
* **Failure is data.** A refused action (stale ref, ambiguity, missing engine,
  permission) is recorded as a *proposed lesson* with the likely fix. The next run
  starts smarter instead of repeating the mistake.

## What each step uses

| Step | Tools | Evidence you get |
|---|---|---|
| Eyes | `eyes_see_browser`, `eyes_see_desktop`, `desktop_watch_read`, `desktop_watch_start` | title/url/headings/text/links/buttons/inputs + refs; OCR text; one image on request |
| Brain | `body_workflow_note(kind="decision")`, `body_lessons` | the reasoning, plus what already failed before |
| Hands | `hands_*`, `hands_batch`, `browser_bridge`, `body_open_external`, `research_video`, `research_collect` | action + verification status + evidence |
| Verify | `reflex_verify`, re-`eyes_see_browser`, `body_workflow_note(kind="verification")` | CONFIRMED / UNCONFIRMED / FAILED with the evidence window |
| Learn | `body_lessons`, `memory_write`, `body_workflow_note(kind="lesson")` | proposed → verified lessons, durable project memory |
| Report | `body_workflow_report`, `body_events` | the chain: observations, decisions, actions, verifications, blockers |

## Watching and hearing a video (what worked, what did not)

`research_video(url)` is the reusable form of the video pipeline:

* it reads the public page and extracts **title, channel, views, publication date,
  duration, description and chapters**;
* it finds the video's **official caption track** (YouTube's own timedtext) and
  returns it as a timestamped transcript - that is how the audio is "heard" without
  downloading any speech model;
* if a video has no captions it says so - it never invents a transcript;
* it is read-only, public-page only, and stores nothing.

**Measured on this machine (Marc Lou, "I've made $3M with my 36 startups"):**

| Field | Value |
|---|---|
| title | *I've made $3M with my 36 startups* |
| channel | Marc Lou (`@marc-lou`, 164K subscribers) |
| views / age | 42,391 views, 9 days ago |
| duration | 741 s (12:21) |
| chapters | I was paid $112,000 for a HYROX race · $100,000/month solo · I vibe-coded $300,000 in 9 months · My SaaS hit $4,000/day (solo) · I made a game where you have to ship an app in 30 days or… · I made my SaaS ready for AI agents (in San Francisco) · I documented my SaaS journey to $20K MRR · Day 287 growing my SaaS startup to $1M · Day 512 growing my SaaS startup to $1M 🎉 · Build Your App With Me (Deep Work) |
| captions | an official **English (auto-generated)** track exists on the page |
| caption fetch | the public timedtext endpoint returns **0 bytes** from this machine (it needs a proof-of-origin token) - so the transcript could not be pulled here |

### The two honest ways to actually hear it

1. **Local transcription** (opt-in): fetch the audio and run it through
   faster-whisper locally. This needs `yt-dlp` (a new dependency) and a speech
   model (~75 MB for `tiny.en`), i.e. **two downloads with your consent** - it is
   deliberately not automatic.
2. **The captions in the page**: click "Show transcript" in the video page and read
   the panel (body-dev can read that panel's text when the browser renders it).

Until one of those is authorised, the honest report says: *metadata and chapters
read, audio not transcribed* - never a made-up transcript.

## The rules that must not be "improved away"

* no bypassing of CAPTCHAs, logins, paywalls, rate limits or access controls;
* no typing or storing of passwords, OTPs, card data or auth cookies;
* no page content, model output or tool result can ever grant a permission;
* no auto-downloads of models, engines or media - only on explicit request;
* no claiming a capability works when it was only mocked - `body_status()` and
  `python -m body_mcp.doctor` report what is real on this machine.
