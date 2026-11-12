"""Undo journal: mistakes can be corrected, not just reported.

The body records what it changed, in a way that can be reversed:

  - typing into a field  -> the value that was there before
  - navigating a page    -> the URL that was open before

`body_undo()` restores the most recent reversible change (and says what it did);
`body_undo_list()` shows the journal. Irreversible steps (a click that submitted,
a payment) are never journalled as undoable - they are recorded as "not undoable"
so the agent knows to apologise and ask, not to pretend it rolled back.
"""
from __future__ import annotations

import time

MAX_ENTRIES = 40

_journal: list[dict] = []


def record_typing(field_ref: str, previous_value: str, page_url: str = "") -> dict:
    """Remember the value of a field before the body typed into it."""
    entry = {"kind": "typing", "at": time.time(), "field_ref": field_ref,
             "previous_value": (previous_value or "")[:2000], "page_url": page_url,
             "undoable": True}
    _journal.append(entry)
    _trim()
    return entry


def record_navigation(url: str, previous_url: str) -> dict:
    """Remember the page that was open before a navigation."""
    entry = {"kind": "navigation", "at": time.time(), "url": url,
             "previous_url": previous_url or "", "undoable": bool(previous_url)}
    _journal.append(entry)
    _trim()
    return entry


def record_irreversible(action: str, detail: str = "") -> dict:
    """Record something that cannot be undone (so nobody pretends otherwise)."""
    entry = {"kind": "irreversible", "at": time.time(), "action": action,
             "detail": detail[:300], "undoable": False}
    _journal.append(entry)
    _trim()
    return entry


def _trim() -> None:
    while len(_journal) > MAX_ENTRIES:
        _journal.pop(0)


def entries(limit: int = 20) -> list[dict]:
    return list(reversed(_journal[-limit:]))


def last_undoable() -> dict | None:
    for entry in reversed(_journal):
        if entry.get("undoable"):
            return entry
    return None


async def undo_last() -> dict:
    """Restore the most recent reversible change."""
    from . import hands

    entry = last_undoable()
    if entry is None:
        recent = entries(limit=3)
        note = ("the last change cannot be undone"
                if recent and not recent[0].get("undoable") else "nothing to undo")
        return {"success": False, "message": note,
                "data": {"journal": entries(limit=5)}}

    if entry["kind"] == "typing":
        result = await hands.type_text(entry["field_ref"], entry["previous_value"])
        if result.get("success"):
            _journal.remove(entry)
            return {"success": True,
                    "message": f"restored the previous value of {entry['field_ref']}",
                    "data": {"kind": "typing", "field_ref": entry["field_ref"]}}
        return {"success": False,
                "message": "could not restore the value: " + str(result.get("message"))[:160],
                "data": {"kind": "typing", "field_ref": entry["field_ref"]}}

    if entry["kind"] == "navigation":
        result = await hands.open_url(entry["previous_url"])
        if result.get("success"):
            _journal.remove(entry)
            return {"success": True,
                    "message": f"navigated back to {entry['previous_url']}",
                    "data": {"kind": "navigation", "url": entry["previous_url"]}}
        return {"success": False,
                "message": "could not navigate back: " + str(result.get("message"))[:160],
                "data": {"kind": "navigation"}}

    return {"success": False, "message": "nothing undoable", "data": {}}
