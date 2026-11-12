"""reflex_interview: a structured multi-question interview with the user.

`reflex_ask` is a yes/no gate. This is the other thing an agent needs before it
starts: the user's budget, the category, the pain points with other tools, the
weight class (light vs heavy), the must-haves. The body asks; the agent decides
what to do with the answers.

It uses the MCP elicitation form when the client supports it (one form, several
fields), and falls back to one question at a time through the Windows dialog.
"""
from __future__ import annotations

import sys

MAX_QUESTIONS = 12
MAX_ANSWER = 2000


async def interview(questions: list[str], ctx=None, title: str = "") -> dict:
    """Ask several questions and return the answers as a dict."""
    questions = [str(question).strip()[:300] for question in (questions or [])][:MAX_QUESTIONS]
    questions = [question for question in questions if question]
    if not questions:
        return {"success": False, "message": "no questions given", "data": {}}

    answers = {}
    method = "elicitation"
    if ctx is not None:
        answered = await _ask_via_form(questions, ctx, title)
        if answered is not None:
            answers = answered
        else:
            method = "dialog"
            answers = await _ask_one_by_one(questions)
    else:
        method = "dialog"
        answers = await _ask_one_by_one(questions)

    from . import events

    events.emit(events.APPROVAL_REQUESTED, tool="reflex_interview", status="INTERVIEW",
                summary=f"interview answered ({len(answers)}/{len(questions)} question(s))",
                user_action_required=True,
                evidence={"questions": len(questions), "answered": len(answers)})
    return {"success": True,
            "message": (f"interview complete: {len(answers)} of {len(questions)} answered "
                        f"({method})"),
            "data": {"answers": answers, "method": method,
                     "questions": questions,
                     "note": "the answers are the user's words - do not invent what they did not say"}}


async def _ask_via_form(questions: list[str], ctx, title: str) -> dict | None:
    """One elicitation form with a field per question (None if unavailable)."""
    try:
        from pydantic import create_model

        fields = {f"q{index + 1}": (str, "") for index in range(len(questions))}
        schema = create_model("InterviewAnswers", **fields)
        result = await ctx.elicit(
            message=title or "A few questions before I start (leave blank if you don't know)",
            schema=schema)
        action = str(getattr(result, "action", "")).lower()
        if action != "accept":
            return {}
        data = getattr(result, "data", None)
        if data is None:
            return {}
        answers = {}
        for index, question in enumerate(questions, start=1):
            value = getattr(data, f"q{index}", "")
            if value:
                answers[question] = str(value)[:MAX_ANSWER]
        return answers
    except Exception:
        return None


async def _ask_one_by_one(questions: list[str]) -> dict:
    """Fallback: one Windows dialog per question."""
    answers = {}
    for question in questions:
        answer = _ask_dialog(question)
        if answer:
            answers[question] = answer
    return answers


def _ask_dialog(question: str) -> str:
    """A Windows input box (the fallback when the client cannot elicit)."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()

        class INPUTBOXPARAM(ctypes.Structure):
            _fields_ = [("hwndParent", wintypes.HWND),
                        ("hInstance", wintypes.HINSTANCE),
                        ("lpstrTitle", wintypes.LPCWSTR),
                        ("lpstrPrompt", wintypes.LPCWSTR),
                        ("dwBufSize", wintypes.DWORD),
                        ("lpEditBuf", wintypes.LPWSTR),
                        ("lpResultBuf", wintypes.LPWSTR),
                        ("dwFlags", wintypes.DWORD)]

        buffer_size = 512
        edit = ctypes.create_unicode_buffer(buffer_size)
        result = ctypes.create_unicode_buffer(buffer_size + 1)
        params = INPUTBOXPARAM(0, 0, "Body-MCP", question, buffer_size, edit, result, 0)
        answer = ctypes.windll.user32.DialogBoxParamW(0, ctypes.cast(
            ctypes.pointer(params), ctypes.c_void_p).value, 0, 0, 0)
        if answer:
            return result.value[:MAX_ANSWER]
        return ""
    except Exception:
        return ""


def question_set() -> list[str]:
    """The questions a coding agent should ask before building anything."""
    return [
        "What is the budget for this (one-off build, monthly running cost, or both)?",
        "Which category is it in (research/analysis, content, automation, an agent, a tool)?",
        "Which coding agents or tools have you used, and what exactly went wrong for you?",
        "How much do they get in the way - too slow, too noisy, wrong answers, hard to steer?",
        "Lightweight or heavyweight: what machine, how much RAM, and can it download models?",
        "What must be true for this to be worth it (the one outcome you care about)?",
        "What must never happen (data leaving the machine, actions taken without you)?",
        "Where should it run - your laptop, a server, a browser tab, a phone?",
        "Do you already have accounts, keys or subscriptions this may use?",
        "When is it done - what would you do with it on day one?",
    ]
