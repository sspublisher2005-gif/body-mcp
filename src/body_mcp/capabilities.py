"""Auto-use: one compact manifest so an agent knows WHAT the body has, and WHEN to use it.

The problem this solves: a 78-tool MCP server is invisible to an agent that
doesn't know to look. It reaches for webfetch/websearch instead. `body_capabilities`
is the one tool an agent should call FIRST; it returns a short, machine-specific
answer plus the exact tool to reach for next.

It is derived from body_status() — never a second source of truth.
"""
from __future__ import annotations

# The work loop, stated once as a tool the agent can call.
LOOP = [
    "EYES: eyes_see_browser / eyes_see_desktop / desktop_watch_read / research_video",
    "BRAIN: decide the next SINGLE action, record it with body_workflow_note",
    "HANDS: hands_* (one action) / desktop_click / desktop_type / browser_bridge",
    "VERIFY: reflex_verify (or the tool's data.verification.status) - UNCONFIRMED is not done",
    "LEARN: body_lessons before repeating a failed attempt",
    "REPORT: body_workflow_report with the evidence chain",
]

# WHY each group exists — the "when", not the "what". These strings are also
# used in the tool docstrings so the agent sees the trigger before selecting.
WHEN = {
    "eyes": "you need to see a page or the screen BEFORE acting (a guess is a wrong action)",
    "hands": "you need to change a page or a native app - one validated action at a time",
    "verify": "after every changing action - a click that didn't navigate is not done",
    "research": "you need evidence from public sources - never claim a platform was searched when access failed",
    "memory": "you need a durable fact or a past lesson - search before re-deriving",
    "privacy": "the task involves sensitive browsing or text that must stay on this machine",
    "worker": "text or an image should be processed locally instead of by a remote provider",
    "reflex": "an action needs human approval, or you must ask a yes/no question",
}


def _available(status: dict) -> dict:
    """Reduce a body_status dict to machine-specific yes/no facts."""
    data = status.get("data") or {}
    browser = data.get("browser") or {}
    voice = data.get("voice_output") or {}
    ocr = data.get("desktop_ocr") or {}
    worker = (data.get("state_perception") or {}).get("local_worker") or {}
    ears = data.get("ears") or {}
    return {
        "browser": bool(browser.get("playwright_importable")),
        "current_browser_attached": (browser.get("current_browser_cdp") or {}).get(
            "attached", False),
        "image_can_be_attached": True,  # no OCR needed - proven on this machine
        "desktop_ocr": ocr.get("status") == "available",
        "native_desktop_control": "windows" in str(data.get("platform", "")).lower(),
        "text_to_speech": bool(voice.get("available")),
        "microphone": bool(ears.get("sounddevice_importable")),
        "speech_to_text_model": bool(ears.get("whisper_model_configured")),
        "local_worker": bool(worker.get("available")),
        "vpn_control_allowed": (data.get("permissions") or {}).get("capabilities", {}).get(
            "vpn_control") == "allow",
    }


def build(status: dict) -> dict:
    facts = _available(status)
    usable = [name for name, ok in facts.items() if ok]
    blocked = [name for name, ok in facts.items() if not ok]

    next_step = "eyes_see_browser(url) to look before acting"
    if not facts["browser"]:
        next_step = "the browser is unavailable on this machine - use the desktop or research tools"

    return {
        "success": True,
        "message": ("Body-MCP is the body, not the brain. Call the tools below; "
                    "the coding agent still makes every decision."),
        "data": {
            "identity": ("I am the body. Eyes, ears, hands, voice, memory, research and "
                         "privacy - over MCP, local-first. I never plan, write project "
                         "files or decide; that is the coding agent's job."),
            "work_loop": LOOP,
            "use_instead_of_web_tools": {
                "why": ("if I can read a page or research a source with a body tool, "
                        "I must not reach for webfetch/websearch instead"),
                "tools": ["eyes_see_browser", "research_any", "research_source",
                          "research_video", "research_collect"],
            },
            "when_to_use": WHEN,
            "available_here": usable,
            "blocked_here": blocked,
            "next_step": next_step,
            "verification_states": ["CONFIRMED", "UNCONFIRMED", "PARTIAL", "FAILED",
                                    "BLOCKED", "CANCELLED", "needs_user"],
            "truth_rule": ("UNCONFIRMED is not done. A click that did not navigate is "
                           "not a completed click. Say what could not be verified."),
            "note": ("This manifest is derived from body_status() - the same machine "
                     "check, never a second source of truth."),
        },
    }
