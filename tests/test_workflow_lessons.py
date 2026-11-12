"""The workflow ledger and the lesson store: the 'learn from failure' loop."""
import asyncio

from body_mcp import lessons, memory, workflow


def test_workflow_ledger_records_the_chain():
    started = workflow.start("open the video and summarise it")
    workflow_id = started["data"]["workflow_id"]
    assert started["success"] is True

    workflow.note(workflow_id, "observation", "results page shows Marc Lou's channel, 164K subs")
    workflow.note(workflow_id, "decision", "open the channel's Latest tab, take the first video")
    workflow.note(workflow_id, "action", "clicked the newest video")
    workflow.note(workflow_id, "verification", "title matches, 42K views, 9d ago")

    report = workflow.report(workflow_id)
    data = report["data"]
    assert data["status"] == "verified"
    assert data["counts"]["observation"] == 1
    assert data["counts"]["decision"] == 1
    assert data["counts"]["action"] == 1
    assert data["counts"]["verification"] == 1
    assert data["decisions"][0]["text"].startswith("open the channel")


def test_workflow_report_flags_a_failed_verification():
    started = workflow.start("do the thing")
    workflow_id = started["data"]["workflow_id"]
    workflow.note(workflow_id, "verification", "FAILED: the field did not keep the value")
    report = workflow.report(workflow_id)
    assert report["data"]["status"] == "failed"


def test_workflow_rejects_an_unknown_kind():
    started = workflow.start("x")
    result = workflow.note(started["data"]["workflow_id"], "guess", "hmm")
    assert result["success"] is False


def test_failed_action_records_a_proposed_lesson():
    memory.clear("workflow")
    result = lessons.record_failure("hands_click", "STALE_REF", "btn_1#3",
                                    "stale reference - the page navigated")
    assert result["success"] is True
    items = lessons.lessons(tool="hands_click")
    assert items, "the lesson should be retrievable"
    assert items[0]["verified"] is False, "a lesson starts as a proposal"
    assert "eyes_see_browser" in items[0]["content"], "the likely fix travels with the lesson"
    assert lessons.hint_for("STALE_REF")
    memory.clear("workflow")


def test_lesson_hints_are_specific():
    assert "eyes_see_browser" in lessons.hint_for("STALE_REF")
    assert "reflex_ask" in lessons.hint_for("APPROVAL_REQUIRED")
    assert "Tesseract" in lessons.hint_for("NO_OCR_ENGINE")
    assert lessons.hint_for("SOMETHING_ELSE", "permission denied by your profile") != ""


def test_failure_capture_records_only_failures():
    memory.clear("workflow")

    from body_mcp import lessons as lessons_module

    @lessons_module.failure_capture
    async def failing_tool():
        return {"success": False, "message": "no OCR engine", "data": {"error_code": "NO_OCR_ENGINE"}}

    @lessons_module.failure_capture
    async def working_tool():
        return {"success": True, "message": "ok", "data": {}}

    asyncio.run(failing_tool())
    asyncio.run(working_tool())
    items = lessons.lessons(tool="failing_tool")
    assert len(items) == 1, "only the failure becomes a lesson"
    memory.clear("workflow")


def test_lesson_tools_are_available():
    memory.clear("workflow")
    listed = asyncio.run(server_list())
    assert "body_lessons" in listed
    assert "body_workflow_start" in listed
    assert "body_workflow_report" in listed


async def server_list() -> list[str]:
    from body_mcp import server

    tools = await server.mcp.list_tools()
    return [tool.name for tool in tools]
