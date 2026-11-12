"""Role contracts: the multi-agent design, mapped onto the body.

The master prompt asks for a coordinated team (research, planning, execution, QA,
security, reporting...). Those are **distinct responsibilities, not separate models**:
the connected agent is the orchestrator and the brain, and the body executes each
role's contract.

This module gives every role a *contract* the body can enforce:

  - what the role may use (which tools / capabilities),
  - a budget (max actions, a deadline),
  - what it must produce (an evidence record),
  - when it must stop (terminal conditions).

    body_role_start(role, goal, budget)   -> a contract with an id
    body_role_status(role_id)             -> progress, spend, terminal state
    body_role_finish(role_id, evidence)   -> close it with what it produced
    body_stop_all()                       -> emergency stop: cancel everything

The orchestrator (the agent) still plans, decides and calls other MCP servers.
"""
from __future__ import annotations

import time
import uuid

from . import events, runtime

ROLES = {
    "research": {"tools": ["research_source", "research_any", "research_video",
                           "research_youtube_search", "research_collect", "body_lessons"],
                 "capability": "public_web", "produces": "evidence records with URLs"},
    "source_connector": {"tools": ["research_sources", "research_source", "research_any"],
                         "capability": "public_web", "produces": "which route worked and why"},
    "planning": {"tools": ["body_workflow_note", "body_events", "body_profile"],
                 "capability": None, "produces": "an ordered plan with acceptance criteria"},
    "workflow_learning": {"tools": ["desktop_watch_start", "desktop_watch_read",
                                    "reflex_interview", "body_skill_save"],
                          "capability": "desktop_capture",
                          "produces": "a skill draft plus the open questions"},
    "skill_engineering": {"tools": ["body_skill_save", "body_skill_list", "body_skill_replay",
                                    "memory_write", "memory_search"],
                          "capability": "memory", "produces": "a versioned, tested skill"},
    "execution": {"tools": ["hands_click", "hands_type", "hands_batch", "desktop_click",
                            "desktop_type", "browser_bridge", "body_open_external"],
                  "capability": "keyboard_mouse", "produces": "an action log with verification"},
    "coding": {"tools": ["body_task_start", "body_task_status", "body_undo"],
               "capability": None, "produces": "the change, and how to undo it"},
    "qa": {"tools": ["reflex_verify", "eyes_see_browser", "body_events", "body_workflow_report"],
           "capability": None, "produces": "a verdict: verified, unverified or failed"},
    "security": {"tools": ["body_status", "body_lessons", "body_undo_list", "body_profile"],
                 "capability": None, "produces": "what was allowed, denied and why"},
    "evaluation": {"tools": ["body_workflow_report", "body_events", "body_lessons"],
                   "capability": None, "produces": "quality, evidence and reliability numbers"},
    "reporting": {"tools": ["body_workflow_report", "body_events", "body_status"],
                  "capability": None, "produces": "the final answer with evidence"},
}

DEFAULT_BUDGET = {"max_actions": 50, "max_seconds": 900}

_contracts: dict[str, dict] = {}


def start(role: str, goal: str, budget: dict | None = None) -> dict:
    """Open a role contract (the orchestrator delegates; the body enforces)."""
    if role not in ROLES:
        return {"success": False,
                "message": f"unknown role {role!r}; known: {sorted(ROLES)}",
                "data": {}}
    limits = dict(DEFAULT_BUDGET)
    limits.update({key: value for key, value in (budget or {}).items()
                   if key in ("max_actions", "max_seconds")})
    contract_id = "role_" + uuid.uuid4().hex[:10]
    task_id = runtime.registry.create(label=f"role:{role}")
    contract = {"role_id": contract_id, "role": role, "goal": (goal or "")[:500],
                "task_id": task_id, "started": time.time(), "finished": None,
                "state": "running", "actions": 0, "budget": limits,
                "evidence": None, "stop_reason": None}
    _contracts[contract_id] = contract
    events.emit(events.TASK_CREATED, task_id=task_id, tool="body_role_start", status="STARTED",
                summary=f"{role} contract opened: {(goal or '')[:70]}",
                evidence={"role_id": contract_id, "budget": limits})
    return {"success": True,
            "message": f"{role} contract {contract_id} opened (budget {limits})",
            "data": {"role_id": contract_id, "role": role, "task_id": task_id,
                     "tools": ROLES[role]["tools"],
                     "capability": ROLES[role]["capability"],
                     "produces": ROLES[role]["produces"]}}


def status(contract_id: str) -> dict:
    contract = _contracts.get(contract_id)
    if not contract:
        return {"success": False, "message": f"no such contract: {contract_id}", "data": {}}
    elapsed = (contract["finished"] or time.time()) - contract["started"]
    data = dict(contract)
    data["elapsed_s"] = round(elapsed, 1)
    data["over_budget"] = (contract["actions"] > contract["budget"]["max_actions"]
                            or elapsed > contract["budget"]["max_seconds"])
    return {"success": True,
            "message": f"{contract['role']}: {contract['state']} "
                        f"({contract['actions']} action(s), {round(elapsed)}s)",
            "data": data}


def finish(contract_id: str, evidence: str = "", verified: bool = False) -> dict:
    """Close a contract with what it produced (the evidence the orchestrator needs)."""
    contract = _contracts.get(contract_id)
    if not contract:
        return {"success": False, "message": f"no such contract: {contract_id}", "data": {}}
    contract["finished"] = time.time()
    contract["state"] = "verified" if verified else "finished"
    contract["evidence"] = (evidence or "")[:4000]
    runtime.registry.finish(contract["task_id"], "completed" if verified else "failed",
                            contract["evidence"][:200])
    events.emit(events.TASK_FINISHED, task_id=contract["task_id"], tool="body_role_start",
                status=contract["state"].upper(),
                summary=f"{contract['role']} contract finished",
                evidence={"role_id": contract_id, "verified": verified})
    return {"success": True, "message": f"{contract['role']} contract closed "
                                        f"({'verified' if verified else 'finished'})",
            "data": {"role_id": contract_id, "state": contract["state"],
                     "evidence": contract["evidence"]}}


def stop_all(reason: str = "emergency stop") -> dict:
    """Emergency stop: cancel every running task and close every role contract."""
    from . import tasks

    cancelled = tasks.stop_all()
    closed = 0
    for contract in _contracts.values():
        if contract["state"] == "running":
            contract["state"] = "cancelled"
            contract["finished"] = time.time()
            contract["stop_reason"] = reason
            closed += 1
    events.emit(events.CANCEL_REQUESTED, tool="body_stop_all", status="CANCELLED",
                summary=reason)
    return {"success": True,
            "message": f"stopped: {cancelled} background task(s), {closed} contract(s)",
            "data": {"tasks": cancelled, "contracts": closed, "reason": reason}}


def matrix() -> list[dict]:
    """The team, with what each role may use and must produce."""
    return [{"role": role, "tools": spec["tools"], "capability": spec["capability"],
             "produces": spec["produces"],
             "note": "the connected agent is the orchestrator and the brain"}
            for role, spec in ROLES.items()]
