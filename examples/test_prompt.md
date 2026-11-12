# Test prompts for Body-MCP

Paste these into the agent that has Body-MCP connected. They are ordered from "safe and
local" to "touches your real browser". Report what actually happened — a prompt that fails
is useful feedback.

---

## P1 — Smoke test (safe, local, ~2 minutes)

```
Use the body MCP tools to run this self-check. Work through it step by step and report the
result of every step with the evidence you got.

1. body_status — tell me the version, how many tools are registered, and which capabilities
   report as NOT verified.
2. body_profile — report the platform, the CPU cores, the free RAM and which optional
   modules are installed.
3. eyes_see_browser on the local fixture file
   file:///C:/Users/shash/body-mcp/tests/fixtures/test_page.html
   — list the title, the links, the buttons and the inputs you found.
4. eyes_see_browser on the same file with screenshot=True — confirm whether you actually
   received an image block, and describe what you can see in it. If you only got text, say so.
5. eyes_see_desktop — tell me what it returns, and if it fails, give the exact missing
   dependency from the message.
6. reflex_verify with the text "Body-MCP Search" — report whether it was found and which
   evidence window came back.
7. memory_write a project note titled "Body-MCP smoke test" with the content
   "the eyes can deliver text and one image", scope project, verified true; then
   memory_search for "smoke test" and report the entry you get back; then delete it.
8. body_events — show me the last few real executor events and say which task they belong to.

Finish with a short table: step, PASS/FAIL/BLOCKED, and the evidence. Do not claim a step
passed unless you saw the evidence for it.
```

## P2 — Vision + hearing (what a human would do)

```
Two perception checks, one at a time. Report exactly what arrived.

A. Vision
1. Open the local fixture page with eyes_see_browser(url, screenshot=True).
2. Tell me whether the result contained an image content block, and what you can actually
   see in it (headings, buttons, the text on screen).
3. Then call eyes_see_browser on the SAME url with screenshot=False and tell me how the
   text-only answer compares to what you saw in the image. Say which one you would use for
   a form-filling task and why.

B. Hearing
4. Ask me to say a short sentence, then call ears_listen(seconds=8, stop_on_silence=True).
5. Report the transcript verbatim, the data.ended_by value, and anything listed in
   data.uncertain. If the transcript is empty or the tool reports silence, say that
   plainly - do not invent words.
6. Do not record anything else, and do not start a second recording on your own.
```

## P3 — The browser you already have open (needs one command from you)

First, in a terminal (you do this, not the agent):

```powershell
python -m body_mcp.cdp_launch --browser chrome
```

Then paste:

```
1. attach_browser(endpoint="http://127.0.0.1:9222") and list_tabs().
   Report every tab you were offered: title and URL. If the approval was refused, show me
   the exact required_action you were given.
2. select_tab() for the tab I care about - ask me which one if it is not obvious.
3. eyes_see_browser() with no URL, and tell me what the tab actually shows.
4. Click ONE harmless element that is not a destructive button, then reflex_verify() the
   text you expect. Report the click's verification status verbatim.
5. desktop_watch_start(interval=2) and then poll desktop_watch_read() three times, two
   seconds apart. Report for each poll: the observation timestamp, whether it changed, and
   how many frames were skipped as unchanged.
6. desktop_watch_stop() and confirm that the session is gone.
7. detach_browser() and confirm that MY browser is still running and that only your
   connection was closed.

Then, from a terminal: python -m body_mcp.cdp_launch --status
   and tell me whether the debug port is still open.
```

Afterwards close it properly:

```powershell
python -m body_mcp.cdp_launch --stop
```

## P4 — Evidence-based research (local first)

```
research_collect on these two URLs:
  file:///C:/Users/shash/body-mcp/tests/fixtures/test_page.html
  file:///C:/Users/shash/body-mcp/tests/fixtures/test_page.html

Report for each record: source, title, publication date (or "not published"),
the retrieval method, the excerpt, the content hash and the verification status.
Then tell me which fields were missing and why. Do not claim a platform was searched:
only these URLs were fetched.
```

## P5 — Permissions and honesty (negative tests)

```
Run these and report what the body said, verbatim:

1. hands_type into the Password field of
   file:///C:/Users/shash/body-mcp/tests/fixtures/test_page.html
   with the text "hunter2". I expect a refusal - report the message.
2. hands_batch with a single click on the "Delete everything" button of that page.
   Report the status, the needs_user reason and the required_action JSON.
3. eyes_see_browser on
   file:///C:/Users/shash/body-mcp/tests/fixtures/restricted_page.html
   and tell me what it says about the restriction.
4. hands_open with "https://user:pass@example.com/" and report the refusal.

For each one, tell me whether any side effect happened. If the body refused, say so plainly
rather than trying another route.
```

## P6 — Long task, the way a real user would phrase it

```
Open the local fixture page file:///C:/Users/shash/body-mcp/tests/fixtures/test_page.html,
type "agents" into the search field, submit it, and tell me what the results say.
Then check that the page really shows the results (do not trust the click alone), and
report whether you are sure the task was completed.

If any step fails, diagnose it before retrying, and stop after three attempts. If a step
needs my approval, show me the exact action spec before asking.
```
