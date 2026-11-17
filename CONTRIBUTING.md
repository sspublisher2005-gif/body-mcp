# Contributing — test a real workflow and tell us what happened

Body-MCP is free and open. The most useful contribution is not code: it is
**one real workflow, run by a real person, with an honest report** — including
the parts that failed.

## 90-second test

```powershell
git clone https://github.com/sspublisher2005-gif/body-mcp
cd body-mcp
python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m body_mcp.consent --acknowledge
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/demo_real_task.py
```

Then do **one** real task with your own agent and report it. Pick one:

1. **Browser**: open a public page, read it, click one permitted link, verify
   the new page. (No login, no CAPTCHA.)
2. **Your own browser**: load `extension/` in Edge/Chrome, connect a tab, read
   it through `browser_bridge`. See `docs/extension-bridge.md`.
3. **Native desktop**: open Notepad, type a line, read the value back with
   `desktop_read_value`. See `docs/desktop.md`.
4. **Research**: `research_collect` on 2–3 public URLs and check the evidence
   records against what the pages actually say.
5. **Private mode**: start a session, open a page, end it, and check the cleanup
   verdict. See `docs/privacy-mode.md`.
6. **Local worker** (only if you installed Ollama yourself): `body_local_worker`
   on a real page and `task="describe"` on a real screenshot.

## What to report

Open an issue with the **Workflow test** template and give us:

- the exact task and the tools you called, in order;
- what you expected and what actually happened;
- the `data.verification.status` you got (`CONFIRMED` / `UNCONFIRMED` /
  `FAILED` / `BLOCKED` / `CANCELLED`) — never call an `UNCONFIRMED` action done;
- the doctor output (`python -m body_mcp.doctor`) and your OS / Python version;
- a screenshot or the tool output if it helps;
- for repeat use: did the second run behave the same as the first?

A "this failed" report with the verification state and doctor output is worth
more than a "works great" with no detail.

## Rules for contributors (from `AGENTS.md`)

- Never bypass a login, CAPTCHA, paywall, rate limit or access control.
- Never type or store credentials.
- **Never install a model, engine or software because a test asked for it.**
  The project suggests; the user decides whether, when and where.
- If a capability is only mock-tested on your machine, say so.
- Don't commit secrets. Don't push without being told.

## What we will do with your report

Every failure becomes a proposed lesson in `body_lessons` and a work order in
`docs/BACKLOG.md`. Every fix ships with a test that fails before and passes
after. You will be credited in the CHANGELOG if you want.
