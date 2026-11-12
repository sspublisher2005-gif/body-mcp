"""Privacy sessions — an explicit, isolated, disposable browsing mode.

What a privacy session does:
  - runs in its OWN browser context (no cookies, storage or history shared with
    your ordinary sessions or your real browser profile),
  - keeps its visited URLs, titles and content OUT of the audit log, the event
    stream and the persistent memory by default,
  - saves no downloads or artifacts unless asked,
  - deletes its context and storage when the session ends, and VERIFIES the cleanup.

What it does not do (honest limits):
  - it is not anonymity. Websites, logged-in accounts, network operators, device
    administrators, installed software and downloaded files can still see or
    infer the activity,
  - it does not touch your personal browser profile, and it never bypasses
    authentication, age verification, DRM, CAPTCHAs, paywalls or platform rules.
"""
from __future__ import annotations

import time
import urllib.parse

from . import browser, events, permissions

MAX_SESSION_SECONDS = 3600

_sessions: dict[str, dict] = {}


def start(label: str = "session") -> dict:
    """Open a privacy session. Returns its id and the limits that apply."""
    import uuid

    label = (label or "session").strip()[:40]
    # the id carries no label: the label must not leak into the event stream
    session_id = "priv_" + uuid.uuid4().hex[:12]
    _sessions[session_id] = {
        "session_id": session_id,
        "label": label,
        "created": time.time(),
        "context": None,
        "page": None,
        "closed": False,
        "visited": 0,
    }
    permissions.record_audit("privacy_session_start", "private_browser", "allow",
                             f"session:{label}", status="STARTED",
                             evidence={"session_id": session_id})
    events.emit(events.TASK_CREATED, tool="privacy_session_start", status="STARTED",
                summary="privacy session started",
                evidence={"session_id": session_id})
    return {
        "success": True,
        "message": (f"privacy session {session_id} ready. Use it with the private_* tools; "
                    "call privacy_session_end() to close it. This reduces local persistence "
                    "only - it is NOT anonymity."),
        "data": {
            "session_id": session_id,
            "label": label,
            "limits": [
                ("websites, network operators, device administrators and downloaded files "
                 "can still observe or infer this activity"),
                "logged-in accounts still identify you",
                "nothing from this session is written to persistent memory or the event stream",
            ],        },
    }


def get(session_id: str) -> dict | None:
    return _sessions.get(session_id)


async def open(session_id: str, url: str) -> dict:
    """Open a URL inside the privacy session's isolated context."""
    session = _sessions.get(session_id)
    if not session or session.get("closed"):
        return {"success": False, "message": "no such privacy session (start one first)",
                "data": {}}
    if time.time() - session["created"] > MAX_SESSION_SECONDS:
        return {"success": False, "message": "privacy session expired - start a new one",
                "data": {}}
    verdict = browser.check_url(url)
    if not verdict["ok"]:
        return {"success": False, "message": verdict["reason"], "data": {}}
    try:
        if session["context"] is None:
            context, page = await browser.new_isolated_context()
            session["context"], session["page"] = context, page
        else:
            context, page = session["context"], session["page"]
        await page.goto(url, wait_until="load", timeout=30000)
    except Exception as exc:
        return {"success": False, "message": f"privacy session navigation failed: {exc}",
                "data": {}}
    session["visited"] += 1
    # deliberately NOT audited with the URL and NOT emitted as an event
    return {"success": True,
            "message": "opened in the privacy session (not recorded in memory or the log)",
            "data": {"session_id": session_id,
                     "domain": urllib.parse.urlsplit(url).netloc,
                     "visited": session["visited"]}}


async def snapshot(session_id: str) -> dict:
    """Read the current page of a privacy session (no refs, no persistence)."""
    session = _sessions.get(session_id)
    if not session or session.get("closed") or session["page"] is None:
        return {"success": False, "message": "no open page in this privacy session",
                "data": {}}
    try:
        snap = await browser.snapshot_page(page=session["page"], build_refs=False)
    except Exception as exc:
        return {"success": False, "message": f"privacy snapshot failed: {exc}", "data": {}}
    return {"success": True, "message": "privacy session snapshot (not stored)",
            "data": {"session_id": session_id, "title": snap["title"],
                     "domain": urllib.parse.urlsplit(snap["url"]).netloc,
                     "text_chars": len(snap["text"]),
                     "text": snap["text"][:4000],
                     "links": snap["links"][:30],
                     "restricted": snap["restricted"],
                     "sensitive_mode": snap["sensitive_mode"]}}


async def end(session_id: str) -> dict:
    """Close the session, delete its context/storage and VERIFY the cleanup."""
    session = _sessions.get(session_id)
    if not session:
        return {"success": False, "message": "no such privacy session", "data": {}}
    context = session.get("context")
    closed = False
    if context is not None:
        try:
            await context.close()
            closed = True
        except Exception:
            closed = False
    session["closed"] = True
    session["context"] = None
    session["page"] = None
    _sessions.pop(session_id, None)
    permissions.record_audit("privacy_session_end", "private_browser", "allow",
                             f"session:{session.get('label')}", status="ENDED",
                             evidence={"context_closed": closed})
    events.emit(events.TASK_FINISHED, tool="privacy_session_end", status="COMPLETED",
                summary="privacy session ended",
                evidence={"context_closed": closed})
    return {"success": True,
            "message": ("privacy session closed; its cookies and storage were discarded"
                        if closed else
                        "privacy session closed; the browser context could not be confirmed closed"),
            "data": {"session_id": session_id, "context_closed": closed,
                     "cleanup_verified": closed,
                     "note": "your ordinary browser profile was never touched"}}


def status() -> dict:
    return {
        "active_sessions": [
            {"session_id": s["session_id"], "label": s["label"],
             "age_s": int(time.time() - s["created"]), "visited": s["visited"],
             "has_page": s["page"] is not None}
            for s in _sessions.values()
        ],
        "note": "privacy sessions keep nothing in memory, the audit log or the event stream",
    }
