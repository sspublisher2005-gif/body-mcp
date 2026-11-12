"""The execution ledger: EYES -> BRAIN -> HANDS -> VERIFY, written down.

The agent stays the brain: it makes the decision. Body-MCP only records the chain so
the work is auditable and the final report can be built from evidence instead of
memory.

A workflow is a small JSON file in <config>/workflows/<id>.json:

    goal          what the user asked for
    observations  what the body saw (eyes)
    decisions     what the brain decided, and why (written by the agent)
    actions       what the body did (hands)
    verifications what proved it worked (or did not)
    blockers      what stopped it
    lessons       what was learned
"""
from __future__ import annotations

import json
import os
import time
import uuid

KINDS = ("observation", "decision", "action", "verification", "blocker", "lesson",
         "note", "approval")


def workflows_dir() -> str:
    from . import permissions

    path = os.path.join(permissions._config_dir(), "workflows")
    os.makedirs(path, exist_ok=True)
    return path


def path_for(workflow_id: str) -> str:
    return os.path.join(workflows_dir(), f"{workflow_id}.json")


def _read(workflow_id: str) -> dict | None:
    try:
        with open(path_for(workflow_id), encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _write(workflow: dict) -> None:
    try:
        with open(path_for(workflow["workflow_id"]), "w", encoding="utf-8") as handle:
            json.dump(workflow, handle, indent=2, default=str)
    except OSError:
        pass


def start(goal: str) -> dict:
    """Open a workflow for one user goal."""
    workflow_id = "wf_" + uuid.uuid4().hex[:10]
    workflow = {
        "workflow_id": workflow_id,
        "goal": (goal or "")[:500],
        "started": time.time(),
        "steps": [],
        "status": "running",
    }
    _write(workflow)
    from . import events

    events.emit(events.TASK_CREATED, tool="body_workflow_start", status="STARTED",
                summary=f"workflow started: {(goal or '')[:80]}")
    return {"success": True, "message": f"workflow {workflow_id} opened",
            "data": {"workflow_id": workflow_id, "goal": workflow["goal"]}}


def note(workflow_id: str, kind: str, text: str, evidence: dict | None = None) -> dict:
    """Append one step to the ledger (observation, decision, action, verification...)."""
    if kind not in KINDS:
        return {"success": False, "message": f"kind must be one of {list(KINDS)}", "data": {}}
    workflow = _read(workflow_id)
    if not workflow:
        return {"success": False, "message": f"no such workflow: {workflow_id}", "data": {}}
    step = {"kind": kind, "text": (text or "")[:1000], "at": time.time(),
            "evidence": evidence or {}}
    workflow["steps"].append(step)
    _write(workflow)
    return {"success": True, "message": f"{kind} recorded", "data": {"workflow_id": workflow_id}}


def latest() -> dict | None:
    """The most recent workflow (so the agent can continue it)."""
    try:
        names = [n for n in os.listdir(workflows_dir()) if n.endswith(".json")]
    except OSError:
        return None
    if not names:
        return None
    newest = max(names, key=lambda n: os.path.getmtime(os.path.join(workflows_dir(), n)))
    return _read(newest[:-5])


def report(workflow_id: str = "") -> dict:
    """The evidence-backed report of a workflow: what was seen, decided, done, verified."""
    workflow = _read(workflow_id) if workflow_id else latest()
    if not workflow:
        return {"success": False, "message": "no workflow to report on", "data": {}}
    steps = workflow.get("steps", [])
    grouped = {kind: [s for s in steps if s.get("kind") == kind] for kind in KINDS}
    verifications = grouped.get("verification", [])
    failed = [v for v in verifications if str(v.get("text", "")).lower().startswith(("fail", "no ", "not "))]
    status = ("verified" if verifications and not failed else
              "failed" if failed else
              "blocked" if grouped.get("blocker") else
              "unverified" if steps else "empty")
    workflow["status"] = status
    _write(workflow)
    return {
        "success": True,
        "message": (f"workflow {workflow.get('workflow_id')}: {len(steps)} step(s), status {status}"),
        "data": {
            "workflow_id": workflow.get("workflow_id"),
            "goal": workflow.get("goal"),
            "status": status,
            "counts": {kind: len(items) for kind, items in grouped.items() if items},
            "observations": grouped.get("observation", []),
            "decisions": grouped.get("decision", []),
            "actions": grouped.get("action", []),
            "verifications": grouped.get("verification", []),
            "blockers": grouped.get("blocker", []),
            "lessons": grouped.get("lesson", []),
            "note": "the agent decides; this ledger only records what it saw, chose, did and proved",
        },
    }
