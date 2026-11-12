"""Background tasks, undo journal and the self-correction loop."""
import asyncio
import os

from body_mcp import server, tasks, undo


def test_background_task_validates_before_starting():
    result = tasks.start([{"type": "click"}])
    assert result["success"] is False
    assert result["data"]["validation_errors"]


def test_background_task_reports_progress_and_result():
    fixture = "file:///" + os.path.abspath(
        os.path.join(os.path.dirname(__file__), "fixtures", "test_page.html")).replace("\\", "/")
    started = tasks.start([
        {"type": "goto", "url": fixture},
        {"type": "verify_text", "expected": "Body-MCP Search"},
    ])
    assert started["success"] is True
    task_id = started["data"]["task_id"]

    import time

    deadline = time.time() + 60
    snapshot = {}
    while time.time() < deadline:
        snapshot = tasks.status(task_id)["data"]
        if snapshot["state"] in ("completed", "failed", "blocked", "needs_user"):
            break
        time.sleep(0.5)
    assert snapshot["steps_total"] == 2
    assert snapshot["steps_done"] == 2, snapshot
    assert snapshot["state"] == "completed", snapshot
    assert snapshot["result"]["data"]["verification"]["status"] == "CONFIRMED"
    tasks.stop_all()


def test_background_task_can_be_cancelled():
    fixture = "file:///" + os.path.abspath(
        os.path.join(os.path.dirname(__file__), "fixtures", "test_page.html")).replace("\\", "/")
    started = tasks.start([{"type": "goto", "url": fixture},
                           {"type": "scroll", "direction": "down", "amount": 1}])
    assert started["success"] is True
    task_id = started["data"]["task_id"]
    cancelled = tasks.cancel(task_id)
    assert cancelled["success"] is True
    assert "next step boundary" in cancelled["message"]
    tasks.stop_all()


def test_undo_journal_records_typing_and_navigation():
    undo._journal.clear()
    undo.record_typing("input_1#3", "old value", "https://x.test/a")
    undo.record_navigation("https://x.test/b", "https://x.test/a")
    items = undo.entries()
    assert len(items) == 2
    assert items[0]["kind"] == "navigation"
    assert undo.last_undoable()["kind"] == "navigation"


def test_undo_refuses_when_nothing_is_undoable():
    undo._journal.clear()
    undo.record_irreversible("clicked 'Send payment'")
    result = asyncio.run(undo.undo_last())
    assert result["success"] is False
    assert "cannot be undone" in result["message"]


def test_undo_restores_a_typed_value(monkeypatch):
    undo._journal.clear()
    undo.record_typing("input_1#3", "the old value", "https://x.test/a")
    seen = {}

    async def fake_type(field_ref, text):
        seen["field_ref"] = field_ref
        seen["text"] = text
        return {"success": True, "message": "typed", "data": {}}

    from body_mcp import hands

    monkeypatch.setattr(hands, "type_text", fake_type)
    result = asyncio.run(undo.undo_last())
    assert result["success"] is True
    assert seen == {"field_ref": "input_1#3", "text": "the old value"}
    assert undo.entries() == []


def test_undo_listing_marks_irreversible_steps():
    undo._journal.clear()
    undo.record_typing("input_1#3", "v", "")
    undo.record_irreversible("clicked Send")
    items = undo.entries()
    assert items[0]["undoable"] is False
    assert items[1]["undoable"] is True


def test_new_tools_are_exposed():
    async def names():
        tools = await server.mcp.list_tools()
        return [tool.name for tool in tools]

    listed = asyncio.run(names())
    for tool in ("body_task_start", "body_task_status", "body_task_cancel",
                 "body_undo", "body_undo_list"):
        assert tool in listed, tool
