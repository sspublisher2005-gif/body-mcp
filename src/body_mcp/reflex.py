"""Reflexes: verify an action's outcome, and ask the human yes/no questions.

reflex_ask prefers the MCP elicitation channel (OpenCode shows it as a form).
If the client does not support elicitation, it falls back to a native Windows
message box. Any failure to ask yields approved=False (fail closed).
"""
import asyncio
import ctypes
import sys

from . import browser


def _messagebox_yesno(question: str) -> bool:
    MB_YESNO, MB_ICONQUESTION, MB_SYSTEMMODAL = 0x04, 0x20, 0x1000
    return ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
        0, question, "Body-MCP — approve this action?",
        MB_YESNO | MB_ICONQUESTION | MB_SYSTEMMODAL,
    ) == 6  # IDYES


async def verify(expected: str) -> dict:
    """Check whether expected text/element appeared in the current page (or desktop)."""
    expected = (expected or "").strip()
    if not expected:
        return {"success": False, "message": "expected must be non-empty",
                "data": {"expected": expected}}
    evidence = None
    found = False
    source = None
    try:
        page = await browser.ensure_page()
        if page.url and page.url != "about:blank":
            text = await page.locator("body").inner_text(timeout=4000)
            lowered = text.lower()
            index = lowered.find(expected.lower())
            if index >= 0:
                found = True
                source = page.url
                start = max(0, index - 60)
                evidence = text[start:index + len(expected) + 60].replace("\n", " ")
    except Exception:
        pass  # fall back to desktop below

    if not found:
        try:
            from . import eyes
            result = await asyncio.to_thread(eyes.see_desktop)
            if result.get("success"):
                text = result["data"].get("text", "")
                index = text.lower().find(expected.lower())
                if index >= 0:
                    found = True
                    source = "desktop-ocr"
                    start = max(0, index - 60)
                    evidence = text[start:index + len(expected) + 60].replace("\n", " ")
        except Exception:
            pass

    return {
        "success": True,
        "found": found,
        "message": ("expected text is present" if found
                    else "expected text NOT found — action may have failed"),
        "data": {"expected": expected, "evidence": evidence, "source": source},
    }


ELICITATION_TIMEOUT_S = 60.0


def _supports_elicitation(ctx) -> bool:
    """True only when the client actually declared elicitation support."""
    if ctx is None:
        return False
    caps = getattr(ctx, "client_capabilities", None)
    elicitation = getattr(caps, "elicitation", None)
    # Some SDK versions expose a dict; some expose a pydantic model.
    if isinstance(elicitation, dict):
        return bool(elicitation)
    return elicitation is not None


async def ask(question: str, ctx=None, action: str | dict | None = None) -> dict:
    """Ask the human a yes/no question.

    Without `action`: answers your question; issues NO scoped approval.
    With `action` (a JSON string OR the already-parsed dict that MCP SDK 2.3+
    passes when the caller writes a JSON string in a tool call): a yes issues ONE
    scoped approval bound to exactly that action. A webpage, model output, or any
    other tool output can never mint an approval — only this function, only on yes.

    Fails closed: if the client cannot do elicitation and there is no interactive
    desktop, it returns approved=False instead of hanging or guessing.
    """
    question = (question or "").strip()
    if not question:
        return {"success": False, "approved": False,
                "message": "question must be non-empty", "data": {}}

    # Validate the action spec BEFORE asking — the user approves the same object
    # the executor will run. MCP SDK 2.3+ parses a JSON-string tool argument into
    # a dict before the tool sees it, so accept both forms.
    action_spec = None
    if action:
        import json
        try:
            parsed = action if isinstance(action, dict) else json.loads(action)
            if not isinstance(parsed, dict) or not parsed.get("tool") or not parsed.get("capability"):
                return {"success": False, "approved": False,
                        "message": "action must be a JSON object with at least tool and capability",
                        "data": {"action": str(action)[:500]}}
            action_spec = parsed
        except Exception as exc:
            return {"success": False, "approved": False,
                    "message": f"action is not valid JSON: {exc}",
                    "data": {"action": str(action)[:500]}}

    approved = None
    if _supports_elicitation(ctx):
        try:
            import asyncio

            approved = await asyncio.wait_for(
                _ask_via_elicitation(question, ctx), timeout=ELICITATION_TIMEOUT_S)
        except Exception:
            approved = None
    fallback_used = False
    if approved is None:
        approved = _ask_via_messagebox(question)
        fallback_used = True

    issued_token = None
    if approved and action_spec is not None:
        from .approvals import approvals
        issued_token = await approvals.issue(action_spec)
        from . import events
        events.emit(events.APPROVAL_GRANTED, tool="reflex_ask", status="APPROVED",
                    summary=f"approval granted for {action_spec.get('tool')} "
                            f"{action_spec.get('target')}",
                    evidence={"capability": action_spec.get("capability")})
    elif not approved:
        from . import events
        events.emit(events.APPROVAL_DENIED, tool="reflex_ask", status="DENIED",
                    summary="the human said no",
                    user_action_required=True)

    message = ("approved — execution of EXACTLY the approved action may proceed once, now"
               if approved else
               "NOT approved — do not proceed; ask the user what they want instead")
    return {"success": True,
            "approved": bool(approved),
            "message": message,
            "data": {"question": question,
                     "method": "elicitation" if not fallback_used else "messagebox",
                     "scoped_approval": bool(issued_token),
                     "action": action_spec}}


async def _ask_via_elicitation(question: str, ctx) -> bool | None:
    """Returns True/False if the client answered, None if elicitation is unavailable."""
    try:
        from pydantic import BaseModel

        class YesNo(BaseModel):
            answer: bool

        result = await ctx.elicit(message=f"{question} (answer yes or no)", schema=YesNo)
        action = str(getattr(result, "action", "")).lower()
        if action != "accept":
            return False
        data = getattr(result, "data", None)
        return bool(getattr(data, "answer", False)) if data is not None else False
    except Exception:
        return None


def _ask_via_messagebox(question: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        return _messagebox_yesno(question)
    except Exception:
        return False
