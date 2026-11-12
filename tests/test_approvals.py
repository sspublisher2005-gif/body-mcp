"""Scoped approval contract: bound to one action, single use, expiring, task-bound.

These are the properties the whole permission model rests on, so they are tested
directly against body_mcp.approvals (not through a mock).
"""
import asyncio
import json

from body_mcp import permissions
from body_mcp.approvals import approvals, normalize_action


def _spec(task="task-1", url="https://x.test/a", target="Delete everything"):
    return permissions.required_action_spec("hands_click", "consequential", target, url, task)


def test_approval_is_single_use():
    async def flow():
        await approvals.clear()
        spec = _spec()
        await approvals.issue(spec)
        assert await approvals.consume(spec) is True
        assert await approvals.consume(spec) is False
        await approvals.clear()

    asyncio.run(flow())


def test_approval_expires():
    async def flow():
        await approvals.clear()
        spec = _spec()
        await approvals.issue(spec)
        await approvals.peek(spec)
        # force expiry by aging the stored issue time
        key = approvals._items and next(iter(approvals._items))
        issued, when = approvals._items[key]
        approvals._items[key] = (issued, when - 10_000)
        assert await approvals.consume(spec) is False
        await approvals.clear()

    asyncio.run(flow())


def test_approval_does_not_cross_tasks():
    async def flow():
        await approvals.clear()
        spec_a = _spec(task="task-A")
        await approvals.issue(spec_a)
        assert await approvals.consume(_spec(task="task-B")) is False
        assert await approvals.consume(spec_a) is True
        await approvals.clear()

    asyncio.run(flow())


def test_approval_does_not_cross_targets():
    async def flow():
        await approvals.clear()
        spec = _spec(target="Delete everything")
        await approvals.issue(spec)
        assert await approvals.consume(_spec(target="Send invoice")) is False
        await approvals.clear()

    asyncio.run(flow())


def test_approval_does_not_cross_tools_or_urls():
    async def flow():
        await approvals.clear()
        spec = _spec(url="https://x.test/a")
        await approvals.issue(spec)
        assert await approvals.consume(
            permissions.required_action_spec("hands_batch", "consequential",
                                             "Delete everything", "https://x.test/a", "task-1")) is False
        assert await approvals.consume(_spec(url="https://other.test/b")) is False
        await approvals.clear()

    asyncio.run(flow())


def test_concurrent_consume_grants_exactly_once():
    async def flow():
        await approvals.clear()
        spec = _spec()
        await approvals.issue(spec)
        results = await asyncio.gather(*[approvals.consume(spec) for _ in range(8)])
        assert results.count(True) == 1, results
        await approvals.clear()

    asyncio.run(flow())


def test_approval_key_excludes_query_secrets():
    spec = normalize_action("hands_click", "consequential", "Delete",
                            "https://x.test/a?token=secret123", "task-1")
    assert "secret123" not in json.dumps(spec)
    # same page, different query → same binding (no secret in the key)
    other = normalize_action("hands_click", "consequential", "Delete",
                             "https://x.test/a?token=other999", "task-1")
    assert spec == other


def test_approval_store_clear_removes_everything():
    async def flow():
        await approvals.clear()
        await approvals.issue(_spec())
        await approvals.issue(_spec(task="task-2"))
        assert await approvals.clear() == 2
        assert await approvals.peek(_spec()) is False

    asyncio.run(flow())


def test_permission_check_never_consumes_an_approval():
    """check() is a pure decision; only authorize() may consume."""
    async def flow():
        await approvals.clear()
        spec = _spec()
        await approvals.issue(spec)
        decision = permissions.check("consequential", tool="hands_click",
                                     target="Delete everything", risk="high",
                                     action="consequential click")
        assert decision.allowed is False and decision.decision == "ask"
        # still consumable — check() did not eat it
        assert await approvals.consume(spec) is True
        await approvals.clear()

    asyncio.run(flow())
