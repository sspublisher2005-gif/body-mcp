"""Execution events — a real activity stream emitted by the executor.

Every event is produced by execution code (never by model output), carries a
task id, a bounded and redacted summary, and an evidence reference. The stream
is the source for the optional local Body Console and for the `body_events`
tool, so the user can see what the body is actually doing.

Privacy: summaries are short and passed through `permissions.redact_target`;
page content, secrets and raw captures never enter the stream.
"""
from __future__ import annotations

import asyncio
import collections
import contextlib
import threading
import time
import uuid

from .permissions import redact_target

MAX_EVENTS = 500
MAX_SUBSCRIBERS = 8
MAX_SUMMARY = 200

# event types
TASK_CREATED = "task_created"
TASK_FINISHED = "task_finished"
TOOL_STARTED = "tool_started"
TOOL_FINISHED = "tool_finished"
OBSERVATION = "observation"
ACTION = "action"
VERIFICATION = "verification"
RETRY = "retry"
APPROVAL_REQUESTED = "approval_requested"
APPROVAL_GRANTED = "approval_granted"
APPROVAL_DENIED = "approval_denied"
BLOCKER = "blocker"
CANCEL_REQUESTED = "cancel_requested"
CANCELLED = "cancelled"
BROWSER_CONNECTED = "browser_connected"
BROWSER_DISCONNECTED = "browser_disconnected"


class Event:
    __slots__ = ("event_id", "ts", "task_id", "type", "status", "tool", "summary",
                 "evidence", "error_code", "user_action_required")

    def __init__(self, *, type: str, task_id: str | None = None, status: str | None = None,
                 tool: str | None = None, summary: str = "", evidence: dict | None = None,
                 error_code: str | None = None, user_action_required: bool = False):
        self.event_id = "ev_" + uuid.uuid4().hex[:12]
        self.ts = time.time()
        self.task_id = task_id
        self.type = type
        self.status = status
        self.tool = tool
        self.summary = redact_target(summary)[:MAX_SUMMARY]
        self.evidence = _safe_evidence(evidence)
        self.error_code = error_code
        self.user_action_required = bool(user_action_required)

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "ts": self.ts,
            "task_id": self.task_id,
            "type": self.type,
            "status": self.status,
            "tool": self.tool,
            "summary": self.summary,
            "evidence": self.evidence,
            "error_code": self.error_code,
            "user_action_required": self.user_action_required,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Event {self.type} {self.status or ''} {self.summary[:40]!r}>"


def _safe_evidence(evidence: dict | None) -> dict:
    """Keep evidence small, scalar and redacted — never page dumps."""
    if not evidence:
        return {}
    out = {}
    for key, value in list(evidence.items())[:12]:
        if isinstance(value, (bool, int, float)) or value is None:
            out[str(key)[:40]] = value
        elif isinstance(value, str):
            out[str(key)[:40]] = redact_target(value)[:120]
        elif isinstance(value, (list, tuple)):
            out[str(key)[:40]] = len(value)
        elif isinstance(value, dict):
            out[str(key)[:40]] = _safe_evidence(value)
        else:
            out[str(key)[:40]] = str(value)[:80]
    return out


class EventBus:
    """Thread-safe ring buffer + per-subscriber queues."""

    def __init__(self, max_events: int = MAX_EVENTS):
        self._events: collections.deque[Event] = collections.deque(maxlen=max_events)
        self._subscribers: list[asyncio.Queue] = []
        self._lock = threading.Lock()
        self._counter = 0

    def emit(self, event: Event) -> Event:
        with self._lock:
            self._counter += 1
            self._events.append(event)
            subscribers = list(self._subscribers)
        for queue in subscribers:
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)  # a slow console must never block the executor
        return event

    def recent(self, limit: int = 100, since: float | None = None) -> list[dict]:
        with self._lock:
            events = list(self._events)
        if since is not None:
            events = [e for e in events if e.ts > since]
        return [e.to_dict() for e in events[-max(1, min(limit, MAX_EVENTS)):]]

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self._lock:
            if len(self._subscribers) >= MAX_SUBSCRIBERS:
                self._subscribers.pop(0)
            self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in self._subscribers:
                self._subscribers.remove(queue)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


bus = EventBus()


def emit(type: str, **kwargs) -> Event:
    """Shorthand: bus.emit(Event(type=type, **kwargs))."""
    return bus.emit(Event(type=type, **kwargs))
