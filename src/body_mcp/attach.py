"""Connect to the user's CURRENT browser tab via Chrome DevTools Protocol (loopback).

Honest rules for this module:
  - Chrome/Edge must run with --remote-debugging-port (loopback). Launch it via
    `python -m body_mcp.cdp_launch --browser chrome [--port 9222]` (user's act).
  - The CDP endpoint is loopback-only and UNAUTHENTICATED — while open, ANY local
    process can drive your browser. Attach when needed; detach when done; restart
    the browser normally afterwards to drop the debug port.
  - Deliberate user authorization required: consent + scoped reflex_ask approval for
    the attach/select actions. Titles/URLs of tabs are disclosed only after attach approval.
  - DevTools windows are never candidates. We never touch unselected tabs, never close
    your browser, never read your profile settings. detach_browser() closes OUR
    connection only — your browser keeps running.
"""
import time
import urllib.parse

from . import events, permissions

_attach = {
    "playwright": None,
    "browser": None,
    "page": None,
    "candidate_pages": None,   # ordered list matching the indices returned to the user
    "endpoint": None,
    "tab_title": None,
    "attached_at": None,
}


def _valid_endpoint(endpoint: str) -> dict:
    try:
        parts = urllib.parse.urlsplit(endpoint)
    except Exception:
        return {"ok": False, "reason": "unparseable endpoint URL"}
    host = (parts.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        return {"ok": False,
                "reason": f"refusing non-loopback CDP endpoint host {host!r} (loopback only)"}
    try:
        port = parts.port or 9222
        if port < 1024 or port > 65535:
            return {"ok": False, "reason": f"refusing suspicious CDP port {port}"}
    except ValueError:
        return {"ok": False, "reason": "invalid CDP port"}
    if (parts.scheme or "").lower() != "http":
        return {"ok": False, "reason": "refusing non-http CDP endpoint (loopback http only)"}
    return {"ok": True, "port": port}


async def _authorize(tool: str, target: object, action: str,
                     task_id: str | None = None):
    """One authorization decision for the chrome_attach capability.

    The endpoint lives in `target`, never in the url slot: the spec we hand back
    for approval must match the spec we consume at execution time, byte for byte.
    """
    decision = await permissions.authorize(
        "chrome_attach", tool=tool, target=target, risk="high",
        action=action, url=None, task_id=task_id)
    if not decision.allowed:
        permissions.record_audit(tool, "chrome_attach", decision.decision, target)
    return decision


def _auth_denied(tool: str, target, decision):
    spec = permissions.required_action_spec(tool, "chrome_attach", target, None, None)
    return {"success": False,
            "message": decision.message,
            "data": {"permission": decision.decision, "required_action": spec}}


async def attach(endpoint: str, tab: str | None = None) -> dict:
    """Attach to your current browser.

    Without `tab`: connect, list your real tabs (by title/URL), keep the session open
    for select_tab(). Requires one scoped approval (action spec is returned for you to
    approve via reflex_ask).
    With `tab`: select that tab immediately (index or unique url/title substring);
    requires its own scoped approval.
    """
    verdict = _valid_endpoint(endpoint)
    if not verdict["ok"]:
        return {"success": False, "message": verdict["reason"], "data": {}}

    # attaching/listing is one authorization decision; the target shows exactly
    # what the user is approving (endpoint, and the tab when one is requested)
    attach_target = f"cdp:{endpoint}" if tab is None else f"cdp:{endpoint}#{tab}"
    decision = await _authorize("attach_browser", attach_target,
                                "list and attach to your browser's tabs")
    if not decision.allowed:
        return _auth_denied("attach_browser", attach_target, decision)

    from playwright.async_api import async_playwright

    await _disconnect(silent=True)  # never leak a previous session

    playwright = None
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.connect_over_cdp(endpoint, timeout=8000)
    except Exception as exc:
        if playwright is not None:
            import contextlib
            with contextlib.suppress(Exception):
                await playwright.stop()
        return {"success": False,
                "message": (f"cannot reach CDP at {endpoint}: {type(exc).__name__}: {exc}. "
                            "Is the browser running with --remote-debugging-port? "
                            "Launch it: python -m body_mcp.cdp_launch --browser chrome"),
                "data": {"endpoint": endpoint}}

    tabs = []
    pages = []
    for context in browser.contexts:
        for page in context.pages:
            title = ""
            try:
                title = await page.title()
            except Exception:
                continue
            url = page.url or ""
            if url.startswith("chrome-devtools://") or title.startswith("DevTools"):
                continue  # never candidate tabs
            tabs.append({"index": len(tabs), "url": url, "title": title})
            pages.append(page)

    if not tabs:
        await _disconnect(silent=True)
        return {"success": False,
                "message": f"CDP connected at {endpoint} but no candidate tabs were found",
                "data": {"endpoint": endpoint}}

    _attach.update(playwright=playwright, browser=browser, browser_context=None,
                   page=None, candidate_pages=pages, endpoint=endpoint,
                   tab_title=None, attached_at=None)

    if tab is not None:
        return await select_tab(tab, _preapproved=(tab, endpoint))

    permissions.record_audit("attach_browser", "chrome_attach", "allow", endpoint)
    events.emit(events.BROWSER_CONNECTED, tool="attach_browser", status="CONNECTED",
                summary=f"attached to {len(tabs)} tab(s) at {endpoint}",
                evidence={"endpoint": endpoint, "tabs": len(tabs)})
    return {"success": True,
            "message": (f"connected to {len(tabs)} tab(s). Pick one with "
                        "select_tab('<index or unique url/title substring>'). "
                        "Contents are not read until you select a tab."),
            "data": {"status": "awaiting_tab_selection", "endpoint": endpoint,
                     "tabs": tabs}}


async def _current_tabs_info() -> list[dict]:
    pages = _attach.get("candidate_pages") or []
    tabs = []
    for i, page in enumerate(pages):
        try:
            title = await page.title()
        except Exception:
            title = "unknown"
        try:
            url = page.url or ""
        except Exception:
            url = "unknown"
        tabs.append({"index": i, "url": url, "title": title})
    return tabs

async def select_tab(selector: str, _preapproved=None) -> dict:
    """Select one tab to drive. Requires a scoped approval unless called via attach(tab=...)."""
    pages = _attach.get("candidate_pages") or []
    tabs_info = await _current_tabs_info()
    if not pages:
        return {"success": False,
                "message": "not attached — call attach_browser(endpoint) first",
                "data": {}}

    if _preapproved is None:
        decision = await _authorize("select_tab", f"tab:{selector}",
                                    f"drive tab {selector!r}")
        if not decision.allowed:
            return _auth_denied("select_tab", f"tab:{selector}", decision)

    selector = (selector or "").strip()
    selected_idx = None
    if selector.isdigit():
        idx = int(selector)
        if 0 <= idx < len(pages):
            selected_idx = idx
    if selected_idx is None:
        wanted = selector.lower()
        matches = [i for i, t in enumerate(tabs_info)
                   if wanted and (wanted in t["url"].lower() or wanted in t["title"].lower())]
        if len(matches) != 1:
            return {"success": False,
                    "message": (f"tab selector {selector!r} matches {len(matches)} tab(s) — "
                                "use a unique substring of url/title or the tab index"),
                    "data": {"candidates": tabs_info}}
        selected_idx = matches[0]

    page = pages[selected_idx]
    title = tabs_info[selected_idx]["title"]
    _attach.update(page=page, candidate_pages=None, tab_title=title, attached_at=time.time())

    from . import browser as _browser
    _browser._wire_navigation_listener(page)
    _browser._bump_navigation()
    permissions.record_audit("select_tab", "chrome_attach", "allow", tabs_info[selected_idx]["url"])
    return {"success": True,
            "message": f"driving tab: {title} — hands/eyes now act on it. detach_browser() disconnects.",
            "data": {"status": "attached",
                     "tab": {"url": tabs_info[selected_idx]["url"], "title": title}}}


def current_page():
    """The attached page, or None. Called by browser.ensure_page()."""
    return _attach.get("page")


async def detach() -> dict:
    """Close OUR CDP connection only. Never closes your browser, tabs, or profile."""
    if _attach.get("page") is None and _attach.get("browser") is None:
        return {"success": True, "message": "not attached — nothing to detach", "data": {}}
    title = _attach.get("tab_title") or "tab"
    await _disconnect(silent=False)
    from . import browser as _browser
    _browser._bump_navigation()
    permissions.record_audit("detach_browser", "chrome_attach", "allow", title)
    events.emit(events.BROWSER_DISCONNECTED, tool="detach_browser", status="DISCONNECTED",
                summary=f"disconnected from {title}")
    return {"success": True,
            "message": f"disconnected from {title} — CDP session closed. "
                       "Your browser is still running; restart it normally to drop the debug port.",
            "data": {"status": "detached"}}


def attached_status() -> dict:
    """Current attachment state. Synchronous on purpose: the console polls it."""
    page = _attach.get("page")
    if page is None:
        return {"attached": False, "tab": None}
    try:
        if page.is_closed():
            return {"attached": False, "tab": None}
        return {"attached": True,
                "url": page.url,
                "title": _attach.get("tab_title") or "",
                "endpoint": _attach.get("endpoint"),
                "attached_seconds": int(time.time() - (_attach.get("attached_at") or time.time()))}
    except Exception:
        return {"attached": False, "tab": None}


def status_text() -> dict:
    snap = attached_status()
    if snap["attached"]:
        return {"success": True,
                "message": f"attached to {snap['title']} ({snap['url']})",
                "data": snap}
    return {"success": True,
            "message": "not attached — the managed Playwright browser is in use",
            "data": snap}


async def _disconnect(silent: bool = False):
    import contextlib

    from . import browser as _browser
    with contextlib.suppress(Exception):
        if _attach.get("browser") is not None:
            await _attach["browser"].close()
    with contextlib.suppress(Exception):
        if _attach.get("playwright") is not None:
            await _attach["playwright"].stop()
    with contextlib.suppress(Exception):
        _browser._bump_navigation()
    _attach.update(playwright=None, browser=None, page=None, candidate_pages=None,
                   endpoint=None, tab_title=None, attached_at=None)
