"""Lessons learned from failures - the "if it failed, mean something and fix it" loop.

Every notable failure is recorded as a **proposed** lesson (verified = False until a
human or a successful retry confirms it). Before the next attempt the agent can ask
for the lessons that apply, so it does not walk into the same wall twice.

Where the lessons live: the same local memory store as everything else
(`memory.py`), scope `workflow`, type `lesson` - one system, not two.
"""
from __future__ import annotations

from . import memory

SCOPE = "workflow"

# stable error codes -> what usually fixes them (the hint travels with the failure)
HINTS = {
    "STALE_REF": "the page was re-scanned or navigated - call eyes_see_browser() again "
                  "and use the NEW refs",
    "TARGET_AMBIGUOUS": "more than one element matched - use the ref from the latest "
                        "eyes_see_browser() call",
    "PERMISSION_DENIED": "the capability is denied in permissions.json - ask the user, "
                         "do not look for another route",
    "APPROVAL_REQUIRED": "pass data.required_action to reflex_ask(action=...) and retry "
                         "with the SAME task_id",
    "POSTCONDITION_FAILED": "the page changed the value - read the field again before "
                            "typing",
    "BLOCKED_BY_CAPTCHA": "a human must complete the challenge - never retry",
    "BLOCKED_BY_RATE_LIMIT": "wait for the cooldown, then retry once",
    "NO_OCR_ENGINE": "install Tesseract (winget install -e --id UB-Mannheim.TesseractOCR)",
    "BROWSER_DISCONNECTED": "the browser went away - re-attach or let the server relaunch it",
    "TIMEOUT": "the step was slow - raise the step timeout or narrow the action",
    "ELEMENT_NOT_FOUND": "the element is gone - re-read the page",
}

MAX_LESSONS = 60


def hint_for(error_code: str | None, message: str = "") -> str:
    """The recovery hint for a failure (from the code, then from the message)."""
    if error_code and error_code in HINTS:
        return HINTS[error_code]
    lowered = (message or "").lower()
    squeezed = lowered.replace(" ", "").replace("_", "")
    for code, hint in HINTS.items():
        needle = code.replace("_", "").lower()
        if needle in lowered or needle in squeezed:
            return hint
    return ""


def record_failure(tool: str, error_code: str, target: str, message: str = "",
                   fix: str = "") -> dict:
    """Store a proposed lesson about a failure (never a secret, never a page dump)."""
    hint = fix or hint_for(error_code, message)
    title = f"{tool}: {error_code or 'failed'}"
    content = (f"what failed: {(message or error_code or 'unknown')[:300]}\n"
               f"target: {str(target)[:120]}\n"
               f"likely fix: {hint or 'diagnose before retrying'}")
    try:
        result = memory.add(title=title, content=content, scope=SCOPE, type="lesson",
                            tags=["failure", tool], source=tool,
                            confidence=0.3, verified=False)
    except Exception:
        return {"success": False, "message": "could not store the lesson", "data": {}}
    return {"success": True, "message": "lesson recorded (proposed, not yet verified)",
            "data": {"id": result.get("data", {}).get("id"), "hint": hint}}


def lessons(tool: str = "", error_code: str = "", limit: int = 10) -> list[dict]:
    """The lessons that apply to a tool / error code (newest first)."""
    items = memory.search("", scope=SCOPE, limit=MAX_LESSONS)
    out = []
    for item in items:
        if tool and tool.lower() not in (item.get("title", "") + item.get("content", "")).lower():
            continue
        if error_code and error_code.lower() not in (
                item.get("title", "") + item.get("content", "")).lower():
            continue
        out.append(item)
        if len(out) >= limit:
            break
    return out


def confirm(lesson_id: str, note: str = "") -> dict:
    """Mark a lesson as verified (a human or a successful retry confirmed it)."""
    return memory.update(lesson_id, verified=True, content_note=note)


def summary() -> dict:
    items = memory.list_scope(scope=SCOPE, limit=MAX_LESSONS)
    return {
        "lessons": len(items),
        "verified": sum(1 for item in items if item.get("verified")),
        "proposed": sum(1 for item in items if not item.get("verified")),
        "oldest": items[-1].get("updated") if items else None,
        "note": "proposals become facts only after a human or a successful retry confirms them",
    }


def failure_capture(func):
    """Decorator: record a lesson whenever the wrapped tool reports a failure."""
    import functools

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        try:
            if isinstance(result, dict) and result.get("success") is False:
                data = result.get("data") or {}
                code = data.get("error_code") or data.get("permission") or "FAILED"
                message = str(result.get("message") or "")[:300]
                target = str(data.get("target") or data.get("field_ref")
                             or data.get("url") or data.get("session_id") or "")[:120]
                if "no speech detected" not in message.lower():
                    record_failure(getattr(func, "__name__", "tool"), code, target, message)
        except Exception:
            pass
        return result

    return wrapper
