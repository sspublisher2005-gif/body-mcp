"""What can Body-MCP see in your Edge right now - WITHOUT a debug port.

Two separate questions:
  1. can body-dev DRIVE it?  -> needs a CDP port (yours has none: Chromium >= 136
     ignores --remote-debugging-port when the default profile is used).
  2. can it READ the window titles? -> yes, read-only, through Win32 - no port needed.
"""
from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes as wt
import sys
import urllib.request

with contextlib.suppress(Exception):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

user32 = ctypes.windll.user32


def visible_windows() -> list[dict]:
    out: list[dict] = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value
        if not title:
            return True
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append({"hwnd": int(hwnd), "pid": pid.value, "title": title})
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)
    return out


def main() -> int:
    print("=== 1. can body-dev DRIVE this Edge? (CDP) ===")
    for port in (9222, 9333):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1):
                print(f"  port {port}: OPEN -> attach_browser() would work")
        except Exception:
            print(f"  port {port}: closed -> attach_browser() cannot connect")

    print("\n=== 2. what is open in it (read-only Win32, no port needed) ===")
    windows = visible_windows()
    edge = [w for w in windows if "edge" in w["title"].lower()
            or w["pid"] in {p for p in _edge_pids()}]
    if not edge:
        print("  no Edge window found")
    for w in edge:
        print(f"  hwnd={w['hwnd']} pid={w['pid']} title={w['title']!r}")
    other = [w for w in windows if w not in edge][:8]
    if other:
        print("\n  other visible windows (not Edge):")
        for w in other:
            print(f"    pid={w['pid']} title={w['title'][:70]!r}")
    return 0


def _edge_pids() -> set[int]:
    import subprocess

    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq msedge.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, timeout=30)
    pids = set()
    for line in (out.stdout or "").splitlines():
        parts = [p.strip('" ') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.add(int(parts[1]))
    return pids


if __name__ == "__main__":
    raise SystemExit(main())
