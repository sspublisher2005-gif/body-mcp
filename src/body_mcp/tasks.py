"""Background work: long tasks run without blocking the agent, and report progress.

An MCP call is synchronous, so a five-minute batch would freeze the session. This
runs it in the background instead:

  body_task_start(actions)   -> a task id immediately, the work continues
  body_task_status(task_id)  -> progress: steps done, elapsed, last evidence
  body_task_cancel(task_id)  -> stops at the next step boundary

The background work runs on its OWN isolated browser context (never the page the
agent is using), in its own event loop, reports every step as an event (the console
shows them live), and is cancellable and verifiable - the result carries the same
verification evidence as a foreground batch.
"""
from __future__ import annotations

import asyncio
import contextlib
import threading
import time
import uuid

from . import batch, events, runtime

MAX_TASKS = 8

_tasks: dict[str, "BackgroundTask"] = {}


class BackgroundTask:
    def __init__(self, task_id: str, actions: list[dict]):
        self.task_id = task_id
        self.actions = actions
        self.state = "starting"
        self.steps_done = 0
        self.steps_total = len(actions)
        self.started = time.time()
        self.finished = None
        self.result = None
        self.error = None
        self.thread: threading.Thread | None = None
        self.last_evidence = None

    def snapshot(self) -> dict:
        elapsed = (self.finished or time.time()) - self.started
        return {
            "task_id": self.task_id,
            "state": self.state,
            "steps_done": self.steps_done,
            "steps_total": self.steps_total,
            "elapsed_s": round(elapsed, 1),
            "percent": round(100 * self.steps_done / max(1, self.steps_total), 1),
            "error": self.error,
            "last_evidence": self.last_evidence,
            "result": self.result,
        }


async def _run_async(task: BackgroundTask) -> None:
    from . import browser as browser_module

    task.state = "running"
    runtime.registry.set_tool(task.task_id, "background_batch")
    playwright = None
    instance = None
    context = None
    try:
        # its OWN browser instance: a background task must never touch the managed
        # browser (or the page the agent is using)
        playwright, instance = await browser_module.launch_isolated_browser()
        context = await instance.new_context()
        page = await context.new_page()
        resolver = batch.BatchResolver(page)
        result = await batch.execute_actions(
            page=page, actions=task.actions, resolver=resolver, allow_consequential=True,
            on_failure="stop", deadline_ms=600000, task_id=task.task_id)
        task.result = result
        task.steps_done = len(result.get("data", {}).get("completed_steps") or [])
        task.state = (result.get("data", {}).get("status") or "completed")
        task.last_evidence = result.get("data", {}).get("verification")
        events.emit(events.TASK_FINISHED, task_id=task.task_id, tool="body_task_start",
                    status=str(task.state).upper(),
                    summary=f"background task finished: {task.steps_done}/{task.steps_total} step(s)",
                    evidence={"task_id": task.task_id, "verification": task.last_evidence})
    except Exception as exc:
        task.error = f"{type(exc).__name__}: {exc}"
        task.state = "failed"
        events.emit(events.TASK_FINISHED, task_id=task.task_id, tool="body_task_start",
                    status="FAILED", summary="background task failed", error_code="TASK_FAILED",
                    evidence={"error": task.error[:200]})
    finally:
        task.finished = time.time()
        if context is not None:
            with contextlib.suppress(Exception):
                await context.close()
        if instance is not None:
            await browser_module.close_isolated_browser(playwright, instance)


def _runner(task: BackgroundTask) -> None:
    """The background thread: its own event loop, isolated context, cancellable."""
    try:
        asyncio.run(_run_async(task))
    except Exception as exc:  # the loop itself failed
        task.error = f"{type(exc).__name__}: {exc}"
        task.state = "failed"
        task.finished = time.time()


def start(actions: list[dict]) -> dict:
    """Start a batch in the background and return its task id immediately."""
    # Reap finished tasks first: otherwise 8 completed tasks lock out all future
    # background work forever.
    for _id, _task in list(_tasks.items()):
        if _task.state in ("completed", "failed", "blocked", "cancelled", "needs_user"):
            _tasks.pop(_id, None)
    if len(_tasks) >= MAX_TASKS:
        return {"success": False,
                "message": f"too many background tasks (max {MAX_TASKS}) - cancel one first",
                "data": {}}
    errors = batch.validate_actions(actions)
    if errors:
        return {"success": False, "message": "the batch is invalid - nothing was started",
                "data": {"validation_errors": errors}}
    task_id = "bg_" + uuid.uuid4().hex[:10]
    task = BackgroundTask(task_id, actions)
    _tasks[task_id] = task
    runtime.registry.create(label="background_batch", task_id=task_id)
    task.thread = threading.Thread(target=_runner, args=(task,), daemon=True,
                                   name=f"body-bg-{task_id}")
    task.thread.start()
    events.emit(events.TASK_CREATED, task_id=task_id, tool="body_task_start", status="STARTED",
                summary=f"background batch started ({len(actions)} step(s))",
                evidence={"task_id": task_id, "steps": len(actions)})
    return {"success": True,
            "message": f"background task {task_id} started ({len(actions)} step(s))",
            "data": {"task_id": task_id, "steps_total": len(actions),
                     "how": "poll body_task_status(task_id) for progress"}}


def status(task_id: str) -> dict:
    """Progress of a background task."""
    task = _tasks.get(task_id)
    if task is None:
        return {"success": False, "message": f"no such task: {task_id}", "data": {}}
    return {"success": True,
            "message": f"{task.state} ({task.steps_done}/{task.steps_total})",
            "data": task.snapshot()}


def cancel(task_id: str) -> dict:
    """Ask a background task to stop (it stops at the next step boundary)."""
    task = _tasks.get(task_id)
    if task is None:
        return {"success": False, "message": f"no such task: {task_id}", "data": {}}
    runtime.registry.request_cancel(task_id)
    events.emit(events.CANCEL_REQUESTED, task_id=task_id, tool="body_task_cancel",
                status="CANCEL_REQUESTED", summary="cancellation requested")
    return {"success": True,
            "message": "cancellation requested - the task stops at the next step boundary",
            "data": {"task_id": task_id, "state": task.state}}


def list_tasks() -> list[dict]:
    return [task.snapshot() for task in _tasks.values()]


def stop_all() -> int:
    count = 0
    for task_id in list(_tasks):
        if cancel(task_id).get("success"):
            count += 1
    return count
