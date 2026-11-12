# Private mode: what is actually private

There are **two different things** people mean by "private browsing", and they
cost different amounts of work. Body-MCP does both, and says which one you got.

| Level | What stays on your machine | Needs |
|---|---|---|
| **A — private browsing** | the *browsing*: own throwaway context, no cookies, no login, nothing persisted | nothing (free, works now) |
| **B — private content** | the *text*: what you read is redacted and summarised locally, so only the summary leaves | a local model (Ollama) |

Level A is about **persistence**. Level B is about **the text leaving the
machine**. A VPN does not do level B either.

## Level A — the private session (free, no installs)

```python
privacy_session_start(label="research", mode="private")   # isolated context
privacy_session_open(session_id, "https://example.com")
privacy_session_snapshot(session_id)                        # bounded text, not stored
privacy_session_end(session_id)                             # context closed, cleanup verified
```

What is guaranteed:

* a **throwaway browser context** — its own cookies, its own storage, nothing
  written to your everyday profile;
* nothing from the session lands in persistent memory, the audit log or the event
  stream;
* `privacy_session_end()` closes the context and **reports whether the cleanup was
  verified** (it does not claim success it cannot see);
* access controls are still respected: a login, CAPTCHA or paywall stops the
  session, it is never bypassed.

What it is **not**: anonymity. Sites, your network, your device administrator,
installed software and downloaded files can still observe you. See
`docs/CONSENT.md` for the full breakdown (history vs cookies vs IP vs accounts vs
fingerprinting vs provider visibility).

## Level B — keeping the content local (needs Ollama)

```python
privacy_session_start(label="research", mode="private", keep_content_local=True)
privacy_session_snapshot(session_id)
```

With `keep_content_local=True` the page text is **redacted and summarised by a
model running on your machine**. The snapshot comes back with `text: null` and a
`summary` instead. The raw text stops at the local model.

The rules:

* **No local model → the text is withheld**, not shipped. The snapshot fails with
  the exact reason and the command to fix it. It is never quietly sent to your
  model provider.
* The worker talks to **127.0.0.1 only** — a runtime URL pointing off the machine
  is refused before any request is made.
* If you also want the **reasoning** to stay local, run the agent itself on a
  local model (see `docs/local-models.md`) — that is outside Body-MCP's control.

One command to enable it:

```powershell
winget install Ollama.Ollama     # or download from https://ollama.com
ollama pull qwen3:0.6b           # 498 MB, free, no API key
```

`body_privacy_preflight()` tells you whether level B is possible on your machine
right now (`content_policy.content_local_possible`), and `body_local_models()`
tells you which model fits your RAM.

## The VPN (Proton VPN, Windows)

`privacy_vpn_connect()` opens Proton VPN and asks **the app itself** to connect:

* it clicks only the app's own connect button (exact name match — never a fuzzy
  match, never a server list);
* it then **reads the window** and reports `connected`, `not connected` or
  `unknown`. `unknown` means the app did not say — check the app yourself.
* it never switches servers or rotates IPs to evade a block.

It is **denied by default**: set `"vpn_control": "allow"` in
`%USERPROFILE%\.config\body_mcp\permissions.json` (a user edit — the agent cannot
make it) before the tool will touch the app.

> Not verified against a live Proton VPN on the machine where this was written
> (Proton VPN is not installed there). If your version names the button
> differently, the tool reports "no connect button found" instead of clicking
> something else.

## Brave, the assistant tab, and the rest

`mode="private"` also accepts:

* `browser="brave"` — Brave as the engine (fall back to the managed Chromium if
  Brave is not installed; the preflight says which one you got);
* `assistant=True` — the AI assistant (Venice AI) opened first as the research
  tab, with the real sites in a second tab.

`body_privacy_preflight()` reports, before anything starts: which browsers are
installed, whether the VPN app is installed and open, whether a local model is
configured, the free RAM, and the warnings.

## What the private mode will never do

* bypass a login, CAPTCHA, paywall, rate limit or bot check;
* type or store passwords, OTPs or card data;
* rotate identities or switch VPN servers to dodge a block;
* fetch your exit IP without being asked (asking a third party for your IP is
  itself a disclosure);
* claim the content stayed local when it did not, or claim anonymity.
