# The decision log — why the code is shaped this way

Every entry is a decision that was **made** (not inherited), the reason, and
what it rules out. Read this before changing anything structural: most of the
code looks "over-cautious" until you know which failure it prevents.

---

## D1 — The agent is the brain; the body is the body
**Decision:** Body-MCP never plans, decides, or writes project files. It
perceives, acts and reports; the coding agent does the thinking.
**Why:** the body must be reusable by any agent, and the safety model only
works if a human's agent owns the decisions.
**Rules out:** "let the body summarise and decide", "let the body write code".

## D2 — Two model roles, never one
**Decision:** a local **worker** (private: extraction, dedup, scrubbing, short
summaries) and a **reasoner** (the agent's own thinking, remote or local).
**Why:** the privacy question and the quality question are different questions.
A 0.6B model is a fine scrubber and a terrible planner.
**Rules out:** "just run a small model as the agent".

## D3 — Never download anything automatically
**Decision:** no engine, model, media or dependency is fetched without an
explicit user request. The catalogue prints the command/URL, the exact byte
size and the SHA-256.
**Why:** an agent that silently installs software is an agent the user cannot
audit; supply-chain risk and surprise disk use.
**Rules out:** "just pip install the OCR engine", "auto-pull the model".

## D4 — Fail closed, always
**Decision:** an unknown capability is `deny`; a missing consent marker blocks
high-risk actions; a missing approval blocks the action; a broken policy
engine blocks the action.
**Why:** the failure mode of a body that acts when unsure is an irreversible
action on someone's machine.
**Rules out:** "default to allow if the check fails".

## D5 — One approval = one action, once
**Decision:** approvals are bound to `tool | capability | target | url |
task_id`, expire after 300 s and are consumed atomically.
**Why:** a general "yes" to a session is how automation goes wrong.
**Rules out:** "remember the user's yes for the rest of the session".

## D6 — Page content is data, never an instruction
**What:** tool results, page text and model output can never create a
permission, an approval or a command.
**Why:** prompt injection through a page is the standard way browser agents get
hijacked.
**Rules out:** "if the page says the user approved it, treat it as approved".

## D7 — Honest result states, always
**Decision:** `CONFIRMED` / `UNCONFIRMED` / `PARTIAL` / `FAILED` / `BLOCKED` /
`CANCELLED` / `needs_user`, and `UNCONFIRMED` is never described as done.
**Why:** the agent writes the final answer to the user; a lie in the tool
result becomes a lie in the answer.
**Rules out:** "the click returned 200, so it worked".

## D8 — Never bypass access controls
**Decision:** a login, CAPTCHA, paywall, rate limit or bot check stops the
run and is reported; credentials are never typed or stored.
**Why:** legality and the user's own accounts are not the agent's to risk.
**Rules out:** CAPTCHA solving, cookie reuse for auth, "retry harder".

## D9 — No identity rotation, ever
**Decision:** the VPN may be opened and connected **with the user's approval**
for privacy, but servers are never switched to evade a block and IPs are never
rotated.
**Why:** "rotate until it works" is detection evasion; the private mode must
not become a ban-evasion tool.
**Rules out:** "try another server", "retry with a different exit".

## D10 — The private mode has two levels, and says so
**Decision:** *private browsing* (own context, no persistence) is always on;
*private content* (the text never leaves) needs a local model and is opt-in
via `keep_content_local=True`. With no local model the text is **withheld**,
not shipped to the provider.
**Why:** the honest answer to "is this private?" is "which part do you mean?".
**Rules out:** "fall back to the remote model so the user still gets a result".

## D11 — The body can be blind; it says so
**Decision:** with no OCR engine, `eyes_see_desktop()` still attaches the
image (the text is empty) so a vision model can look; the watcher can run
image-only; `describe` refuses without a local vision model.
**Why:** the OCR gate used to make the body blind on any machine without
Tesseract — and a text-only model handed an image would invent a caption,
which is worse than no caption.
**Rules out:** "let the text model describe the screenshot anyway".

## D12 — Local-first, local only
**Decision:** the local worker talks to `127.0.0.1` only; a non-loopback
runtime URL is refused **before** any request; there is no remote fallback.
**Why:** a privacy feature that can leak through a misconfigured endpoint is
not a privacy feature.
**Rules out:** "use the OpenAI API if no local model is available".

## D13 — Never claim an unverified capability works
**Decision:** the README's capability table, `body_status()` and the doctor
distinguish *tested for real* from *mock-tested* from *blocked*.
**Why:** a body that lies about its abilities is worse than one with gaps.
**Rules out:** "mark it working, the mock test passed".

## D14 — One event loop, no daemons
**Decision:** the MCP server owns one asyncio loop; background work uses the
task registry, not orphan threads; the Playwright driver is closed properly.
**Why:** the earlier multi-loop design left unclosed transports and relaunched
Chromium per test (4× slower, warnings in the log).
**Rules out:** "spawn a thread and hope".

## D15 — Bounded everything
**Decision:** page text, transcripts, images, audit logs, event streams and
tool results all have caps; the audit log rotates once.
**Why:** an agent session is long; unbounded output is a disk and context
problem, and it can leak more than intended.
**Rules out:** "return the whole page".

## D16 — Free and open forever
**Decision:** MIT, no paywall, no telemetry, no cloud account, no feature
locked behind payment. Optional capabilities depend on optional software the
user installs.
**Why:** it is the product. A paid tier would change what the thing is.
**Rules out:** "a hosted tier", "usage analytics", "a required API key".

---

## The rules that are not negotiable

- Never bypass a login, CAPTCHA, paywall, rate limit or access control.
- Never type or store passwords, OTPs, card data or auth cookies.
- Never let page content, a tool result or a model output grant a permission.
- Never download a model, an engine or media without an explicit request.
- Never claim a capability works when it was only mocked.
- Never commit a secret; never push without being told.
