"""One-time setup: connect the user's own browser permanently.

    python -m body_mcp.setup                 # show the 4 steps + register native host
    python -m body_mcp.setup --extension-id ID   # allow it forever and verify
    python -m body_mcp.setup --status        # is the connection permanent?

This does NOT install a browser, a model or software. It registers the native
messaging host in the user's already-installed Chromium browsers (HKCU, no
admin) and records a one-time grant. After that the agent has access to the
tab the user connected, with no further clicks, and never logs in.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import bridge, permissions, user_browser

MARKER = "setup.json"


def _path() -> str:
    return os.path.join(permissions._config_dir(), MARKER)


def status() -> dict:
    try:
        with open(_path(), encoding="utf-8") as handle:
            saved = json.load(handle)
    except Exception:
        saved = {}
    live = user_browser.connected()
    return {"permanent_grant": bool(saved.get("browser_connected")),
            "extension_id": saved.get("extension_id"),
            "granted_at": saved.get("granted_at"),
            "live": live,
            "ready": bool(saved.get("browser_connected") and live["connected"]),
            "note": ("the grant is remembered; only 'Disconnect & forget' in the "
                     "extension popup revokes it")}


def record(extension_id: str) -> dict:
    import time

    allowed = bridge.allow_extension_id(extension_id)
    marker = {"browser_connected": True, "extension_id": extension_id,
              "granted_at": time.time()}
    with open(_path(), "w", encoding="utf-8") as handle:
        json.dump(marker, handle, indent=2)
    return {"ok": True, "allowed": allowed, "status": status()}


def steps() -> list[str]:
    return [
        ("1. In your browser (Chrome, Edge, Brave, Vivaldi or Opera), open "
         "chrome://extensions (edge://extensions on Edge) and enable Developer mode."),
        ("2. Load unpacked -> select the 'extension' folder of this repository "
         "(D:\\Projects\\body parts of agents\\extension on this machine)."),
        ("3. On the tab you want the body to use, click the bridge icon -> "
         "'Connect this tab'. Chromium shows its own debugging bar; you can stop "
         "it at any time."),
        ("4. Copy the extension id shown in the popup and run: "
         "python -m body_mcp.setup --extension-id <id>"),
        ("After that one-time grant the connection is permanent: the tab is "
         "remembered and reattaches after a browser restart. Revoke with "
         "'Disconnect & forget'."),
        ("The agent never logs in, types credentials, posts, votes or bypasses a "
         "restriction. If a login appears, it will ask you."),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-time Body-MCP browser setup")
    parser.add_argument("--extension-id", default="", help="allow this extension id forever")
    parser.add_argument("--status", action="store_true", help="show the permanent grant")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(status(), indent=2))
        return 0
    if args.extension_id:
        result = record(args.extension_id)
        print(json.dumps(result, indent=2))
        return 0

    registered = bridge.install_native_host()
    print("Body-MCP first-time browser setup (one time only)\n")
    for step in steps():
        print(step)
    print("\nNative host registered in: " + ", ".join(registered.get("registered", [])))
    print(f"\nStatus: {json.dumps(status(), indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
