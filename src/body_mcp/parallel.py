"""Bounded parallel execution for independent browser tasks.

Rules:
  - Default max 2 concurrent workers, clamped to a hard max (config).
  - Each task gets an ISOLATED browser context + page (no shared cookies/storage/REF_MAP).
  - Consequential clicks (pay/delete/send/...) are refused in parallel mode — they
    must run sequentially via hands_batch with fresh approval.
  - Target resolution in parallel uses visible text / label / placeholder / name —
    snapshot refs (btn_N) belong to the shared page and do NOT cross into isolated pages.
  - Per-service cooldowns are shared: one worker uncovering 429 blocks its siblings.
  - Per-task deadline + overall deadline; tasks are cancellable; contexts are always closed.
"""
import asyncio
import contextlib

from . import browser, config, safety
from .batch import execute_actions, validate_actions

MAX_TASKS = 8


def _parallel_consequential_hit(actions: list[dict]) -> str | None:
    for step in actions:
        if step.get("type") == "click" and safety.is_dangerous_label(str(step.get("target", ""))):
            return str(step["target"])
    return None


class ParallelResolver:
    """Text/label targeting for an isolated page (no snapshot refs)."""

    def __init__(self, page):
        self.page = page

    def label_of(self, step):
        return str(step.get("target") or step.get("field_ref") or "")

    async def resolve_click(self, step):
        target = str(step["target"]).strip()
        for role in ("button", "link"):
            loc = self.page.get_by_role(role, name=target, exact=False)
            if await loc.count() == 1:
                return loc, f"text:{role}", None
        loc = self.page.get_by_text(target, exact=False)
        count = await loc.count()
        if count == 1:
            return loc, "text", None
        if count > 1:
            return None, None, f"ambiguous target {target!r}: {count} matches — be more specific"
        return None, None, f"no visible element matches {target!r}"

    async def resolve_fill(self, step):
        target = str(step["field_ref"]).strip()
        # 1) label
        loc = self.page.get_by_label(target, exact=False)
        if await loc.count() == 1:
            return await self._sensitive_check(loc, target)
        # 2) placeholder
        loc = self.page.locator(f'[placeholder="{target}"]')
        if await loc.count() == 1:
            return await self._sensitive_check(loc, target)
        # 3) name attribute
        loc = self.page.locator(f'[name="{target}"]')
        if await loc.count() == 1:
            return await self._sensitive_check(loc, target)
        total = (await self.page.get_by_label(target, exact=False).count()
                 + await self.page.locator(f'[placeholder="{target}"]').count()
                 + await self.page.locator(f'[name="{target}"]').count())
        if total > 1:
            return None, None, f"ambiguous field {target!r}: {total} matches — be more specific"
        return None, None, f"no field matches label/placeholder/name {target!r}"

    async def _sensitive_check(self, locator, target):
        try:
            attrs = await locator.evaluate(
                "e => ({type: e.type || '', name: e.name || '', id: e.id || '',"
                " autocomplete: e.getAttribute('autocomplete') || '',"
                " placeholder: e.placeholder || ''})")
        except Exception:
            attrs = {}
        if safety.is_sensitive_field(
                {"type": attrs.get("type"), "name": attrs.get("name"), "id": attrs.get("id"),
                 "autocomplete": attrs.get("autocomplete"),
                 "placeholder": attrs.get("placeholder")}):
            return None, None, f"refusing to fill sensitive field {target!r} — the user must type it"
        return locator, "label/placeholder/name", None

    def describe(self, step):
        return f"{step.get('type')}: {step.get('target') or step.get('field_ref') or step.get('url') or step.get('expected') or ''}"


async def _run_single_task(task: dict, task_id: str, semaphore: asyncio.Semaphore) -> dict:
    deadline_ms = min(int(task.get("deadline_ms") or config.task_deadline_ms()),
                      config.task_deadline_ms())
    async with semaphore:
        context = None
        try:
            context, page = await browser.new_isolated_context()
            resolver = ParallelResolver(page)
            return await execute_actions(
                page=page, actions=task["actions"], resolver=resolver,
                allow_consequential=False, on_failure=task.get("on_failure", "stop"),
                deadline_ms=deadline_ms, task_id=task_id)
        except Exception as exc:
            return {"success": False,
                    "message": f"task {task_id} crashed: {type(exc).__name__}: {exc}",
                    "data": {"status": "failed", "completed_steps": [],
                             "failed_step": {"index": -1, "type": "task",
                                             "reason": f"{type(exc).__name__}: {exc}"}}}
        finally:
            if context is not None:
                with contextlib.suppress(Exception):
                    await context.close()


async def run_parallel(tasks, max_concurrency: int | None = None) -> dict:
    if not isinstance(tasks, list) or not tasks:
        return {"success": False, "message": "tasks must be a non-empty list",
                "data": {"status": "failed"}}
    if len(tasks) > MAX_TASKS:
        return {"success": False, "message": f"too many tasks: {len(tasks)} > {MAX_TASKS}",
                "data": {"status": "failed"}}
    limit = config.max_concurrency()
    if max_concurrency:
        with contextlib.suppress(TypeError, ValueError):
            limit = max(1, min(config.hard_max_concurrency(), int(max_concurrency)))

    prepared = []
    for i, task in enumerate(tasks):
        if not isinstance(task, dict) or not isinstance(task.get("actions"), list):
            return {"success": False,
                    "message": f"task {i}: must be an object with an actions list",
                    "data": {"status": "failed"}}
        tid = str(task.get("id") or f"task_{i + 1}")
        dangerous = _parallel_consequential_hit(task["actions"])
        if dangerous is not None:
            prepared.append({"blocked": True, "task_id": tid,
                             "reason": f"consequential action {dangerous!r} refused in parallel mode — "
                                       "run it via hands_batch with reflex_ask approval"})
            continue
        errors = validate_actions(task["actions"])
        if errors:
            prepared.append({"blocked": True, "task_id": tid,
                             "reason": f"validation failed: {'; '.join(errors)}"})
            continue
        prepared.append({"blocked": False, "task_id": tid, "task": task})

    semaphore = asyncio.Semaphore(limit)
    runnable = [p for p in prepared if not p["blocked"]]
    try:
        overall = asyncio.wait_for(
            asyncio.gather(*[ _run_single_task(p["task"], p["task_id"], semaphore)
                              for p in runnable ]),
            timeout=config.parallel_deadline_ms() / 1000.0)
        task_results = list(await overall)
    except asyncio.TimeoutError:
        task_results = [{"success": False,
                         "message": "overall parallel deadline exceeded — task cancelled",
                         "data": {"status": "failed", "completed_steps": [],
                                  "failed_step": {"index": -1, "type": "task",
                                                  "reason": "parallel deadline exceeded"}}}
                        for _ in runnable]

    results: list[dict] = []
    run_iter = iter(task_results)
    for p in prepared:
        if p["blocked"]:
            results.append({"task_id": p["task_id"], "status": "blocked",
                            "message": p["reason"],
                            "completed_steps": [], "failed_step": None,
                            "success": False, "timings_ms": {"total": 0, "steps": []}})
            continue
        res = next(run_iter)
        results.append({"task_id": p["task_id"],
                        "status": res.get("data", {}).get("status", "failed"),
                        "success": res.get("success", False),
                        "message": res.get("message", ""),
                        "completed_steps": res.get("data", {}).get("completed_steps", []),
                        "failed_step": res.get("data", {}).get("failed_step"),
                        "evidence": res.get("data", {}).get("evidence"),
                        "timings_ms": res.get("data", {}).get("timings_ms")})

    summary = {k: sum(1 for r in results if r["status"] == k)
               for k in ("completed", "failed", "blocked", "needs_user", "retry_scheduled")}
    ok = summary["completed"] == len(results)
    return {"success": ok,
            "message": ("all parallel tasks completed and verified" if ok else
                        f"parallel run finished with issues — completed {summary['completed']}/{len(results)}; "
                        "see per-task results"),
            "data": {"status": "completed" if ok else "partial",
                     "summary": summary,
                     "results": results,
                     "limits": {"max_concurrency": limit,
                                "hard_max_concurrency": config.hard_max_concurrency(),
                                "max_tasks": MAX_TASKS,
                                "task_deadline_ms": config.task_deadline_ms(),
                                "overall_deadline_ms": config.parallel_deadline_ms()}}}
