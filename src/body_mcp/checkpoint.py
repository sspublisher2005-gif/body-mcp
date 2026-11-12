"""In-memory task checkpoints for safe pause/resume.

Checkpoints are created when batch execution pauses on a restriction or fails
in a recoverable spot. They are:
  - memory-only (never written to disk),
  - free of credentials and raw page content,
  - used to resume from the last VERIFIED step, never to replay blindly.

Remaining-step data is redacted before storage: fill texts are dropped, URLs
are stripped to origin+path, page content is never stored.
"""
import time
import urllib.parse
import uuid

MAX_CHECKPOINTS = 20
TTL_SECONDS = 3600
_checkpoints: dict[str, dict] = {}


def _redact_step(step: dict) -> dict:
    out = {"type": step.get("type")}
    if step.get("type") in ("goto",):
        try:
            parts = urllib.parse.urlsplit(str(step.get("url", "")))
            out["url"] = f"{parts.scheme}://{parts.netloc}{parts.path}"  # query dropped
        except Exception:
            out["url"] = "<unparseable>"
    elif step.get("type") == "fill":
        out["field_ref"] = step.get("field_ref")
        out["text"] = "<redacted>"
    elif step.get("type") == "click":
        out["target"] = step.get("target")
    elif step.get("type") == "press":
        out["key"] = step.get("key")
    elif step.get("type") == "scroll":
        out["direction"] = step.get("direction")
        out["amount"] = step.get("amount")
    elif step.get("type") == "wait_for":
        out["condition"] = step.get("condition")
        out["value"] = str(step.get("value", ""))[:200]
    elif step.get("type") in ("verify_text", "verify_url"):
        out[step.get("type")] = str(step.get(step.get("type"), ""))[:200]
    elif step.get("type") == "screenshot":
        out = {"type": "screenshot"}
    for k in ("timeout_ms", "expected"):
        if k in step:
            out[k] = step[k]
    return out


def create(task_id: str, last_verified_step: int, remaining_steps: list[dict],
           url: str, reason: str, resume_condition: str,
           attempted_unverified: int = 0) -> str:
    if url:
        try:
            parts = urllib.parse.urlsplit(url)
            url = f"{parts.scheme}://{parts.netloc}{parts.path}"
        except Exception:
            url = "<unparseable>"
    cid = "ckpt_" + uuid.uuid4().hex[:12]
    _checkpoints[cid] = {
        "checkpoint_id": cid,
        "task_id": task_id,
        "created": time.time(),
        "updated": time.time(),
        "url": url,
        "last_verified_step": last_verified_step,
        # steps that ran but were never verified — resume must not treat them as done
        "attempted_unverified_steps": attempted_unverified,
        "remaining_steps": [_redact_step(s) for s in remaining_steps],
        "reason": reason,
        "resume_condition": resume_condition,
    }
    _evict()
    return cid


def _evict() -> None:
    # drop expired entries first, then oldest beyond the cap
    now = time.time()
    for cid, ck in list(_checkpoints.items()):
        if now - ck["updated"] > TTL_SECONDS:
            del _checkpoints[cid]
    while len(_checkpoints) > MAX_CHECKPOINTS:
        oldest = min(_checkpoints, key=lambda c: _checkpoints[c]["updated"])
        del _checkpoints[oldest]


def get(cid: str) -> dict | None:
    ck = _checkpoints.get(cid)
    if not ck:
        return None
    if time.time() - ck["updated"] > TTL_SECONDS:
        del _checkpoints[cid]
        return None
    return ck


def list_checkpoints() -> list[dict]:
    _evict()
    return [
        {k: ck[k] for k in ("checkpoint_id", "task_id", "created", "updated",
                            "url", "last_verified_step", "attempted_unverified_steps",
                            "reason", "resume_condition")}
        for ck in sorted(_checkpoints.values(), key=lambda c: c["created"])
    ]


def clear(cid: str) -> bool:
    return _checkpoints.pop(cid, None) is not None


def clear_all() -> int:
    count = len(_checkpoints)
    _checkpoints.clear()
    return count
