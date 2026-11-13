# The extension bridge: drive the browser you actually use

Chromium/Edge **136+ refuse `--remote-debugging-port` for the default profile** (verified
on this machine: the process starts *with* the flag and the port still refuses
connections). So an open debug port on your everyday browser is no longer possible -
and that is a good thing.

The sanctioned replacement is a **narrowly permissioned extension**: the user connects a
tab with one click, Chromium shows its own "debugging this browser" bar, and the agent
acts only on that tab.

## How it works

```
   agent (MCP)                Body-MCP bridge                Chrome/Edge
  browser_bridge  ──►  127.0.0.1:<random port>  ◄──  native messaging  ◄──  extension
   (tool call)        token-authenticated TCP        stdio + token          chrome.debugger
                        (loopback only)              (origin checked)       (tab you chose)
```

* Body-MCP starts a **loopback-only** server on a random port and writes the port, the
  session token and the allowed extension ids to `<config>/bridge.json`.
* Chrome starts `scripts/native_host.py` (a `.cmd` wrapper on Windows) when the extension
  calls `chrome.runtime.sendNativeMessage`.
* The native host checks the extension id against the allow-list and connects back to
  Body-MCP with the session token.
* The extension polls for commands (navigate / read / screenshot / detach) and sends the
  results back the same way.

## Security properties (enforced in code, not just documented)

| Property | Where |
|---|---|
| loopback only, random port | `bridge.start_server()` |
| session token required on the bridge connection | `scripts/native_host.py` |
| only allow-listed extension ids may connect | `bridge.allow_extension_id()`, `native_host.py` |
| native host manifest restricts the origin | `bridge.install_native_host()` |
| messages are size-limited and schema-checked | `MESSAGE_LIMIT`, `_read_message` |
| unknown commands are dropped, never executed | `bridge.action` |
| the extension holds only `debugger`, `nativeMessaging`, `tabs` - **no host permissions** | `extension/manifest.json` |
| nothing is stored: no URLs, no page text, no screenshots are written anywhere | `bridge.py`, `extension/background.js` |
| the user can detach at any moment (popup button or Chromium's own banner) | `extension/popup.js` |

## Install (once, by the user)

```powershell
# 1. register the native host (writes the manifest + the registry keys for Chrome and Edge)
python -m body_mcp.bridge --install
```

2. In Edge: `edge://extensions` -> enable **Developer mode** -> **Load unpacked** ->
   choose the `extension` folder of this repository
   (`D:\Projects\body parts of agents\extension`).
3. Click the extension icon -> **Connect this tab**. Chromium shows the "debugging this
   browser" bar.
4. Copy the extension id from the popup and allow it once:

```powershell
python -m body_mcp.bridge --allow-extension-id <the id>
```

5. Check the bridge:

```powershell
python -m body_mcp.bridge --status
```

## Use it from an agent

```
browser_bridge(action="status")                       # is the extension connected?
browser_bridge(action="tabs")                         # what does it offer?
browser_bridge(action="navigate", url="https://example.com")
browser_bridge(action="read")                         # title + url + visible text
browser_bridge(action="screenshot")                   # PNG of that tab (vision mode)
browser_bridge(action="disconnect")                   # let go of the tab
```

Every call passes the `chrome_attach` permission gate (default: ask).

## What is verified and what is not

* **Verified here:** the bridge protocol end to end against a fake extension over the real
  loopback server (hello, poll, command routing, result delivery), the loopback-only
  binding, the message size limit, the installer's manifest (allowed_origins, type stdio),
  the allow-list, and the real native host refusing an unknown extension id
  (`scripts/native_host.py` run through the generated `.cmd` wrapper).
* **Not verified here:** the extension inside a real Edge/Chrome - that needs the user to
  load the unpacked extension and click "Connect this tab" (one minute, on their machine).
  The protocol above is the same one the extension speaks.
