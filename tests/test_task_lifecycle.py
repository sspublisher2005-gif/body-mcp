"""Task lifecycle: identity, cancellation and reuse (regression coverage)."""
import asyncio

from body_mcp import runtime, server


def test_cancel_before_start_is_remembered():
    task_id = runtime.registry.request_cancel("cancel-before-start")
    assert task_id == "cancel-before-start"
    assert runtime.registry.cancel_requested("cancel-before-start") is True


def test_reusing_a_task_id_keeps_the_cancel_request():
    runtime.registry.request_cancel("reuse-me")
    runtime.registry.create(label="batch", task_id="reuse-me")
    assert runtime.registry.cancel_requested("reuse-me") is True


def test_cancelled_batch_reports_cancelled_not_completed():
    async def flow():
        runtime.registry.request_cancel("batch-cancel-test")
        return await server.hands_batch(
            [{"type": "scroll", "direction": "down", "amount": 1}], task_id="batch-cancel-test")

    result = asyncio.run(flow())
    assert result["data"]["status"] == "cancelled", result["data"]["status"]
    assert result["data"]["verification"]["status"] == "CANCELLED"
    assert result["success"] is False


def test_body_cancel_tool_reports_the_cancelled_task():
    async def flow():
        task_id = runtime.registry.create(label="tool-cancel")
        result = await server.body_cancel(task_id)
        return task_id, result

    task_id, result = asyncio.run(flow())
    assert result["success"] is True
    assert result["data"]["task_id"] == task_id
    assert runtime.registry.cancel_requested(task_id) is True


def test_parallel_results_carry_the_task_id():
    async def flow():
        return await server.hands_parallel([
            {"id": "alpha", "actions": [{"type": "scroll", "direction": "down", "amount": 1}]},
            {"id": "beta", "actions": [{"type": "scroll", "direction": "down", "amount": 1}]},
        ])

    result = asyncio.run(flow())
    ids = [r.get("task_id") for r in result["data"]["results"]]
    assert ids == ["alpha", "beta"], ids
