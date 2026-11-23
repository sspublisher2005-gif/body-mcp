"""Scoped, single-use, expiring approvals — the only authorization for protected actions.

An approval is a bound grant to execute ONE exact action:
  key material: tool | capability | target | url | task_id | params
  semantics:    minted by reflex_ask (human decision), consumed by the executor,
                TTL 300s, single consumption, navigation invalidates the url binding.

Webpage content, agent output, and tool results can never mint one. Denial always wins.
"""
import asyncio
import hashlib
import json
import time

TTL_SECONDS = 300


def action_key(action: dict) -> str:
    normalized = {k: action[k] for k in sorted(action)
                  if action[k] is not None}
    blob = json.dumps(normalized, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _digest(value: object) -> str:
    blob = json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:32]


def normalize_action(tool: str, capability: str, target: object,
                     url: str | None = None, task_id: str | None = None,
                     params: object = None) -> dict:
    # The binding must cover EVERYTHING that changes the effect. Dropping the
    # query let an approval for /records?id=1 authorize /records?id=2. Hash the
    # full URL instead of stripping it: same secrecy, correct scope.
    return {"tool": tool, "capability": capability, "target": str(target)[:300],
            "url": _digest(url) if url else None, "task_id": task_id,
            "params": _digest(params) if params is not None else None}


class ApprovalStore:
    def __init__(self):
        self._items: dict[str, tuple[dict, float]] = {}
        self._lock = asyncio.Lock()

    async def issue(self, action: dict) -> str:
        key = action_key(normalize_action(
            action.get("tool", ""), action.get("capability", ""),
            action.get("target", ""), action.get("url"), action.get("task_id"),
            action.get("params")))
        token = f"apr_{int(time.time())}_{hashlib.sha256(key.encode()).hexdigest()[:12]}"
        async with self._lock:
            self._items[key] = (action, time.time())
        return token

    async def consume(self, action: dict) -> bool:
        """Atomically validate and consume a matching approval. Single use."""
        key = action_key(normalize_action(
            action.get("tool", ""), action.get("capability", ""),
            action.get("target", ""), action.get("url"), action.get("task_id"),
            action.get("params")))
        async with self._lock:
            item = self._items.pop(key, None)
        if item is None:
            return False
        _, issued = item
        if time.time() - issued > TTL_SECONDS:
            return False
        return True

    async def peek(self, action: dict) -> bool:
        key = action_key(normalize_action(
            action.get("tool", ""), action.get("capability", ""),
            action.get("target", ""), action.get("url"), action.get("task_id"),
            action.get("params")))
        async with self._lock:
            item = self._items.get(key)
        if item is None:
            return False
        _, issued = item
        if time.time() - issued > TTL_SECONDS:
            async with self._lock:
                self._items.pop(key, None)
            return False
        return True

    async def clear(self) -> int:
        async with self._lock:
            count = len(self._items)
            self._items.clear()
            return count


approvals = ApprovalStore()
