# Example: research prompt for the brain

Paste something like this to your coding agent (with the Body-MCP server connected):

> Use the Body-MCP server. Open https://www.reddit.com/r/LocalLLaMA/, research the best open-source computer-use agents, read a few public posts, and give me a short comparison with sources. If a login, CAPTCHA, or restriction appears, stop and ask me.

## What a correct brain does with Body-MCP

1. `hands_open("https://duckduckgo.com/?q=best+open+source+computer+use+agents+2026")` — start from a search page with no account wall.
2. `eyes_see_browser()` — scan result links; note refs (`link_3`, …).
3. For each of 3–5 public sources, at a human-like pace:
   - `hands_click("link_N")`
   - `eyes_see_browser()` — read headings, visible text, outbound refs.
   - `reflex_verify("<a string you expect on that page>")` — confirm the page actually loaded before drawing conclusions.
4. Reddit specifically: prefer its public/RSS surfaces or the official API with your own (logged-out) access. If Reddit shows a login/CAPTCHA/rate-limit page:
   - Body-MCP returns `STOP …`; the brain must tell you and WAIT. It must not click through, solve, or route around it.
5. Synthesize the comparison; cite every source with its URL. No fabricated quotes, no invented benchmarks — if a page was unreadable, say so.

## Asking the human

If the brain needs your decision mid-flow: it calls `reflex_ask("…")`. You answer yes/no (OpenCode shows a form; otherwise a Windows dialog appears). Only an explicit yes authorizes a dangerous click.

## What this example deliberately does not include

- No CAPTCHA handling of any kind — the human completes it, or the task stops.
- No login walls: reading logged-out public content only.
- No scraping spree: a handful of pages, with human-like delays.
- No reposting content: the output is your summary + links.
