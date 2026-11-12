"""Open a URL in the USER'S OWN browser (not Body-MCP's browser).

Body-MCP deliberately has no shell tool, so it cannot spawn arbitrary commands. This is
the narrow, safe exception:

  - only http/https URLs,
  - the browser executable comes from a FIXED table (never from the tool input), so
    there is no "run this program" hole,
  - the URL is passed as its own argv element - no shell, no string building,
  - the operating system opens it in the browser you already have running (a new tab
    in that very window).

That is what makes "open YouTube in my Chrome" possible from an agent session:
  - Body-MCP's own Chromium (Chrome for Testing) is a SEPARATE browser and stays the
    controlled one,
  - your everyday Chrome/Edge gets the URL as a new tab.
"""
from __future__ import annotations

import os
import subprocess
import urllib.parse
import webbrowser

ALLOWED_SCHEMES = ("http", "https")

BROWSERS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "brave": [
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
    ],
}


def find_browser(name: str) -> str | None:
    """The executable for a known browser name (fixed paths only)."""
    if not name:
        return None
    candidates = BROWSERS.get(name.lower())
    if not candidates:
        return None
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def open_external(url: str, browser: str = "") -> dict:
    """Hand an http/https URL to the user's own browser (a new tab)."""
    raw = (url or "").strip()
    if not raw:
        return {"success": False, "message": "no URL given", "data": {}}
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return {"success": False,
                "message": f"refusing scheme {parsed.scheme!r} - only http and https are handed "
                           "to the browser",
                "data": {"url": raw}}
    if not parsed.netloc:
        return {"success": False, "message": "that URL has no host", "data": {"url": raw}}

    if browser:
        executable = find_browser(browser)
        if not executable:
            return {"success": False,
                    "message": f"could not find {browser} (known: {', '.join(sorted(BROWSERS))})",
                    "data": {"url": raw, "browser": browser}}
        try:
            subprocess.Popen([executable, raw], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as exc:
            return {"success": False,
                    "message": f"could not start {browser}: {type(exc).__name__}: {exc}",
                    "data": {"url": raw, "browser": browser}}
        return {"success": True,
                "message": f"opened in {browser} (a new tab in the window you already have open)",
                "data": {"url": raw, "browser": browser, "executable": executable,
                         "note": "Body-MCP's own browser is separate; this is your everyday browser"}}

    try:
        opened = webbrowser.open(raw, new=2, autoraise=False)
    except Exception as exc:
        return {"success": False,
                "message": f"could not open the browser: {type(exc).__name__}: {exc}",
                "data": {"url": raw}}
    return {"success": True,
            "message": "the URL was handed to your default browser (a new tab)",
            "data": {"url": raw, "opened": bool(opened),
                     "note": "Body-MCP's own browser is separate; this is your everyday browser"}}
