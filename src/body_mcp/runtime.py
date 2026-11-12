"""Task runtime: identity, lifecycle and cancellation.

A task is the unit of ownership for a browser session: its id appears in every
event, in every audit record and in every scoped approval, so two concurrent
tasks can never use each other's authorization.

Cancellation is cooperative: the executor checks `cancel_requested` between
steps, so a cancelled task stops at a safe boundary and reports CANCELLED
instead of pretending to finish.
"""
from __future__ import annotations

import threading
import time
import uuid

STATES = ("running", "completed", "failed", "blocked", "cancelled", "needs_user")


class TaskRegistry:
    def __init__(self, max_tasks: int = 50):
        self._tasks: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._max = max_tasks

    def create(self, label: str = "", task_id: str | None = None) -> str:
        tid = task_id or ("task_" + uuid.uuid4().hex[:12])
        with self._lock:
            existing = self._tasks.get(tid)
            if existing is not None:
                # a task id is reused on purpose (e.g. resuming after an approval):
                # keep its lifecycle state and any pending cancellation
                existing["label"] = label[:120] or existing["label"]
                existing["state"] = "running"
                existing["updated"] = time.time()
                return tid
            self._tasks[tid] = {"task_id": tid, "label": label[:120], "state": "running",
                                "created": time.time(), "updated": time.time(),
                                "cancel_requested": False, "tool": None}
            if len(self._tasks) > self._max:
                oldest = min(self._tasks, key=lambda t: self._tasks[t]["created"])
                self._tasks.pop(oldest, None)
        return tid

    def get(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def finish(self, task_id: str, state: str, detail: str = "") -> None:
        if state not in STATES:
            state = "failed"
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task["state"] = state
            task["detail"] = detail[:200]
            task["updated"] = time.time()

    def set_tool(self, task_id: str, tool: str | None) -> None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task["tool"] = tool
                task["updated"] = time.time()

    def request_cancel(self, task_id: str | None = None) -> str | None:
        """Request cancellation of one task (or the newest running task).

        A cancellation for a task id that has not started yet is remembered, so a
        task that is launched later with that id stops immediately.
        """
        with self._lock:
            if task_id is None:
                running = [t for t in self._tasks.values() if t["state"] == "running"]
                if not running:
                    return None
                task = max(running, key=lambda t: t["created"])
            else:
                task = self._tasks.get(task_id)
                if task is None:
                    self._tasks[task_id] = {
                        "task_id": task_id, "label": "cancel requested before start",
                        "state": "running", "created": time.time(), "updated": time.time(),
                        "cancel_requested": True, "tool": None}
                    return task_id
            task["cancel_requested"] = True
            task["updated"] = time.time()
            return task["task_id"]

    def cancel_requested(self, task_id: str | None) -> bool:
        if not task_id:
            return False
        with self._lock:
            task = self._tasks.get(task_id)
            return bool(task and task["cancel_requested"])

    def list_tasks(self) -> list[dict]:
        with self._lock:
            return [dict(t) for t in sorted(self._tasks.values(), key=lambda t: t["created"])]

    def active(self) -> dict | None:
        with self._lock:
            running = [t for t in self._tasks.values() if t["state"] == "running"]
            if not running:
                return None
            return dict(max(running, key=lambda t: t["created"]))


registry = TaskRegistry()
