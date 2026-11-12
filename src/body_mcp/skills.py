"""Skills: procedures the body learned from your own work - and can replay.

A "skill" is a reusable procedure: what the goal was, the steps that worked, **why**
they worked, and whether the result was verified. It is stored in the same local
memory as everything else (scope `workflow`, type `skill`), so it survives sessions
and is inspectable.

  body_skill_save(name, goal, steps, why, verified)  -> learn it
  body_skill_list()                                   -> what we know
  body_skill_replay(skill_id)                         -> do exactly the same thing again

Replay runs the recorded steps through the normal executor: the same targets, the
same order, the same content - with the same permission gate, the same approval
rules and the same verification. It is "copy paste the same", not a new guess.

A skill that was never verified stays a proposal: the agent is told to check it
before trusting it.
"""
from __future__ import annotations

import difflib
import json
import time

from . import memory

SCOPE = "workflow"
MAX_STEPS = 40


def save(name: str, goal: str, steps: list[dict], why: str = "",
         verified: bool = False, tags: list[str] | None = None) -> dict:
    """Store a procedure so it can be replayed later."""
    name = (name or "").strip()[:120]
    goal = (goal or "").strip()[:500]
    steps = [step for step in (steps or []) if isinstance(step, dict)][:MAX_STEPS]
    if not name or not goal or not steps:
        return {"success": False,
                "message": "a skill needs a name, a goal and at least one step",
                "data": {}}
    content = (f"goal: {goal}\n"
               f"why: {(why or 'not recorded')[:1000]}\n"
               f"steps: {json.dumps(steps, ensure_ascii=False)[:6000]}")
    result = memory.add(title=f"skill: {name}", content=content, scope=SCOPE, type="skill",
                        tags=(tags or []) + ["skill", name], source="skill",
                        confidence=0.8 if verified else 0.4, verified=verified)
    return {"success": bool(result.get("success")),
            "message": (f"skill saved ({'verified' if verified else 'proposed - verify it first'})"),
            "data": {"id": result.get("data", {}).get("id"), "name": name,
                     "steps": len(steps), "verified": verified}}


def list_skills(limit: int = 20) -> list[dict]:
    """The skills we know about (newest first)."""
    items = memory.search("", scope=SCOPE, limit=80)
    out = []
    for item in items:
        if item.get("type") != "skill":
            continue
        out.append({"id": item["id"], "title": item["title"],
                    "verified": item.get("verified"), "updated": item.get("updated"),
                    "goal": _section(item.get("content", ""), "goal"),
                    "why": _section(item.get("content", ""), "why"),
                    "steps": _steps_of(item.get("content", ""))})
        if len(out) >= limit:
            break
    return out


def _section(content: str, name: str) -> str:
    for line in (content or "").splitlines():
        if line.startswith(f"{name}: "):
            return line[len(name) + 2:].strip()
    return ""


def _steps_of(content: str) -> list[dict]:
    for line in (content or "").splitlines():
        if line.startswith("steps: "):
            try:
                steps = json.loads(line[len("steps: "):])
                return steps if isinstance(steps, list) else []
            except Exception:
                return []
    return []


def get(skill_id: str) -> dict | None:
    item = memory.get(skill_id)
    if not item or item.get("type") != "skill":
        return None
    return {"id": item["id"], "title": item["title"], "verified": item.get("verified"),
            "goal": _section(item.get("content", ""), "goal"),
            "why": _section(item.get("content", ""), "why"),
            "steps": _steps_of(item.get("content", ""))}


async def replay(skill_id: str, task_id: str | None = None) -> dict:
    """Run a saved skill again - exactly the same steps, in the same order."""
    from . import batch, browser

    skill = get(skill_id)
    if not skill:
        return {"success": False, "message": f"no such skill: {skill_id}", "data": {}}
    if not skill["verified"]:
        return {"success": False,
                "message": ("this skill was never verified - check it with the user before "
                            "replaying it"),
                "data": {"skill": skill}}
    steps = skill["steps"]
    page = await browser.ensure_page()
    result = await batch.execute_actions(
        page=page, actions=steps, resolver=batch.BatchResolver(page),
        allow_consequential=True, on_failure="stop", task_id=task_id)
    return {"success": bool(result.get("success")),
            "message": f"replayed '{skill['title']}' ({len(steps)} step(s))",
            "data": {"skill_id": skill_id, "result": result}}


def summary() -> dict:
    skills = list_skills(limit=80)
    return {"skills": len(skills),
            "verified": sum(1 for skill in skills if skill["verified"]),
            "proposed": sum(1 for skill in skills if not skill["verified"]),
            "note": "a skill is only replayed after it was verified",
            "at": time.time()}


def similarity(new_text: str, previous: list[str]) -> dict:
    """How similar is the new text to what was produced before?

    Used for ADAPTED execution: the method is kept, the content must be new. The
    score is the worst (highest) similarity against the previous outputs.
    """
    import re

    def tokens(text: str) -> set:
        return set(re.findall(r"[\w']+", (text or "").lower()))

    new_tokens = tokens(new_text)
    if not new_tokens:
        return {"ok": False, "reason": "no text to compare", "max_similarity": None}
    best = 0.0
    worst = None
    for previous_text in previous or []:
        old_tokens = tokens(previous_text)
        if not old_tokens:
            continue
        overlap = len(new_tokens & old_tokens) / max(1, len(new_tokens | old_tokens))
        sequence = difflib.SequenceMatcher(None, (new_text or "")[:4000],
                                          (previous_text or "")[:4000]).ratio()
        score = max(overlap, sequence)
        if score > best:
            best = score
            worst = (previous_text or "")[:120]
    return {"ok": True, "max_similarity": round(best, 3),
            "closest_previous": worst,
            "verdict": ("too similar - change the topic or the wording"
                        if best >= 0.8 else
                        "similar - review it" if best >= 0.6 else "new enough")}
