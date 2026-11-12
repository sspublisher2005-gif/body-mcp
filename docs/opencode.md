# Using Body-MCP from OpenCode

Verified on this machine with **opencode 2.2.6** (Windows 11, Python 3.14).

## 1. Install the server

```powershell
cd C:\path\to\body-mcp
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
playwright install chromium
```

Use the venv's interpreter in the MCP command. A global `python` can resolve a
different (older) install — `python -m body_mcp.doctor` tells you which one is
running.

## 2. Acknowledge consent (once)

```powershell
python -m body_mcp.consent --acknowledge
```

Without it, protected actions (dangerous clicks, app launches, attaching to your
browser) are refused — that is fail-closed by design, not a bug.

## 3. Register the MCP server

```powershell
opencode mcp add body -- C:\path\to\body-mcp\.venv\Scripts\python.exe -m body_mcp.server
```

Or edit `~/.config/opencode/opencode.jsonc` (back it up first — opencode has no
`mcp remove`, so disconnecting means deleting the entry):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "body": {
        "type": "local",
        "command": ["C:\\path\\to\\body-mcp\\.venv\\Scripts\\python.exe", "-m", "body_mcp.server"]
      }
    }
  }
}
```

## 4. Check the connection

1. Start opencode; the server appears in the MCP panel of the TUI.
2. Ask the agent: *"call body_status and tell me what the body can do"*.
   A working server answers with version, tool count (18), browser state,
   permission summary and the real availability of OCR/STT.
3. Offline check without an agent:

```powershell
python -m body_mcp.doctor
```

## 5. Safe first run

```
Look at https://example.com and tell me the page title. Do not click anything.
```

Then a slightly deeper one:

```
Open https://example.com, click the "More information..." link, and verify the
resulting page title with reflex_verify before you report it as done.
```

The agent will:

- `eyes_see_browser(url)` → snapshot with refs (`link_1#3`),
- `hands_click("link_1#3")` → click,
- `reflex_verify("Example Domain")` → proof.

## 6. Driving the browser you already have open

Body-MCP can act on your own tab instead of a Playwright-managed browser:

```powershell
# you run this — a browser window opens with a loopback debug port
python -m body_mcp.cdp_launch --browser chrome
```

Then in the agent:

```
attach_browser(endpoint="http://127.0.0.1:9222")
list_tabs()
select_tab(selector="0")
```

Both `attach_browser` and `select_tab` require an explicit approval from you.
The agent will call `reflex_ask` with the exact action; approve only the tab you
meant. When the task is done:

```
detach_browser()
```

The debug port is unauthenticated while it is open — restart the browser normally
afterwards (or use `--user-data-dir <temp>` for a disposable profile).

### The Chromium-136 rule (why "my own browser" is not drivable yet)

Since Chromium/Edge **136**, the browser **ignores `--remote-debugging-port` when the
default user-data directory is used**. Verified here: Edge started *with* the flag and
*with* your everyday profile came up, but `127.0.0.1:9222` refused connections - there
is no endpoint to attach to.

So there are three levels, and the launcher never pretends otherwise:

| Level | Status | How |
|---|---|---|
| drive a browser Body-MCP started | works | `python -m body_mcp.cdp_launch --browser edge` (disposable profile) then `attach_browser()` |
| drive your everyday window | **not possible** | the debug port is refused for the default profile |
| see your everyday window | works, read-only | `body_windows()` - window titles only |

`cdp_launch` prints which profile it uses and never silently opens a different browser:

```
  profile: DISPOSABLE at ...\body_mcp\cdp-profile\p9222-<ts>
  NOTE: this is a SEPARATE browser window with its own empty profile -
        it is NOT your everyday browser. Use --own-profile to try yours.
```

With `--own-profile` the port usually does not come up (the rule above); the launcher
then explains exactly why and lists the alternatives - the missing piece being the
**extension bridge** (a Chromium extension attaching through `chrome.debugger` after you
click "Allow", over a validated native-messaging channel).

## 7. What the agent gets, and what it must do with it

- Every tool answers `{success, message, data}`.
- `data.verification.status` is `CONFIRMED`, `UNCONFIRMED`, `FAILED` or
  `UNVERIFIED`. `UNCONFIRMED` means "the action ran, the effect is unproven" —
  the agent should call `reflex_verify()` before claiming success.
- `data.required_action` appears when an approval is needed. The agent should
  pass that exact JSON to `reflex_ask(question=..., action=...)` — that is the
  only way an approval can be issued.
- `hands_batch` returns `data.status` (`completed` / `failed` / `blocked` /
  `needs_user` / `retry_scheduled`), `data.task_id`, `data.checkpoint_id` and
  `data.completed_steps` with a `verified` flag per step.
- When a batch returns `needs_user`, re-run it with the same `task_id` after the
  approval — approvals are bound to that task.

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `body_status` says "no browser page is open yet" | no page yet | call `eyes_see_browser(url)` first |
| `PERMISSION_DENIED` / `needs_consent` | consent not acknowledged | `python -m body_mcp.consent --acknowledge` |
| `approval required` with `required_action` | protected action | approve that exact spec via `reflex_ask`, then retry |
| `stale reference` | the page was re-scanned or navigated | call `eyes_see_browser()` again and use the new refs |
| `cannot reach CDP at http://127.0.0.1:9222` | browser not started with `--remote-debugging-port` | `python -m body_mcp.cdp_launch` |
| `refusing non-loopback CDP endpoint` | endpoint is not local | use `http://127.0.0.1:<port>` |
| `BLOCKED_BY_CAPTCHA` / rate limit | the site is restricting access | complete it manually; Body-MCP will not bypass it |
| Server does not appear in opencode | wrong interpreter or command | `python -m body_mcp.doctor` shows the running interpreter; re-add with the venv python |

## 9. Disconnect

1. Stop the agent session.
2. Delete the `body` entry from `~/.config/opencode/opencode.jsonc`
   (opencode has no `mcp remove`).
3. Optional: `python -m body_mcp.consent --revoke` (check the CLI flags with
   `python -m body_mcp.consent --help`) and delete
   `%USERPROFILE%\.config\body_mcp\audit.log` to remove local records.
