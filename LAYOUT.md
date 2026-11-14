# Where everything lives

**One home:** `D:\Projects\body parts of agents`

Everything that belongs to Body-MCP ("body-dev") is here. Nothing is kept
anywhere else, and nothing is published that should not be.

```
D:\Projects\body parts of agents\
├── .git\                  the history (11 commits) - origin: github.com/sspublisher2005-gif/body-mcp
├── .venv\                 the working environment (editable install -> .\src)
├── src\body_mcp\          the implementation: 78 MCP tools
├── tests\                 287 tests - the executable specification
├── docs\                  18 documents (BACKLOG.md, DECISIONS.md, privacy-mode.md, ...)
├── scripts\               builders, acceptance runs, the doctor wrapper
├── extension\             the MV3 bridge for driving your own browser
├── examples\              usage examples
├── reports\qa-campaign\   the QA campaign (matrix, defects, environment report)
├── .github\workflows\     ci.yml (tests on Windows + Linux) and publish.yml (PyPI)
│
├── runtime\body_mcp\      THE RUNTIME PROFILE (live data)
│   ├── permissions.json   your allow/ask/deny profile
│   ├── consent.json       the consent marker
│   ├── memory.db          the local memory (SQLite + FTS5)
│   ├── notes\             hand-editable Markdown notes
│   ├── audit.log          the audit trail (rotated once)
│   ├── bridge.json        the extension-bridge state
│   ├── native_host.cmd    the Chrome/Edge native-messaging host
│   └── cdp-profile\       the disposable Chromium profile (cleaned by cdp_launch --cleanup)
│
├── config\                COPIES of the agent apps' own config (backup, not used live)
│   ├── opencode\          opencode.jsonc + the old backups
│   └── claude\            claude.json + settings.json
│
├── dist\                  built artifacts: the wheel, the release zip, the bundles
└── backups\               older snapshots of the project
```

## The one thing on C: (a pointer, not a copy)

```
C:\Users\shash\.config\body_mcp   ->  junction  ->  D:\Projects\body parts of agents\runtime\body_mcp
```

It is a **directory junction**, not a copy: the bytes are on D:, and every
existing path (the doctor's default config dir, the Chrome/Edge native-messaging
registry entry, the `native_host.cmd`) keeps working untouched. Delete the
junction and nothing breaks as long as `BODY_MCP_CONFIG_DIR` points at the D:
path.

The live app configs stay where their apps require them:
`~\.config\opencode\opencode.jsonc` (it registers the `body-dev` MCP server with
the D: interpreter) and `~\.claude\`. Copies are kept in `config/` above.

## The commands (all from this folder)

```powershell
.\.venv\Scripts\python.exe -m pytest -q          # 287 tests
.\.venv\Scripts\python.exe -m ruff check .       # lint
.\.venv\Scripts\python.exe -m body_mcp.doctor    # what is real here + the next commands
.\.venv\Scripts\python.exe scripts\acceptance_private_mode.py
.\.venv\Scripts\python.exe scripts\build_handoff.py     # the ZIP for Claude Code
.\.venv\Scripts\python.exe scripts\build_bundle.py      # the single-file bundles
git push                                          # origin = the public GitHub repo
```

## The published project

<https://github.com/sspublisher2005-gif/body-mcp> — public, MIT, release
`v0.4.0` with the wheel and the release zip attached.
