"""Bounded action executor — the engine behind hands_batch and hands_parallel.

Design contract:
  - Actions are a declared, bounded list (max 25). No arbitrary JS/Python/shell.
  - Validation happens up front; nothing executes until the whole plan validates.
  - Sequential, dependent steps run on ONE page; each step has a bounded timeout.
  - Total task deadline is enforced; per-step timeouts clamp to [1s, 30s].
  - Stop-on-failure by default. `on_failure="continue"` skips SAFE steps only;
    a failed consequential step always stops the run.
  - Consequential clicks (pay/delete/send/...) require a FRESH per-step approval;
    batching never lets dangerous steps ride on one another's approval.
  - Duplicate submission of an identical consequential action is refused.
  - Verification steps (verify_text / verify_url) produce evidence, not vibes;
    a run is never reported completed when verification timed out or found nothing.
  - Checkpoints for pause/resume are memory-only and payload-redacted.
"""
import asyncio
import contextlib
import json
import re
import time
import urllib.parse

from . import browser, checkpoint, config, events, restrictions, runtime, safety

MAX_ACTIONS = 25
MAX_SCREENSHOTS = 10
MAX_STEP_TIMEOUT_MS = 30000
MIN_STEP_TIMEOUT_MS = 1000
DEFAULT_STEP_TIMEOUT_MS = 10000

ALLOWED_ACTIONS = {
    "goto", "click", "fill", "press", "scroll",
    "wait_for", "verify_text", "verify_url", "screenshot",
}

CONSEQUENTIAL_MARKERS = safety.DANGEROUS_BUTTON_PATTERNS  # reuse: pay/delete/send/...


class _StepFailed(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _RestrictionHit(Exception):
    def __init__(self, classification: dict):
        super().__init__(classification.get("kind", "restricted"))
        self.classification = classification


class _NeedsUser(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _step_signature(step: dict) -> str:
    return json.dumps(step, sort_keys=True, ensure_ascii=True)


def _is_consequential(step: dict, resolver) -> bool:
    if step.get("type") != "click":
        return False
    label = getattr(resolver, "label_of", lambda s: None)(step)
    return safety.is_dangerous_label(str(label or step.get("target", "")))


def validate_actions(actions) -> list[str]:
    """Structural validation only — no execution, no browser."""
    errors: list[str] = []
    if not isinstance(actions, list) or not actions:
        return ["actions must be a non-empty list"]
    if len(actions) > MAX_ACTIONS:
        errors.append(f"too many actions: {len(actions)} > {MAX_ACTIONS}")
    for i, step in enumerate(actions):
        if not isinstance(step, dict):
            errors.append(f"step {i}: not an object")
            continue
        a_type = step.get("type")
        if a_type not in ALLOWED_ACTIONS:
            errors.append(f"step {i}: unsupported action type {a_type!r}")
            continue
        if a_type == "goto":
            if not isinstance(step.get("url"), str) or not step["url"].strip():
                errors.append(f"step {i}: goto requires a 'url' string")
            else:
                verdict = browser.check_url(step["url"])
                if not verdict["ok"]:
                    errors.append(f"step {i}: goto refused: {verdict['reason']}")
        elif a_type == "click":
            if not isinstance(step.get("target"), str) or not step["target"].strip():
                errors.append(f"step {i}: click requires a non-empty 'target' (ref like 'btn_1' or visible text)")
        elif a_type == "fill":
            if not isinstance(step.get("field_ref"), str) or not step["field_ref"].strip():
                errors.append(f"step {i}: fill requires 'field_ref'")
            if not isinstance(step.get("text"), str):
                errors.append(f"step {i}: fill requires a 'text' string")
        elif a_type == "press":
            key = step.get("key")
            if not isinstance(key, str) or not key.strip():
                errors.append(f"step {i}: press requires a 'key'")
        elif a_type == "scroll":
            if step.get("direction", "down") not in ("up", "down"):
                errors.append(f"step {i}: scroll direction must be 'up' or 'down'")
            amount = step.get("amount", 3)
            if not isinstance(amount, int) or amount < 1 or amount > 50:
                errors.append(f"step {i}: scroll amount must be an int in [1, 50]")
        elif a_type == "wait_for":
            if step.get("condition") not in ("text", "selector"):
                errors.append(f"step {i}: wait_for condition must be 'text' or 'selector'")
            if not isinstance(step.get("value"), str) or not step["value"].strip():
                errors.append(f"step {i}: wait_for requires a non-empty 'value'")
        elif a_type == "verify_text":
            if not isinstance(step.get("expected"), str) or not step["expected"].strip():
                errors.append(f"step {i}: verify_text requires 'expected'")
        elif a_type == "verify_url" and (not isinstance(step.get("expected"), str)
                                         or not step["expected"].strip()):
            errors.append(f"step {i}: verify_url requires 'expected'")
        t = step.get("timeout_ms", DEFAULT_STEP_TIMEOUT_MS)
        if not isinstance(t, int) or t < MIN_STEP_TIMEOUT_MS or t > MAX_STEP_TIMEOUT_MS:
            errors.append(f"step {i}: timeout_ms must be an int in [{MIN_STEP_TIMEOUT_MS}, {MAX_STEP_TIMEOUT_MS}]")
    return errors


async def _body_text(page) -> str:
    try:
        return await page.locator("body").inner_text(timeout=4000)
    except Exception:
        return ""


async def _evidence_window(page, needle: str, radius: int = 80) -> str | None:
    text = await _body_text(page)
    idx = text.lower().find(needle.lower())
    if idx < 0:
        return None
    return text[max(0, idx - radius): idx + len(needle) + radius].replace("\n", " ")


async def _handle_restriction(classification: dict, page, executed_steps: list[dict],
                              remaining_steps: list[dict], task_id: str, *,
                              completed, start, evidence) -> dict:
    url = getattr(page, "url", "") or ""
    domain = classification.get("domain", "")
    kind = classification.get("kind")
    events.emit(events.BLOCKER, task_id=task_id, tool="hands_batch", status="BLOCKED",
                summary=f"blocked by {kind}",
                error_code=str(kind),
                user_action_required=kind in ("captcha", "auth_expired", "access_denied", "paywall"),
                evidence={"evidence": classification.get("evidence")})
    runtime.registry.finish(task_id, "blocked", str(kind))
    verified_indexes = [s["index"] for s in executed_steps if s.get("verified")]
    last_verified = max(verified_indexes) if verified_indexes else -1
    attempted_unverified = len([s for s in executed_steps if not s.get("verified")])

    if kind == "rate_limit":
        retry_s = classification.get("retry_after_s") or _backoff_default(executed_steps)
        await restrictions.set_cooldown(domain, retry_s, "rate-limited during task")
        cid = checkpoint.create(task_id, last_verified, remaining_steps, url,
                                reason=f"HTTP 429/rate limit on {domain}",
                                resume_condition=f"retry after cooldown (~{int(retry_s)}s) and re-verify page",
                                attempted_unverified=attempted_unverified)
        return _make_result(task_id, "retry_scheduled", completed,
                            failed_step={"index": len(completed), "type": "goto",
                                         "reason": f"rate-limited on {domain}"},
                            evidence=evidence, start=start, checkpoint_id=cid,
                            retry_scheduled={"domain": domain, "retry_after_s": retry_s,
                                             "evidence": classification.get("evidence")})

    if kind == "captcha":
        cid = checkpoint.create(task_id, last_verified, remaining_steps, url,
                                reason="CAPTCHA/human-verification challenge",
                                resume_condition="user completes the challenge manually; re-inspect page before resuming",
                                attempted_unverified=attempted_unverified)
        return _make_result(task_id, "needs_user", completed,
                            failed_step={"index": len(completed), "type": "goto",
                                         "reason": "human-verification challenge"},
                            needs_user={"url": _strip_url(url),
                                        "reason": f"human-verification challenge detected ({classification.get('evidence')}). "
                                                  "Body-MCP does not solve CAPTCHAs. Complete it in the browser, "
                                                  "then resume.",
                                        "checkpoint_id": cid},
                            evidence=evidence, start=start, checkpoint_id=cid)

    if kind == "auth_expired":
        cid = checkpoint.create(task_id, last_verified, remaining_steps, url,
                                reason="authentication/login wall",
                                resume_condition="user signs in manually; re-inspect page before resuming",
                                attempted_unverified=attempted_unverified)
        return _make_result(task_id, "needs_user", completed,
                            failed_step={"index": len(completed), "type": "goto",
                                         "reason": "login/authentication required"},
                            needs_user={"url": _strip_url(url),
                                        "reason": f"login/authentication required ({classification.get('evidence')}). "
                                                  "Sign in manually, then resume.",
                                        "checkpoint_id": cid},
                            evidence=evidence, start=start, checkpoint_id=cid)

    cid = checkpoint.create(task_id, last_verified, remaining_steps, url,
                            reason=f"blocked by {kind}",
                            resume_condition="restriction lifted or target permitted; re-verify page",
                            attempted_unverified=attempted_unverified)
    return _make_result(task_id, "blocked", completed,
                        failed_step={"index": len(completed), "type": "goto",
                                     "reason": f"{kind}: {classification.get('evidence')}"},
                        blocked=True, evidence=evidence, start=start, checkpoint_id=cid)


def _backoff_default(executed_steps) -> float:
    attempts = sum(1 for s in executed_steps if s.get("type") == "goto")
    return min(config.backoff_max_s(), config.backoff_base_s() * (2 ** max(0, attempts - 1)))


def _strip_url(url: str) -> str:
    try:
        parts = urllib.parse.urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}{parts.path}"
    except Exception:
        return "<unparseable url>"


async def execute_actions(*, page, actions: list[dict], resolver, allow_consequential: bool,
                          on_failure: str, deadline_ms: int,
                          task_id: str | None = None, checkpoint_overrides: dict | None = None) -> dict:
    """Run validated actions sequentially on one page.

    resolver: object with async resolve_click(step) / resolve_fill(step) / describe(step).
    """
    import uuid

    on_failure = (on_failure or "stop").lower()
    if on_failure not in ("stop", "continue"):
        on_failure = "stop"
    deadline = time.monotonic() + (deadline_ms if deadline_ms and deadline_ms > 0
                                   else config.batch_deadline_ms()) / 1000.0
    task_id = task_id or "task_" + uuid.uuid4().hex[:12]
    start = time.monotonic()
    runtime.registry.create(label="hands_batch", task_id=task_id)
    runtime.registry.set_tool(task_id, "hands_batch")
    events.emit(events.TASK_CREATED, task_id=task_id, tool="hands_batch",
                summary=f"batch of {len(actions) if isinstance(actions, list) else 0} action(s)",
                evidence={"actions": len(actions) if isinstance(actions, list) else 0})

    errors = validate_actions(actions)
    if errors:
        return {
            "success": False,
            "message": "action validation failed — nothing was executed",
            "data": {
                "status": "failed",
                "validation_errors": errors,
                "completed_steps": [],
                "failed_step": {"index": 0, "type": "validation",
                                "reason": "; ".join(errors)},
                "evidence": {"last_verify": None},
                "timings_ms": {"total": _ms_since(start), "steps": []},
                "actions_total": 0,
            },
        }

    completed: list[dict] = []
    executed_sigs: set[str] = set()
    screenshots = 0
    evidence: dict = {"last_verify": None}
    last_verified = -1  # index of the last step whose postcondition was proven
    attempted_unverified = 0

    for index, step in enumerate(actions):
        if runtime.registry.cancel_requested(task_id):
            events.emit(events.CANCELLED, task_id=task_id, tool="hands_batch",
                        status="CANCELLED", summary="cancelled by the user before step "
                        f"{index}")
            runtime.registry.finish(task_id, "cancelled", "user requested cancellation")
            return _make_result(task_id, "cancelled", completed,
                                failed_step={"index": index, "type": step.get("type"),
                                             "reason": "cancelled by the user"},
                                evidence=evidence, start=start,
                                checkpoint_id=_make_checkpoint(task_id, index, actions, page.url,
                                                               last_verified, attempted_unverified))
        if time.monotonic() > deadline:
            return _make_result(task_id, "failed", completed, failed_step={
                               "index": index, "type": step.get("type"),
                               "reason": "task deadline exceeded"},
                           evidence=evidence, start=start,
                           checkpoint_id=_make_checkpoint(task_id, index, actions, page.url, last_verified, attempted_unverified))
        sig = _step_signature(step)
        consequential = _is_consequential(step, resolver)
        if consequential and sig in executed_sigs:
            return _make_result(task_id, "blocked", completed,
                           failed_step={"index": index, "type": "click",
                                        "reason": "duplicate_submission_refused: identical consequential action already executed in this task"},
                           evidence=evidence, start=start, blocked=True)
        executed_sigs.add(sig)

        step_start = time.monotonic()
        timeout_s = step.get("timeout_ms", DEFAULT_STEP_TIMEOUT_MS) / 1000.0
        try:
            await asyncio.wait_for(
                _execute_step(step, page, resolver, allow_consequential,
                              max_step_screenshot=screenshots < MAX_SCREENSHOTS,
                              evidence=evidence, task_id=task_id),
                timeout=timeout_s,
            )
        except _RestrictionHit as hit:
            remaining = actions[index:]
            return await _handle_restriction(hit.classification, page, completed, remaining, task_id,
                                             completed=completed, start=start, evidence=evidence)
        except _NeedsUser as needs:
            cid = _make_checkpoint(task_id, index, actions, page.url, last_verified, attempted_unverified)
            return _make_result(task_id, "needs_user", completed,
                           failed_step={"index": index, "type": step.get("type"),
                                        "reason": needs.reason},
                           needs_user={"url": _strip_url(page.url), "reason": needs.reason,
                                       "checkpoint_id": cid},
                           evidence=evidence, start=start, checkpoint_id=cid)
        except (asyncio.TimeoutError, _StepFailed) as exc:
            reason = (f"step timed out after {int(timeout_s * 1000)}ms"
                      if isinstance(exc, asyncio.TimeoutError) else exc.reason)
            if on_failure == "continue" and not consequential:
                completed.append({"index": index, "type": step.get("type"),
                                  "detail": f"FAILED (continued): {reason}",
                                  "ms": _ms_since(step_start), "failed": True})
                continue
            cid = _make_checkpoint(task_id, index, actions, page.url, last_verified, attempted_unverified)
            return _make_result(task_id, "failed", completed,
                           failed_step={"index": index, "type": step.get("type"), "reason": reason},
                           evidence=evidence, start=start, checkpoint_id=cid)
        except Exception as exc:  # defensive: no raw stack traces out of a tool
            if on_failure == "continue" and not consequential:
                completed.append({"index": index, "type": step.get("type"),
                                  "detail": f"FAILED (continued): {type(exc).__name__}",
                                  "ms": _ms_since(step_start), "failed": True})
                continue
            cid = _make_checkpoint(task_id, index, actions, page.url, last_verified, attempted_unverified)
            return _make_result(task_id, "failed", completed,
                           failed_step={"index": index, "type": step.get("type"),
                                        "reason": f"{type(exc).__name__}: {exc}"},
                           evidence=evidence, start=start, checkpoint_id=cid)
        if step.get("type") == "screenshot":
            screenshots += 1
        was_verified = step.get("type") in ("verify_text", "verify_url")
        if was_verified:
            last_verified = index
        else:
            attempted_unverified += 1
        completed.append({"index": index, "type": step.get("type"),
                          "detail": resolver.describe(step),
                          "ms": _ms_since(step_start),
                          "verified": was_verified})
        events.emit(events.VERIFICATION if was_verified else events.ACTION,
                    task_id=task_id, tool="hands_batch", status="CONFIRMED" if was_verified else None,
                    summary=f"{step.get('type')} {resolver.describe(step)}",
                    evidence={"index": index, "ms": _ms_since(step_start),
                              "verified": was_verified})

    events.emit(events.TASK_FINISHED, task_id=task_id, tool="hands_batch", status="COMPLETED",
                summary=f"batch finished ({len(completed)} step(s))",
                evidence={"steps": len(completed),
                          "verification": "CONFIRMED" if evidence.get("last_verify") else "UNVERIFIED"})
    runtime.registry.finish(task_id, "completed")
    return _make_result(task_id, "completed", completed, evidence=evidence, start=start)


def _ms_since(t: float) -> int:
    return int((time.monotonic() - t) * 1000)


def _make_result(task_id, status, completed, *, failed_step=None, evidence=None, start,
                 checkpoint_id=None, needs_user=None, retry_scheduled=None, blocked=False) -> dict:
    """Uniform tool envelope: {success, message, data}. success only on verified completion."""
    evidence = evidence or {"last_verify": None}
    verified = evidence.get("last_verify") is not None
    if status == "completed" and not verified:
        message = ("all steps executed — OUTCOME UNVERIFIED (no verify step ran); "
                   "call reflex_verify() with the expected result before treating it as done")
    else:
        message = {
            "completed": "all steps executed and verified",
            "failed": "task failed — see failed_step",
            "blocked": "blocked by safety policy or restriction — no further action taken",
            "needs_user": "human action required — see needs_user",
            "retry_scheduled": "rate-limited — retry after cooldown",
            "cancelled": "cancelled by the user — stopped at a safe boundary",
        }[status]
    return {
        "success": status == "completed" and verified,
        "message": message,
        "data": {
            "status": status,
            "task_id": task_id,
            "completed_steps": completed,
            "failed_step": failed_step,
            "needs_user": needs_user,
            "retry_scheduled": retry_scheduled,
            "blocked": blocked,
            "checkpoint_id": checkpoint_id,
            "evidence": evidence,
            "verification": {
                "status": ("CONFIRMED" if verified else
                           "UNVERIFIED" if status == "completed" else
                           "CANCELLED" if status == "cancelled" else "NOT_RUN"),
                "evidence": evidence.get("last_verify"),
            },
            "timings_ms": {"total": _ms_since(start),
                           "steps": [s.get("ms", 0) for s in completed]},
            "actions_total": len(completed) + (1 if failed_step else 0),
        },
    }


def _make_checkpoint(task_id, next_index, actions, url, last_verified=-1,
                     attempted_unverified=0) -> str:
    """Checkpoint the task. `last_verified` is the last step whose postcondition
    was proven — steps that merely ran are counted separately and never claimed
    as verified."""
    return checkpoint.create(task_id, last_verified, list(actions[next_index:]),
                             url or "", reason="task paused at an unrecoverable point",
                             resume_condition="re-inspect page; resume only from the last verified step",
                             attempted_unverified=attempted_unverified)


async def _execute_step(step, page, resolver, allow_consequential, *,
                        max_step_screenshot, evidence, task_id):
    a_type = step["type"]

    if a_type == "goto":
        url = step["url"]
        remaining = await restrictions.cooldown_remaining(restrictions.domain_of(url))
        if remaining > 0:
            raise _RestrictionHit({"kind": "rate_limit", "http_status": 429,
                                   "retry_after_s": remaining,
                                   "evidence": f"cooldown active for {restrictions.domain_of(url)}",
                                   "domain": restrictions.domain_of(url)})
        try:
            response = await page.goto(url, wait_until="load",
                                       timeout=step.get("timeout_ms", 30000))
        except Exception as exc:
            raise _StepFailed(f"navigation failed: {restrictions.network_failure(exc, url)['evidence']}")
        status = response.status if response else None
        retry_after = None
        try:
            retry_after = response.headers.get("retry-after") if response else None
        except Exception:
            retry_after = None
        text = await _body_text(page)
        hit = restrictions.classify(status, text, url, retry_after)
        if hit and hit["kind"] in ("captcha", "rate_limit", "access_denied", "paywall", "auth_expired"):
            raise _RestrictionHit(hit)
        if status is not None and status >= 400:
            raise _StepFailed(f"HTTP {status} from {restrictions.domain_of(url)}")
        return

    if a_type == "click":
        label = str(resolver.label_of(step) or step["target"])
        if safety.is_dangerous_label(label):
            if not allow_consequential:
                raise _NeedsUser(f"consequential action {label!r} is not permitted here — "
                                 "run it sequentially with hands_batch/hands_click after reflex_ask approval")
            from . import permissions as _permissions
            decision = await _permissions.authorize(
                "consequential", tool="hands_click", target=label, risk="high",
                action=f"consequential click: {label!r}",
                url=page.url, task_id=task_id)
            if not decision.allowed:
                spec = _permissions.required_action_spec("hands_click", "consequential",
                                                         label, page.url, task_id)
                raise _NeedsUser(
                    f"fresh reflex_ask() approval is required before clicking {label!r}\n"
                    f"required_action: {json.dumps(spec)}")
        locator, how, error = await resolver.resolve_click(step)
        if error:
            raise _StepFailed(error)
        url_before = page.url
        await locator.click()
        evidence["last_click"] = {"target": label, "how": how,
                                  "url_before": url_before, "url_after": page.url,
                                  "navigated": page.url != url_before}
        return

    if a_type == "fill":
        target = step["field_ref"]
        text_to_fill = step.get("text") or ""
        if text_to_fill == "<redacted>":
            raise _NeedsUser("fill step restored from checkpoint without its text "
                             "(secrets are never stored); supply the text explicitly")
        locator, how, error = await resolver.resolve_fill(step)
        if error:
            raise _StepFailed(error)
        # sensitive-field policy applies to ref-based fills on the shared page;
        # the resolver enforces the same rule for parallel pages.
        await locator.fill("")
        await locator.fill(text_to_fill)
        # postcondition: a successful fill() is not proof the page kept the value
        try:
            actual = await asyncio.wait_for(locator.input_value(), timeout=3.0)
        except Exception:
            actual = None
        if actual is None:
            evidence["last_fill"] = {"field_ref": target, "how": how,
                                     "chars": len(text_to_fill), "verified": False}
            return
        if actual != text_to_fill:
            raise _StepFailed(
                f"POSTCONDITION_FAILED: field {target!r} holds {len(actual)} chars after typing "
                f"{len(text_to_fill)} — the page stripped, masked or reformatted the input")
        evidence["last_fill"] = {"field_ref": target, "how": how,
                                 "chars": len(text_to_fill), "verified": True}
        return

    if a_type == "press":
        key = str(step["key"]).strip()
        from .hands import KEY_PATTERN, NAMED_KEYS
        if not KEY_PATTERN.match(key):
            raise _StepFailed(f"unsupported key: {key!r}")
        parts = [p.lower() for p in key.split("+")]
        if any(p not in NAMED_KEYS and not p.isalnum() for p in parts):
            raise _StepFailed(f"unsupported key chord: {key!r}")
        await page.keyboard.press("+".join(parts))
        return

    if a_type == "scroll":
        delta = int(step.get("amount", 3)) * 300
        if step.get("direction", "down") == "up":
            delta = -delta
        await page.mouse.wheel(0, delta)
        return

    if a_type == "wait_for":
        condition = step["condition"]
        value = str(step["value"])
        if condition == "text":
            await page.get_by_text(value, exact=False).first.wait_for(state="visible")
            evidence["wait_for"] = {"text": value, "found": True}
            return
        await page.locator(value).first.wait_for(state="attached",
                                                 timeout=step.get("timeout_ms", 10000))
        evidence["wait_for"] = {"selector": value, "found": True}
        return

    if a_type == "verify_text":
        expected = str(step["expected"])
        window = await _evidence_window(page, expected)
        if window is None:
            raise _StepFailed(f"verify_text failed: {expected!r} not present on page")
        evidence["last_verify"] = {"type": "verify_text", "expected": expected,
                                   "found": True, "evidence": window}
        return

    if a_type == "verify_url":
        expected = str(step["expected"])
        if expected.lower() not in (page.url or "").lower():
            raise _StepFailed(f"verify_url failed: {expected!r} not in {page.url!r}")
        evidence["last_verify"] = {"type": "verify_url", "expected": expected, "url": page.url}
        return

    if a_type == "screenshot":
        if not max_step_screenshot:
            raise _StepFailed("screenshot quota exceeded (max 10 per task)")
        png = await page.screenshot()
        evidence["screenshot"] = {"bytes": len(png), "in_memory_only": True}
        return

    raise _StepFailed(f"unsupported action: {a_type!r}")


class BatchResolver:
    """Refs-first resolver for the SHARED page; text fallback for non-ref targets."""

    REF_RE = re.compile(r"^(btn|input|link)_\d+(#\d+)?$")

    def __init__(self, page):
        self.page = page

    def label_of(self, step):
        """Resolve the human-meaningful label (for dangerous-button checks)."""
        key = str(step.get("target") or step.get("field_ref") or "").strip()
        desc = browser.resolve_ref(key)
        if desc is not None:
            return desc.get("text") or key
        return key

    async def resolve_click(self, step):
        target = str(step["target"]).strip()
        desc = browser.resolve_ref(target)
        if desc is not None:
            return await browser.resolve_locator(desc)
        if self.REF_RE.match(target):
            return None, None, (f"stale reference {target!r} — the page navigated or changed "
                                "since refs were issued; call eyes_see_browser() again")
        for role in ("button", "link"):
            loc = self.page.get_by_role(role, name=target, exact=False)
            if await loc.count() == 1:
                return loc, f"text:{role}", None
        loc = self.page.get_by_text(target, exact=True)
        if await loc.count() == 1:
            return loc, "text", None
        count = await self.page.get_by_text(target, exact=False).count()
        if count > 1:
            return None, None, f"ambiguous target {target!r}: {count} matches"
        return None, None, f"no visible element matches {target!r} — call eyes_see_browser() for refs"

    async def resolve_fill(self, step):
        field_ref = str(step["field_ref"]).strip()
        desc = browser.resolve_ref(field_ref)
        if desc is None:
            if self.REF_RE.match(field_ref):
                return None, None, (f"stale reference {field_ref!r} — the page navigated or changed "
                                    "since refs were issued; call eyes_see_browser() again")
            loc = self.page.get_by_label(field_ref, exact=False)
            if await loc.count() == 1:
                return await self._sensitive_check(loc, field_ref)
            loc = self.page.locator(f'[placeholder="{field_ref}"]')
            if await loc.count() == 1:
                return await self._sensitive_check(loc, field_ref)
            loc = self.page.locator(f'[name="{field_ref}"]')
            if await loc.count() == 1:
                return await self._sensitive_check(loc, field_ref)
            return None, None, (f"unknown field ref/label {field_ref!r} — call eyes_see_browser() "
                                "and use refs, or a unique label/placeholder/name")
        sensitive = safety.is_sensitive_field(
            {"type": desc.get("field_type"), "name": desc.get("name_attr"),
             "id": desc.get("id"), "autocomplete": desc.get("autocomplete"),
             "placeholder": desc.get("placeholder")})
        if sensitive:
            return None, None, f"refusing to fill sensitive field {field_ref!r}"
        if browser.ref_is_stale(desc):
            return None, None, "stale reference — re-scan with eyes_see_browser()"
        return await browser.resolve_locator(desc)

    async def _sensitive_check(self, locator, field_ref):
        attrs = {}
        with contextlib.suppress(Exception):
            attrs = await locator.evaluate(
                "e => ({type: e.type || '', name: e.name || '', id: e.id || '',"
                " autocomplete: e.getAttribute('autocomplete') || '',"
                " placeholder: e.placeholder || ''})")
        if safety.is_sensitive_field(
                {"type": attrs.get("type"), "name": attrs.get("name"), "id": attrs.get("id"),
                 "autocomplete": attrs.get("autocomplete"), "placeholder": attrs.get("placeholder")}):
            return None, None, f"refusing to fill sensitive field {field_ref!r}"
        return locator, "label/placeholder/name", None

    def describe(self, step):
        detail = (step.get("target") or step.get("field_ref") or step.get("url")
                  or step.get("expected") or step.get("key") or "")
        return f"{step.get('type')}: {detail}"


async def resume_checkpoint(cid: str) -> dict:
    """Resume a paused task from a checkpoint — never blindly replays."""
    ckpt = checkpoint.get(cid)
    if not ckpt:
        return {"success": False, "message": f"checkpoint {cid!r} not found or expired",
                "data": {"checkpoint_id": cid}}
    page = await browser.ensure_page()
    url = ckpt.get("url") or "about:blank"
    try:
        response = await page.goto(url, wait_until="load", timeout=30000)
    except Exception as exc:
        return {"success": False, "message": f"resume navigation failed: {exc}",
                "data": {"checkpoint_id": cid, "status": "failed"}}
    status = response.status if response else None
    text = await _body_text(page)
    hit = restrictions.classify(status, text, url,
                                (response.headers.get("retry-after") if response else None))
    if hit:
        return await _restriction_report(cid, ckpt, hit, page)

    # challenge cleared — continue with remaining steps
    remaining = ckpt["remaining_steps"]
    result = await execute_actions(page=page, actions=remaining, resolver=BatchResolver(page),
                                    allow_consequential=True, on_failure="stop",
                                    deadline_ms=config.batch_deadline_ms(),
                                    task_id=ckpt["task_id"])
    checkpoint.clear(cid)
    return result


async def _restriction_report(cid, ckpt, hit, page) -> dict:
    kind = hit["kind"]
    if kind == "rate_limit":
        retry_s = hit.get("retry_after_s") or 60
        await restrictions.set_cooldown(hit.get("domain", ""), retry_s, "rate-limited during resume")
        return {"success": True,
                "message": f"still rate-limited on {hit.get('domain')} — retry after ~{int(retry_s)}s",
                "data": {"status": "retry_scheduled", "checkpoint_id": cid,
                         "retry_scheduled": {"domain": hit.get("domain"),
                                             "retry_after_s": retry_s,
                                             "evidence": hit.get("evidence")}}}
    return {"success": True,
            "message": f"challenge still present ({hit.get('evidence')}) — complete it manually, then resume again",
            "data": {"status": "needs_user", "checkpoint_id": cid,
                     "needs_user": {"url": _strip_url(page.url),
                                    "reason": f"{hit['kind']}: {hit.get('evidence')}",
                                    "checkpoint_id": cid}}}
