"""One gate for every tool that needs a browser.

The user chose: body works in THEIR already-open browser, never a test browser.
When no browser is connected we return needs_user with the exact steps — we do
not launch a managed Chromium silently.
"""
from __future__ import annotations


def refusal() -> dict:
    """The single, actionable needs_user answer for a missing browser."""
    return {
        "success": False,
        "status": "needs_user",
        "message": ("your browser is not connected — I will not open a separate test "
                    "browser. Connect the tab you already have open:"),
        "data": {
            "steps": [
                ("In your browser (Chrome, Edge, Brave, Vivaldi or Opera): open "
                 "chrome://extensions (edge://extensions for Edge) and enable Developer mode"),
                "Load unpacked -> select the 'extension' folder of this repository",
                ("Click the bridge icon on the tab you want the body to use -> "
                 "'Connect this tab' (the browser's own debugging bar appears)"),
                ("Run: python -m body_mcp.bridge --allow-extension-id <the id shown> "
                 "-- then the tab is remembered and reattaches after a restart"),
            ],
            "revoke": "click 'Disconnect & forget' in the extension popup at any time",
            "note": ("the body never logs in, types credentials, posts, votes or "
                     "bypasses access controls"),
        },
    }


def connected() -> dict:
    """Live state: {connected, source, tabs}."""
    from . import attach as attach_mod
    from . import bridge as bridge_mod

    if attach_mod.attached_status()["attached"]:
        return {"connected": True, "source": "CDP-attached tab", "tabs": []}
    info = bridge_mod.status()
    if info.get("extension_connected"):
        return {"connected": True, "source": "extension bridge", "tabs": info.get("tabs", [])}
    return {"connected": False, "source": None, "tabs": []}


def required() -> bool:
    """The profile decides: 'allow' (default) = only the user's browser; 'deny' = managed allowed.

    Named as a restrictive capability on purpose: 'deny' means the user chose to
    allow the separate managed browser (tests, headless CI). Default fails closed.
    """
    from . import permissions

    return permissions.load_profile()["capabilities"].get("own_browser_only", "allow") == "allow"


def gate() -> dict | None:
    """None = OK to proceed; otherwise the needs_user refusal to return."""
    if not required():
        return None
    return None if connected()["connected"] else refusal()


def gate_if_browser(actions) -> dict | None:
    """Gate only batches that contain browser-changing steps."""
    kinds = {str(a.get("type", "")) for a in (actions or []) if isinstance(a, dict)}
    if kinds & {"goto", "click", "fill", "type", "press", "scroll", "verify_text",
                "verify_url", "screenshot"}:
        return gate()
    return None
