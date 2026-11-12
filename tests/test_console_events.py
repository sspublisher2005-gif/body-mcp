"""Event stream + Body Console: real events, loopback-only, token-protected."""
import asyncio
import json
import urllib.error
import urllib.request

from body_mcp import console as console_mod
from body_mcp import events, runtime, server


def _get(url: str, headers: dict | None = None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _post(url: str, headers: dict | None = None):
    request = urllib.request.Request(url, data=b"", headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def test_events_are_emitted_by_the_executor_not_the_model():
    async def flow():
        events.bus.clear()
        await server.eyes_see_browser("file:///" + __file__.replace("\\", "/"))
        types = [e["type"] for e in events.bus.recent(limit=50)]
        assert types, "the executor must emit events"

    asyncio.run(flow())


def test_event_payload_is_bounded_and_redacted():
    events.bus.clear()
    events.emit(events.ACTION, tool="hands_click", summary="click https://x.test/a?token=secret123",
                evidence={"url": "https://x.test/a?token=secret123", "count": 3})
    item = events.bus.recent(limit=1)[0]
    assert "secret123" not in json.dumps(item)
    assert item["evidence"]["count"] == 3
    assert len(item["summary"]) <= 200


def test_body_events_tool_reports_state():
    result = asyncio.run(server.body_events(limit=10))
    assert result["success"] is True
    assert "events" in result["data"]


def test_console_requires_token_and_loopback_host():
    console = console_mod.get_console()
    console.port = 8791
    console.start()
    try:
        base = f"http://127.0.0.1:{console.port}"
        status, _ = _get(base + "/api/state")
        assert status == 401, "the console must not answer without the token"

        status, body = _get(base + "/api/state?token=" + console.token)
        assert status == 200
        assert "events" in body

        status, _ = _get(base + "/api/state?token=" + console.token,
                         headers={"Host": "evil.example.com"})
        assert status == 403, "a non-loopback Host header must be rejected"

        status, _ = _get(base + "/api/state?token=" + console.token,
                         headers={"Origin": "http://evil.example.com"})
        assert status == 403, "a foreign Origin must be rejected"
    finally:
        console.stop()


def test_console_cancel_button_requests_cancellation():
    console = console_mod.get_console()
    console.port = 8792
    console.start()
    try:
        task_id = runtime.registry.create(label="test")
        status, body = _post(f"http://127.0.0.1:{console.port}/api/cancel?token={console.token}")
        assert status == 200
        assert json.loads(body)["cancelled"] == task_id
        assert runtime.registry.cancel_requested(task_id) is True
    finally:
        console.stop()


def test_console_page_renders_the_timeline():
    console = console_mod.get_console()
    console.port = 8793
    console.start()
    try:
        status, body = _get(f"http://127.0.0.1:{console.port}/?token={console.token}")
        assert status == 200
        assert "Body-MCP console" in body
        assert "/api/state" in body
    finally:
        console.stop()


def test_task_registry_cancellation_lifecycle():
    task_id = runtime.registry.create(label="x")
    assert runtime.registry.active()["task_id"] == task_id
    assert runtime.registry.request_cancel(task_id) == task_id
    assert runtime.registry.cancel_requested(task_id) is True
    runtime.registry.finish(task_id, "cancelled")
    assert runtime.registry.get(task_id)["state"] == "cancelled"
    assert runtime.registry.cancel_requested("task_missing") is False
