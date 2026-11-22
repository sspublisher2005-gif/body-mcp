"""Assemble a failure diagnosis from what the body already knows.

No new storage, no new state, no auto-fix: this reads the error catalog in
lessons.py and the proposal ledger in memory.py and returns the next step.
The coding agent applies the fix; the body only supplies evidence.
"""
from __future__ import annotations

MAX_RETRIES = 3


def context(code: str, tool: str = "", message: str = "", attempt: int = 0) -> dict:
    from . import lessons

    known = lessons.hint_for(code, message) or lessons.HINTS.get(code, "")
    past = lessons.lessons(tool=tool, error_code=code, limit=3)
    retry = "stop after 3 attempts; a retry must CHANGE something, not repeat"
    if attempt and attempt >= MAX_RETRIES:
        retry = "limit reached (3) — stop, report the blocker, ask the user"

    route = ("research_any(query=<the exact error text>) then research_source on "
             "github_issues or stackoverflow for external causes")
    return {
        "success": True,
        "message": (f"failure diagnosis for {code or 'unknown error'}"
                    + (f" in {tool}" if tool else "")),
        "data": {
            "code": code, "tool": tool, "message": message[:300],
            "known_fix": known or "no catalog entry — research before guessing",
            "past_lessons": [{"title": item.get("title", ""),
                              "verified": bool(item.get("verified")),
                              "content": str(item.get("content", ""))[:200]}
                             for item in past],
            "attempt": attempt, "retry_rule": retry,
            "research_route": route,
            "loop": [
                "propose the fix with body_workflow_note(kind='lesson')",
                "ask approval with reflex_ask(action=<exact spec>) if consequential",
                "apply the fix in the AGENT (the body has no file/shell tools)",
                "prove it with reflex_verify or the tool's verification state",
                "only then promote the lesson to verified=true",
            ],
            "never": ["auto-apply", "auto-install", "bypass a block",
                      "rotate identity", "retry unchanged more than 3 times"],
        },
    }
