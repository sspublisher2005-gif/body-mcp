# The prompt to paste into Claude (with this ZIP attached)

> **How to use it**
> 1. Attach `body-mcp-full-report-YYYYMMDD.zip` to the Claude conversation.
> 2. Paste everything in the block below (after "PROMPT START").
> 3. Claude will read the archive, understand the project, and hand back **one
>    master prompt** that states what we are building, why, for whom — plus the
>    next work, ready to give to a coding agent.

---

## PROMPT START

You are reading the complete source of an open-source project called **Body-MCP**.
The attached ZIP contains the whole project: source, tests, docs, scripts, the
browser extension, the CI workflow and the commit history.

**Step 1 — read the project.** Unzip the archive (use your code execution tool if
the attachment is a zip). Then read, in this order:

- `body-mcp/PROJECT_REPORT.md` (the summary I wrote — treat it as a map, not as
  truth; verify anything that matters against the code)
- `body-mcp/README.md`, `body-mcp/AGENTS.md` (the agent's operating rules),
  `body-mcp/CHANGELOG.md`
- `body-mcp/docs/*.md` (architecture, safety, perception, privacy-mode,
  local-models, research-and-interview, extension-bridge, workflow, release)
- `body-mcp/src/body_mcp/*.py` — the 78 MCP tools live in `server.py`; the
  interesting modules are `permissions.py`, `approvals.py`, `eyes.py`,
  `browser.py`, `watch.py`, `hands.py`, `batch.py`, `restrictions.py`,
  `privacy.py`, `local_worker.py`, `models.py`, `memory.py`, `research.py`,
  `video.py`, `demo.py`, `doctor.py`
- `body-mcp/tests/*.py` — 287 tests; the tests are the specification of the
  behaviour, so read them before judging any design decision
- `body-mcp/scripts/*.py`, `body-mcp/extension/*`, `body-mcp/.github/workflows/*`

**Step 2 — understand it deeply.** Before writing anything, make sure you can
answer for yourself: what problem does this solve; who is the user; what is the
architecture and why is it shaped this way; what the permission model guarantees
and what it deliberately does not; which capabilities are proven and which are
mock-tested only; where the code contradicts the documentation.

**Step 3 — give me back exactly these four things:**

**(A) A one-paragraph definition.** What Body-MCP is, in plain language, that a
non-engineer could repeat correctly. No marketing adjectives.

**(B) The product brief.** What we are creating / why we are creating it / for
whom — three sections, each with the concrete evidence from the code that
supports it. Name the audiences and the job each one hires it for.

**(C) The honest gap analysis.** A table of every capability with: proven how /
mock-tested how / blocked (and on what), plus the contradictions you found
between the docs and the code, and the design risks. Rank the gaps by how much
they block a real user from getting value. Be blunt; a flattering review is
useless to me.

**(D) THE MASTER PROMPT** — and this is the deliverable I care about most.
Write **one** self-contained prompt (in Markdown, inside a fenced block) that I
can hand to a coding agent working on this repository. It must:

- state what we are building, why, and for whom, so the agent cannot drift;
- name the exact files and modules that matter and the conventions it must
  follow (the existing layering, the permission gate, the honest result states,
  the "never download / never bypass / never fabricate" rules);
- list the next concrete work items, ordered, each with a **verification**
  method (a test, a command, a measurable proof) — not "done when it feels
  right";
- state the non-negotiables (free and open forever, no telemetry, no automatic
  downloads, no bypassing access controls, no claiming an unverified capability
  works, everything local-first);
- tell the agent to report honestly what it could not verify.

Format the master prompt so it can be pasted as-is, with no reference to this
conversation. Keep it dense — no filler, no restating what the agent can read
in the code itself.

## PROMPT END
