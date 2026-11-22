"""The user-decides rule for login walls and other restrictions.

The user's decision (2026-11-22):
  - connect the user's own browser ONCE, at first install, and keep it;
  - after that the agent may use it, safely;
  - if a login / CAPTCHA / paywall / rate limit appears, the agent must NOT log
    in, solve, bypass or rotate. It stops with needs_user.
  - the USER chooses: log in themselves and continue, or decline. If they
    decline, the agent picks another SAFE option (a different source/tool).

This module produces that decision object. It never grants anything.
"""
from __future__ import annotations

ALTERNATIVES = {
    "research": ["research_any with another source", "research_source on a public API",
                 "public pages the user names", "local memory / body_lessons"],
    "browser": ["a public page on another domain", "a document the user opens and connects",
                "wait and retry later (rate limit only)"],
}

HUMAN_ACTION = {
    "auth_expired": "Log in YOURSELF in YOUR browser, then tell me to continue on the same tab.",
    "captcha": "Solve the challenge YOURSELF in your browser; tell me when it is clear.",
    "paywall": "Subscribe or open an accessible copy YOURSELF; tell me if you want to continue.",
    "rate_limit": "Wait for the cooldown, or pick another source. I will not rotate identity "
                  "or retry aggressively.",
    "access_denied": "Open an accessible copy YOURSELF, or pick another source.",
}


def decision(kind: str, *, area: str = "research", evidence: str = "",
             domain: str = "") -> dict:
    """A needs_user decision with two explicit options for the human."""
    return {
        "status": "needs_user",
        "success": False,
        "kind": kind,
        "area": area,
        "evidence": evidence[:300],
        "domain": domain,
        "agent_must_not": ("log in, type credentials, solve a challenge, bypass a "
                           "paywall/rate limit, or switch identity"),
        "options": {
            "user_continues": HUMAN_ACTION.get(kind, "Decide how you want to continue."),
            "user_declines": ("I will use a different safe option: "
                              + ", ".join(ALTERNATIVES.get(area, ALTERNATIVES["research"]))),
        },
        "rule": ("Ask the user. Never choose 'user_continues' on their behalf. If they "
                 "decline, use a safe alternative and say which source actually answered."),
    }
