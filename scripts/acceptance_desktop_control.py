"""REAL desktop acceptance: drive a native Windows app (Notepad) through UI Automation.

    python scripts/acceptance_desktop_control.py

Opens Notepad (a harmless app), inspects its real control tree, types into it,
reads the value back as the verification, and closes it again. No mocks.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from body_mcp import permissions, uia  # noqa: E402

RESULTS = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok))
    print(f"[{'PASS_REAL' if ok else 'FAIL':<10}] {name}: {detail}")


def main() -> int:
    permissions.acknowledge_consent()
    notepad = subprocess.Popen(["notepad.exe"], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2.5)
    try:
        listing = uia.inspect("Notepad")
        controls = listing.get("controls", [])
        names = [c["name"] for c in controls][:12]
        record("inspect the window", bool(controls),
               f"{listing.get('count')} control(s), window={listing.get('window')!r}, "
               f"names={names}")

        editable = next((c["name"] for c in controls
                         if c["type"] in ("Edit", "Document", "Text") and not c["sensitive"]), None)
        if not editable:
            editable = "Text Document"
        typed = uia.type_text("Notepad", editable, "Body-MCP desktop acceptance")
        record("type into a real field", bool(typed.get("ok")),
               f"field={typed.get('into')!r} typed={typed.get('typed')} "
               f"{'' if typed.get('ok') else typed.get('reason')}")

        value = uia.read_value("Notepad", editable)
        text = str(value.get("value") or "")
        record("read the value back (verification)", "Body-MCP desktop acceptance" in text,
               f"value={text[:80]!r}")

        refused = uia.type_text("Notepad", "Password", "hunter2")
        record("password-like field refused", refused.get("ok") is False,
               str(refused.get("reason"))[:100])

        missing = uia.click("Notepad", "NoSuchButtonAnywhere")
        record("unknown control refused (no blind click)", missing.get("ok") is False,
               str(missing.get("reason"))[:100])

        unknown_window = uia.inspect("ThereIsNoSuchWindowAnywhere")
        record("unknown window refused", unknown_window.get("ok") is False,
               str(unknown_window.get("reason"))[:100])
    finally:
        with __import__("contextlib").suppress(Exception):
            subprocess.run(["taskkill", "/PID", str(notepad.pid), "/T", "/F"],
                           capture_output=True, timeout=30)
        time.sleep(1)

    failures = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS)} checks, {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
