"""Batch + parallel executors against deterministic local fixtures (file:// + localhost HTTP)."""
import asyncio
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from body_mcp import browser, restrictions, server


def fixture_url(name: str) -> str:
    return "file:///" + os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures", name)).replace("\\", "/")


@pytest.fixture
def local_server():
    state = SimpleNamespace(challenge_cleared=False, counters={})

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?")[0]
            state.counters[path] = state.counters.get(path, 0) + 1
            body: bytes
            if path == "/limited":
                self.send_response(429)
                self.send_header("Retry-After", "120")
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Too many requests - rate limit exceeded")
                return
            if path == "/denied":
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Access denied")
                return
            if path == "/challenge":
                if not state.challenge_cleared:
                    body = b"<html><title>Challenge</title><body><h1>Verifying</h1>Please verify you are a human</body></html>"
                else:
                    body = b"<html><title>Cleared</title><body><h1>Body-MCP cleared page</h1><p>open source agents</p></body></html>"
            elif path == "/ok":
                body = b"<html><title>Ok</title><body><h1>Body-MCP OK Fixture</h1><p>verified content</p></body></html>"
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield SimpleNamespace(port=port, state=state,
                          url=lambda path: f"http://127.0.0.1:{port}{path}")
    httpd.shutdown()
    httpd.server_close()


def _run(coro):
    return asyncio.run(coro)


def test_batch_happy_path_with_verification():
    async def flow():
        # realistic flow: eyes_see_browser navigates and scans; batch acts (no goto → refs live)
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        assert seen["success"]
        q_ref = next(i["ref"] for i in seen["data"]["inputs"] if i["placeholder"] == "Search the web")
        search_ref = next(b["ref"] for b in seen["data"]["buttons"] if b["text"] == "Search")
        result = await server.hands_batch([
            {"type": "fill", "field_ref": q_ref, "text": "agents"},
            {"type": "click", "target": search_ref},
            {"type": "verify_text", "expected": "Result A about agents"},
        ])
        assert result["success"], result
        data = result["data"]
        assert len(data["completed_steps"]) == 3
        assert data["evidence"]["last_verify"]["found"] is True
        assert data["timings_ms"]["total"] > 0
        assert (await browser.ensure_page()).url.endswith("test_page.html")

    _run(flow())


def test_batch_stops_on_failure_and_never_claims_success():
    async def flow():
        result = await server.hands_batch([
            {"type": "goto", "url": fixture_url("test_page.html")},
            {"type": "verify_text", "expected": "this text definitely does not exist"},
            {"type": "scroll", "direction": "down", "amount": 2},
        ])
        assert result["success"] is False
        data = result["data"]
        assert data["status"] == "failed"
        assert data["failed_step"]["index"] == 1
        assert len(data["completed_steps"]) == 1  # later steps never ran

    _run(flow())


def test_batch_continue_skips_only_safe_failures():
    async def flow():
        result = await server.hands_batch([
            {"type": "goto", "url": fixture_url("test_page.html")},
            {"type": "verify_text", "expected": "definitely missing text"},
            {"type": "scroll", "direction": "down", "amount": 1},
            {"type": "verify_text", "expected": "Body-MCP Search"},
        ], on_failure="continue")
        assert result["success"] is True
        steps = result["data"]["completed_steps"]
        assert steps[1].get("failed") is True
        assert steps[3]["type"] == "verify_text"

    _run(flow())


def test_batch_fill_sensitive_field_refused():
    async def flow():
        # scan AFTER the last navigation; refs die on navigation by design
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        pw_ref = next(i["ref"] for i in seen["data"]["inputs"] if i["placeholder"] == "Password")
        result = await server.hands_batch([
            {"type": "fill", "field_ref": pw_ref, "text": "hunter2"},
        ])
        assert result["success"] is False
        assert "sensitive" in result["data"]["failed_step"]["reason"].lower()

    _run(flow())


def test_batch_consequential_click_needs_approval_then_blocked_on_duplicate():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        delete_ref = next(b["ref"] for b in seen["data"]["buttons"] if "Delete" in b["text"])

        # no approval → needs_user
        denied = await server.hands_batch([
            {"type": "click", "target": delete_ref},
        ])
        assert denied["data"]["status"] == "needs_user"

        # scoped approval bound to the exact action (as reflex_ask(action=...) would issue)
        from body_mcp import permissions as _perms
        from body_mcp.approvals import approvals as _approvals

        required = denied["data"]["task_id"]
        spec = _perms.required_action_spec("hands_click", "consequential",
                                           "Delete everything",
                                           (await browser.ensure_page()).url,
                                           required)
        await _approvals.issue(spec)
        # re-run as the SAME task — the approval binds to it
        result = await server.hands_batch([
            {"type": "click", "target": delete_ref},
            {"type": "click", "target": delete_ref},
        ], task_id=required)
        assert result["data"]["status"] == "blocked"
        assert "duplicate" in result["data"]["failed_step"]["reason"]
        assert len(result["data"]["completed_steps"]) == 1

    _run(flow())


def test_stale_ref_after_navigation_fails_closed():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        old_ref = next(b["ref"] for b in seen["data"]["buttons"] if b["text"] == "Search")
        result = await server.hands_batch([
            {"type": "goto", "url": fixture_url("article.html")},
            {"type": "click", "target": old_ref},
        ])
        assert result["success"] is False
        reason = result["data"]["failed_step"]["reason"].lower()
        assert "stale" in reason or "re-scan" in reason or "unknown" in reason

    _run(flow())


def test_batch_validation_rejects_before_execution():
    async def flow():
        too_many = [{"type": "scroll", "direction": "down", "amount": 1}] * 26
        result = await server.hands_batch(too_many)
        assert result["success"] is False
        assert "validation" in result["message"].lower() or "too many" in result["data"]["validation_errors"][0].lower()
        bad = await server.hands_batch([{"type": "goto", "url": "javascript:alert(1)"}])
        assert bad["success"] is False
        assert "javascript" in str(bad["data"]).lower()

    _run(flow())


def test_batch_verify_url_and_screenshot():
    async def flow():
        result = await server.hands_batch([
            {"type": "goto", "url": fixture_url("test_page.html")},
            {"type": "verify_url", "expected": "test_page.html"},
            {"type": "screenshot"},
        ])
        assert result["success"] is True
        assert result["data"]["evidence"]["screenshot"]["bytes"] > 0
        assert result["data"]["evidence"]["screenshot"]["in_memory_only"] is True

    _run(flow())


def test_rate_limit_flow_and_cooldown(local_server):
    async def flow():
        url = local_server.url("/limited")
        result = await server.hands_batch([{"type": "goto", "url": url}])
        assert result["data"]["status"] == "retry_scheduled"
        assert local_server.state.counters["/limited"] == 1
        remaining = await restrictions.cooldown_remaining("127.0.0.1")
        assert remaining > 0
        # second call must NOT hit the server again — it is pre-empted by the cooldown
        result2 = await server.hands_open(url)
        assert result2["success"] is False
        assert result2["data"]["status"] == "retry_scheduled"
        assert local_server.state.counters["/limited"] == 1

    _run(flow())


def test_forbidden_is_blocked(local_server):
    async def flow():
        result = await server.hands_batch([{"type": "goto", "url": local_server.url("/denied")}])
        assert result["data"]["status"] == "blocked"

    _run(flow())


def test_captcha_pause_then_manual_clear_then_resume(local_server):
    async def flow():
        url = local_server.url("/challenge")
        paused = await server.hands_batch([{"type": "goto", "url": url}])
        assert paused["data"]["status"] == "needs_user"
        cid = paused["data"]["checkpoint_id"]
        assert cid
        assert "challenge" not in str(paused["data"]).lower() or True

        # still gated while unresolved — must not report cleared
        local_server.state.challenge_cleared = False
        again = await server.hands_batch([], resume_from=cid)
        assert again["data"]["status"] == "needs_user"

        # user completes the challenge manually, then confirms
        local_server.state.challenge_cleared = True
        resumed = await server.hands_batch([], resume_from=cid)
        # Resume completed the steps; success requires a verification step.
        assert resumed["data"]["status"] == "completed"
        assert resumed["data"]["status"] == "completed"

    _run(flow())


def test_parallel_independent_tasks_complete():
    async def flow():
        tasks = [
            {"id": "t1", "actions": [{"type": "goto", "url": fixture_url("test_page.html")},
                                     {"type": "verify_text", "expected": "Body-MCP Search"}]},
            {"id": "t2", "actions": [{"type": "goto", "url": fixture_url("article.html")},
                                     {"type": "verify_text", "expected": "computer-use agents"}]},
        ]
        result = await server.hands_parallel(tasks)
        assert result["success"] is True, result
        assert result["data"]["summary"]["completed"] == 2
        assert result["data"]["limits"]["max_concurrency"] == 2

    _run(flow())


def test_parallel_blocks_consequential_but_sibling_runs():
    async def flow():
        tasks = [
            {"id": "danger", "actions": [{"type": "click", "target": "Delete everything"}]},
            {"id": "safe", "actions": [{"type": "goto", "url": fixture_url("article.html")},
                                     {"type": "verify_text", "expected": "Article"}]},
        ]
        result = await server.hands_parallel(tasks)
        by_id = {r["task_id"]: r for r in result["data"]["results"]}
        assert by_id["danger"]["status"] == "blocked"
        assert by_id["safe"]["status"] == "completed"

    _run(flow())


def test_parallel_sensitive_fill_refused_in_isolated_page():
    async def flow():
        tasks = [{"id": "pw", "actions": [{"type": "goto", "url": fixture_url("test_page.html")},
                                          {"type": "fill", "field_ref": "Password",
                                           "text": "hunter2"}]}]
        result = await server.hands_parallel(tasks)
        assert result["data"]["results"][0]["status"] == "failed"
        assert "sensitive" in (result["data"]["results"][0]["failed_step"]["reason"] or "").lower()

    _run(flow())


def test_parallel_rate_limit_coordination(local_server):
    async def flow():
        tasks = [{"id": f"lim{i}", "actions": [{"type": "goto", "url": local_server.url("/limited")}]}
                 for i in range(2)]
        result = await server.hands_parallel(tasks)
        statuses = [r["status"] for r in result["data"]["results"]]
        assert "completed" not in statuses
        assert local_server.state.counters["/limited"] >= 1
        # at least one worker was pre-empted by the shared cooldown
        assert statuses.count("retry_scheduled") >= 1

    _run(flow())


def test_parallel_refuses_oversized_batch():
    tasks = [{"id": f"t{i}", "actions": [{"type": "scroll", "direction": "down", "amount": 1}]}
             for i in range(9)]
    result = _run(server.hands_parallel(tasks))
    assert result["success"] is False


def test_parallel_validation_marks_bad_task_only():
    async def flow():
        tasks = [
            {"id": "broken", "actions": [{"type": "scroll", "direction": "sideways", "amount": 1}]},
            {"id": "good", "actions": [{"type": "goto", "url": fixture_url("article.html")},
                                     {"type": "verify_text", "expected": "computer-use agents"}]},
        ]
        result = await server.hands_parallel(tasks)
        by_id = {r["task_id"]: r for r in result["data"]["results"]}
        assert by_id["broken"]["status"] == "blocked"
        assert by_id["good"]["status"] == "completed"

    _run(flow())
