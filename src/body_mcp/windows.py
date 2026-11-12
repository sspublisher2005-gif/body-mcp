"""Read-only view of the visible windows (no debug port required).

This is the part of "your own browser" that works today: Body-MCP can see which
windows are open (title, process, position) without any debugging port, using plain
Win32 calls. It cannot click them - for that, the browser needs a sanctioned
connection (a debug port on a separate profile, or the extension bridge).

Only window TITLES are read. Nothing is captured, no screenshot is taken, no window
content is opened, and nothing is stored.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

MAX_WINDOWS = 60
MAX_TITLE = 200

_user32 = None


def _api():
    global _user32
    if _user32 is None:
        try:
            _user32 = ctypes.windll.user32
        except Exception:
            return None
    return _user32


def list_windows() -> dict:
    """Visible top-level windows: title, owning process, position, size."""
    api = _api()
    if api is None:
        return {"ok": False, "reason": "window enumeration is only available on Windows"}
    out: list[dict] = []
    proc_type = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def callback(hwnd, _lparam):
        if len(out) >= MAX_WINDOWS:
            return False
        if not api.IsWindowVisible(hwnd):
            return True
        length = api.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        api.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.strip()
        if not title:
            return True
        pid = wt.DWORD()
        api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        rect = wt.RECT()
        api.GetWindowRect(hwnd, ctypes.byref(rect))
        out.append({"hwnd": int(hwnd), "pid": int(pid.value), "title": title[:MAX_TITLE],
                    "left": rect.left, "top": rect.top,
                    "width": rect.right - rect.left, "height": rect.bottom - rect.top})
        return True

    try:
        api.EnumWindows(proc_type(callback), 0)
    except Exception as exc:
        return {"ok": False, "reason": f"window enumeration failed: {exc}"}
    return {"ok": True, "windows": out, "count": len(out),
            "note": "titles only - no content is read and nothing is stored"}


def browser_windows() -> dict:
    """The visible windows that look like a browser (Edge, Chrome, Firefox)."""
    result = list_windows()
    if not result.get("ok"):
        return result
    hints = (" - personal - microsoft", " - microsoft", "google chrome", "mozilla firefox",
             "microsoft\u200b edge")
    browsers = []
    for window in result["windows"]:
        title = window["title"].lower()
        if any(hint in title for hint in hints) or "edge" in title or "chrome" in title:
            browsers.append(window)
    return {"ok": True, "browsers": browsers,
            "note": "a browser without a debug port can be SEEN but not driven; "
                    "body-dev can drive it with a separate --user-data-dir or the extension bridge"}
