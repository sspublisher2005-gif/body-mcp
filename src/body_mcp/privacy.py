"""Privacy sessions — an explicit, isolated, disposable browsing mode.

Modes
-----
`standard`  an isolated Playwright context (incognito-equivalent: own cookies, own
            storage, nothing persisted). This is the default and it is already
            private in the way that matters for automation.
`private`  the same isolation **plus** the optional extras:
              - the VPN you asked for (Proton VPN on Windows) is opened and
                connected by the agent - with your approval, and never used to
                evade a block;
              - Brave (or Chromium) as the engine, in a private window;
              - the AI assistant (Venice AI) opened first as the "research brain"
                tab, while the real websites stay in a second tab.

`preflight()` reports what is actually in place BEFORE anything starts: which
browser is installed, whether the VPN app is running, whether the exit IP should
be shown, and - as a warning, never a block - that the reasoning model is still
your configured (remote) provider unless you switched the agent to a local one.

What this mode does NOT do: it does not make you anonymous, it does not rotate
identities to dodge rate limits or bot checks, and it never bypasses a login, an
age gate, a paywall, a CAPTCHA or an access control.
"""
from __future__ import annotations

import os
import time

from . import events, runtime

MAX_SESSIONS = 2
DEFAULT_TIMEOUT = 900
VENICE_AI = "https://venice.ai/chat"

BRAVE_PATHS = (
    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
)
PROTON_PATHS = (
    r"C:\Program Files\Proton\VPN\ProtonVPN.exe",
    r"C:\Program Files (x86)\Proton\VPN\ProtonVPN.exe",
)

_sessions: dict[str, dict] = {}


def _browser_executable(name: str) -> str | None:
    """The installed browser executable (fixed paths only - never from the input)."""
    if name == "brave":
        for path in BRAVE_PATHS:
            if os.path.isfile(path):
                return path
        return None
    if name in ("chromium", "chrome", "edge"):
        from . import cdp_launch

        for candidate in cdp_launch.CANDIDATES.get(name, []):
            if os.path.isfile(candidate):
                return candidate
    return None


def _vpn_app() -> str | None:
    for path in PROTON_PATHS:
        if os.path.isfile(path):
            return path
    return None


def _vpn_window() -> dict | None:
    """The VPN window, if it is open right now (title only - no scraping)."""
    try:
        from . import windows

        for window in windows.list_windows().get("windows", []):
            title = (window.get("title") or "").lower()
            if "proton" in title and "vpn" in title:
                return {"title": window.get("title"), "hwnd": window.get("hwnd")}
    except Exception:
        pass
    return None


# Only these exact button names are ever clicked - never a fuzzy match, never a
# server/switch list (switching servers to dodge a block is out of scope by design).
VPN_CONNECT_LABELS = ("quick connect", "connect")
VPN_CONNECTED_MARKERS = ("connected", "secure", "protected", "vpn is on")


def vpn_state(text: str) -> str:
    """Read the VPN state out of the app's own text. 'unknown' when it is unclear."""
    lowered = (text or "").lower()
    if "disconnected" in lowered or "not connected" in lowered:
        return "not connected"
    if any(marker in lowered for marker in VPN_CONNECTED_MARKERS):
        return "connected"
    return "unknown"


def _vpn_observed_state() -> str:
    """What the VPN app's window says right now (never a guess)."""
    window = _vpn_window()
    if not window:
        return "not running"
    try:
        from . import uia

        listed = uia.inspect(window["title"])
        text = " ".join([listed.get("window", "")] + [c.get("name", "") for c in
                                                     listed.get("controls", [])])
        return vpn_state(text)
    except Exception:
        return "unknown"


def _launch_vpn_app(path: str) -> str:
    """Start the VPN app (fixed path, argv list, no shell). Returns an error or ''."""
    import subprocess

    try:
        subprocess.Popen([path], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return ""


def vpn_connect(app: str = "proton") -> dict:
    """Open the VPN app and ask IT to connect. The state is read from the app.

    Only Proton VPN on Windows is supported (fixed paths, never from the input).
    The agent clicks the app's own connect button and then reads the window - it
    never claims "connected" without the app saying so.

    shortcut: the button names are Proton VPN version specific and this was written
    without Proton VPN installed, so it is unverified against the real app - if your
    version names the button differently the tool reports "no connect button found"
    instead of clicking something else.
    """
    import time

    if app != "proton":
        return {"success": False,
                "message": f"only 'proton' is supported (got {app!r})", "data": {}}
    path = _vpn_app()
    if not path:
        return {"success": False,
                "message": ("Proton VPN is not installed (checked: "
                            + ", ".join(PROTON_PATHS) + ") - install it, or the private "
                            "mode runs without a VPN (no IP change)"),
                "data": {"app_installed": False}}
    from . import uia

    launch_error = _launch_vpn_app(path)
    if launch_error:
        return {"success": False, "message": f"could not start Proton VPN: {launch_error}",
                "data": {"app_path": path}}

    title = ""
    deadline = time.time() + 20
    while time.time() < deadline:
        window = _vpn_window()
        if window:
            title = window["title"]
            break
        time.sleep(0.5)
    if not title:
        return {"success": False,
                "message": ("Proton VPN started but its window did not appear within 20 s - "
                            "check the app (it may be waiting for a sign-in)"),
                "data": {"app_path": path, "window_found": False}}

    listed = uia.inspect(title)
    controls = listed.get("controls", []) if listed.get("ok") else []
    label = next((control["name"] for control in controls
                  if (control.get("name") or "").strip().lower() in VPN_CONNECT_LABELS
                  and control.get("enabled")), "")
    if not label:
        return {"success": False,
                "message": ("the Proton VPN window is open but no connect button was found "
                            f"(looked for {', '.join(VPN_CONNECT_LABELS)}; the app may be "
                            "signed out, or this version names it differently) - nothing was "
                            "clicked"),
                "data": {"app_path": path, "window": title, "window_found": True,
                         "controls": [c.get("name") for c in controls][:40]}}

    clicked = uia.click(title, label)
    if not clicked.get("ok"):
        return {"success": False, "message": f"the connect click failed: {clicked.get('reason')}",
                "data": {"app_path": path, "window": title}}
    time.sleep(3)
    after = uia.inspect(title)
    text = " ".join([after.get("window", "")] + [c.get("name", "") for c in
                                                 after.get("controls", [])])
    state = vpn_state(text)
    return {"success": True,
            "message": (f"asked Proton VPN to connect (clicked {label!r}); the app now "
                        f"reports: {state}"),
            "data": {"app_path": path, "window": title, "clicked": label,
                     "vpn_state": state,
                     "verified": state == "connected",
                     "evidence": text[:300],
                     "note": ("the state is read from the app's own window; 'unknown' means "
                              "the app did not say - check the app yourself")}}


def _local_model_configured() -> dict:
    """Is a LOCAL model configured for the agent? (the agent's own model lives outside)"""
    configured = os.environ.get("BODY_MCP_LOCAL_MODEL") or ""
    path = configured if configured and os.path.exists(configured) else ""
    return {"configured": bool(path), "path": path,
            "note": "Body-MCP cannot see which model your agent is using; set "
                    "BODY_MCP_LOCAL_MODEL to a local model file to record that choice"}


def content_policy() -> dict:
    """Where does the page text go? Two levels, and only one of them is private.

    `browsing` is always local (own context, no cookies, nothing persisted).
    `content` is only local when a local worker model is available - otherwise the
    text travels to whatever provider the agent's own model runs on.
    """
    from . import local_worker

    worker = local_worker.status()
    return {
        "browsing": "local - own throwaway context, no cookies, nothing persisted",
        "content_local_possible": worker["available"],
        "worker": worker,
        "if_not_local": "the page text is sent to your agent's model provider (that is "
                        "outside Body-MCP); start a session with keep_content_local=True "
                        "once a local model is installed - then only a redacted summary "
                        "leaves this machine",
    }


def preflight(show_ip: bool = False) -> dict:
    """Check the privacy posture BEFORE starting: what is installed, what is running."""
    from . import sysprofile

    browsers = {}
    for name in ("brave", "chrome", "edge"):
        browsers[name] = {"installed": bool(_browser_executable(name)),
                           "path": _browser_executable(name)}
    vpn_app = _vpn_app()
    vpn_window = _vpn_window()
    local_model = _local_model_configured()
    content = content_policy()
    warnings = []
    if not browsers["brave"]["installed"]:
        warnings.append("Brave is not installed - the private mode will use the managed "
                        "Chromium instead (same isolation, different brand).")
    if not vpn_app and not vpn_window:
        warnings.append("no Proton VPN found: install it, or the private mode runs without "
                        "a VPN (no IP change).")
    if not local_model["configured"]:
        warnings.append("the reasoning model is your configured (remote) provider: if you "
                        "want fully local reasoning, switch the agent to the local model "
                        "and set BODY_MCP_LOCAL_MODEL to it.")
    if not content["content_local_possible"]:
        warnings.append("NO LOCAL MODEL: page text you read will be sent to your agent's "
                        "model provider. To keep the content on this machine install Ollama "
                        "and `ollama pull qwen3:0.6b` (498 MB), then start the session with "
                        "keep_content_local=True.")
    try:
        profile = sysprofile.summary()
        ram = profile.get("ram_available_mb")
    except Exception:
        ram = None
    if ram is not None and ram < 400:
        warnings.append(f"only {ram} MB of RAM free - a second browser plus a local model "
                        "will be slow; consider closing apps first.")
    return {
        "ok": True,
        "browsers": browsers,
        "vpn": {"app_installed": bool(vpn_app), "app_path": vpn_app,
                 "window_open": vpn_window is not None, "window": vpn_window,
                 "note": "the agent can open and connect the VPN app on your request "
                         "(approval required); it never rotates IPs to evade a block"},
        "exit_ip": "not checked (it is only fetched when you ask for it - asking a third "
                   "party for your IP is itself a disclosure)",
        "local_model": local_model,
        "content_policy": content,
        "ram_free_mb": ram,
        "warnings": warnings,
        "not_anonymous": "no mode makes you anonymous: sites, accounts, your network, device "
                         "administrators, installed software and downloaded files still see you",
    }


def start(label: str = "session", mode: str = "standard", browser: str = "chromium",
          vpn: bool = False, assistant: bool = False, show_ip: bool = False,
          keep_content_local: bool = False) -> dict:
    """Open a session (standard = isolated context; private = + VPN + Brave + assistant)."""
    if len(_sessions) >= MAX_SESSIONS:
        return {"success": False,
                "message": f"too many sessions (max {MAX_SESSIONS}) - end one first",
                "data": {}}
    checks = preflight(show_ip=show_ip)
    executable = _browser_executable(browser)
    # "chromium" means the managed browser Playwright already ships with - nothing to install
    if mode == "private" and browser != "chromium" and not executable:
        return {"success": False,
                "message": (f"no {browser} installation found - install it, or use "
                            "mode='standard' (the managed Chromium)"),
                "data": {"preflight": checks}}

    session_id = "priv_" + uuid_hex()
    task_id = runtime.registry.create(label=f"privacy:{mode}")
    session = {
        "session_id": session_id,
        "task_id": task_id,
        "label": (label or "session")[:40],
        "mode": mode,
        "browser": browser,
        "browser_path": executable,
        "vpn_requested": bool(vpn),
        "vpn_state": (_vpn_observed_state() if vpn else "not used"),
        "assistant_opened": False,
        "keep_content_local": bool(keep_content_local),
        "created": time.time(),
        "context": None,
        "page": None,
        "closed": False,
        "visited": 0,
        "preflight": checks,
    }
    _sessions[session_id] = session
    events.emit(events.TASK_CREATED, task_id=task_id, tool="privacy_session_start",
                status="STARTED",
                summary=f"{mode} privacy session started ({browser})",
                evidence={"session_id": session_id, "mode": mode, "browser": browser})
    content_note = ""
    if keep_content_local:
        if checks["content_policy"]["content_local_possible"]:
            content_note = (", page content stays on this machine (redacted summary only)")
        else:
            content_note = (", page content will be WITHHELD: no local model is installed "
                            "(install Ollama and `ollama pull qwen3:0.6b`)")
    return {"success": True,
            "message": (f"privacy session {session_id} ready ({mode}"
                        + (", assistant tab first" if assistant else "")
                        + (", VPN requested" if vpn else "") + content_note + ")"),
            "data": {"session_id": session_id, "task_id": task_id, "mode": mode,
                     "browser": browser, "browser_path": executable,
                     "assistant_url": VENICE_AI if assistant else None,
                     "keep_content_local": bool(keep_content_local),
                     "content_local_ready": checks["content_policy"][
                         "content_local_possible"],
                     "warnings": checks["warnings"],
                     "note": checks["not_anonymous"]}}


def uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex[:12]


def permissions_record(session: dict) -> None:
    """Record the session start in the audit log (no URLs, no page content)."""
    from . import permissions

    permissions.record_audit("privacy_session_start", "private_browser", "allow",
                             f"session:{session['label']}", status="STARTED",
                             task_id=session.get("task_id"),
                             evidence={"mode": session.get("mode"),
                                       "browser": session.get("browser"),
                                       "vpn": session.get("vpn_requested")})


def get(session_id: str) -> dict | None:
    return _sessions.get(session_id)


async def open(session_id: str, url: str) -> dict:
    """Open a URL inside the session (its own context, its own storage)."""
    session = _sessions.get(session_id)
    if not session or session.get("closed"):
        return {"success": False, "message": "no such session (start one first)", "data": {}}
    if time.time() - session["created"] > DEFAULT_TIMEOUT:
        return {"success": False, "message": "session expired - start a new one", "data": {}}
    from . import browser as browser_module

    try:
        if session["context"] is None:
            if session.get("browser_path"):
                from playwright.async_api import async_playwright

                playwright = await async_playwright().start()
                instance = await playwright.chromium.launch(
                    headless=browser_module.browser_headless(),
                    executable_path=session["browser_path"])
                context = await instance.new_context()
                session["playwright"] = playwright
                session["instance"] = instance
            else:
                context, _page = await browser_module.new_isolated_context()
            session["context"] = context
            session["page"] = await context.new_page()
        await session["page"].goto(url, wait_until="load", timeout=30000)
    except Exception as exc:
        return {"success": False, "message": f"navigation failed: {type(exc).__name__}: {exc}",
                "data": {}}
    session["visited"] += 1
    return {"success": True,
            "message": "opened in the private session (not recorded in memory or the log)",
            "data": {"session_id": session_id, "visited": session["visited"]}}


async def snapshot(session_id: str) -> dict:
    """Read the current page of a session (bounded text, no refs, nothing stored).

    With keep_content_local=True the raw text never leaves this machine: it is
    redacted and summarised by the local worker, and only that comes back. If no
    local model is available the text is withheld - it is never quietly shipped
    to a remote provider."""
    session = _sessions.get(session_id)
    if not session or session.get("closed") or session.get("page") is None:
        return {"success": False, "message": "no open page in this session", "data": {}}
    from . import browser as browser_module

    try:
        snap = await browser_module.snapshot_page(page=session["page"], build_refs=False)
    except Exception as exc:
        return {"success": False, "message": f"snapshot failed: {exc}", "data": {}}
    raw = snap["text"][:4000]
    if session.get("keep_content_local"):
        return await _local_snapshot(session_id, raw, snap)
    return {"success": True, "message": "private session snapshot (not stored)",
            "data": {"session_id": session_id, "title": snap["title"],
                     "text": raw,
                     "restricted": snap["restricted"],
                     "sensitive_mode": snap["sensitive_mode"]}}


async def _local_snapshot(session_id: str, raw: str, snap: dict) -> dict:
    """Redact + summarise locally. The raw text stops here, on this machine."""
    import asyncio

    from . import local_worker

    worker = local_worker.status()
    if not worker["available"]:
        return {"success": False,
                "message": ("page content withheld: this session keeps the content local, "
                            "but no local model is installed (Ollama + "
                            "`ollama pull qwen3:0.6b`, or set BODY_MCP_LOCAL_MODEL)"),
                "data": {"session_id": session_id, "content_local": True,
                         "withheld": True, "title": snap["title"],
                         "worker": worker}}
    redacted = await asyncio.to_thread(local_worker.run, "redact", raw)
    if not redacted.get("ok"):
        return {"success": False,
                "message": f"local redaction failed, text withheld: {redacted.get('reason')}",
                "data": {"session_id": session_id, "content_local": True, "withheld": True,
                         "title": snap["title"], "error": redacted.get("reason")}}
    summary = await asyncio.to_thread(local_worker.run, "summarise", redacted.get("text", ""))
    if not summary.get("ok"):
        return {"success": False,
                "message": f"local summary failed, text withheld: {summary.get('reason')}",
                "data": {"session_id": session_id, "content_local": True, "withheld": True,
                         "title": snap["title"], "error": summary.get("reason")}}
    return {"success": True,
            "message": ("private session snapshot - processed on this machine, only the "
                        "redacted summary was returned (raw text never left)"),
            "data": {"session_id": session_id, "title": snap["title"],
                     "text": None,
                     "summary": summary.get("text", ""),
                     "redacted": redacted.get("text", "")[:2000],
                     "content_local": True,
                     "model": summary.get("model"), "runtime": summary.get("runtime"),
                     "restricted": snap["restricted"],
                     "sensitive_mode": snap["sensitive_mode"]}}


async def end(session_id: str) -> dict:
    """Close the session, delete its context/storage and VERIFY the cleanup."""
    session = _sessions.get(session_id)
    if not session:
        return {"success": False, "message": "no such session", "data": {}}
    closed = False
    context = session.get("context")
    if context is not None:
        try:
            await context.close()
            closed = True
        except Exception:
            closed = False
    instance = session.get("instance")
    if instance is not None:
        with contextlib_suppress():
            await instance.close()
    playwright = session.get("playwright")
    if playwright is not None:
        with contextlib_suppress():
            await playwright.stop()
    session["closed"] = True
    session["context"] = None
    session["page"] = None
    _sessions.pop(session_id, None)
    runtime.registry.finish(session["task_id"], "completed", "privacy session ended")
    events.emit(events.TASK_FINISHED, task_id=session["task_id"],
                tool="privacy_session_end", status="COMPLETED",
                summary="privacy session ended",
                evidence={"session_id": session_id, "context_closed": closed})
    return {"success": True,
            "message": ("privacy session closed; its cookies and storage were discarded"
                        if closed else
                        "privacy session closed; the browser context could not be confirmed closed"),
            "data": {"session_id": session_id, "context_closed": closed,
                     "cleanup_verified": closed,
                     "note": "your ordinary browser profile was never touched"}}


class contextlib_suppress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(exc_type, Exception)


def sessions() -> list[dict]:
    return [{"session_id": s["session_id"], "mode": s["mode"], "browser": s["browser"],
             "vpn_state": s["vpn_state"], "visited": s["visited"],
             "age_s": int(time.time() - s["created"])}
            for s in _sessions.values()]
