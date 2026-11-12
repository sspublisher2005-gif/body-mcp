# Body-MCP bridge extension (unpacked)

This extension is the **sanctioned** way for Body-MCP to drive the browser you
actually use. Chromium shows its own "Body-MCP bridge is debugging this browser"
bar while it is attached, and you can cancel that at any moment.

## What it can do

* attach to **the tab you select** (never all tabs, never silently),
* navigate that tab to a URL you ask for,
* read that tab's title, URL and visible text on request,
* take a screenshot of that tab on request,
* detach on request (popup button, or the agent's `disconnect` action).

It does **not** read anything until you click "Connect this tab", it has no host
permissions (no access to any website by default), and it never talks to anything
except the local Body-MCP bridge on `127.0.0.1`.

## Install (one time)

1. Open `edge://extensions` (Edge) or `chrome://extensions` (Chrome).
2. Turn on **Developer mode**.
3. Click **Load unpacked** and choose the `extension` folder of this repository.
4. Click the extension icon -> **Connect this tab**.
5. Copy the extension id shown in the popup and allow it once:

```powershell
python -m body_mcp.bridge --install
python -m body_mcp.bridge --allow-extension-id <the id you copied>
```

## Use it from an agent

```
browser_bridge(action="status")     # is the extension connected?
browser_bridge(action="tabs")       # what does it offer?
browser_bridge(action="navigate", url="https://example.com")
browser_bridge(action="read")       # title + url + visible text of the connected tab
browser_bridge(action="disconnect")
```

## Why this and not a debug port

Chromium 136+ refuses `--remote-debugging-port` for the default profile, so an
open port on your everyday profile is not possible any more. The extension route
keeps the port closed and puts the decision in your hands: one click per tab, a
visible indicator, and a detach button.

## Files

| File | Purpose |
|---|---|
| `manifest.json` | MV3 manifest: `debugger`, `nativeMessaging`, `tabs` - nothing else |
| `background.js` | attaches the debugger on request, polls the native host for commands |
| `popup.html` / `popup.js` | the Connect / Disconnect UI and the extension id |
