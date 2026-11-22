"""Real MCP stdio smoke test: call EVERY tool with minimal arguments.

This is the guard that would have caught bugs #1 (research_youtube_search),
#2 (research_any) and #3 (reflex_ask with a dict action): those tools crashed
only when reached through the MCP layer, because unit tests call Python
functions directly.

We spawn the server as a separate process and speak raw JSON-RPC over stdio,
exactly like an agent does. A reader thread feeds a queue and EVERY call has a
hard timeout — a tool that never answers fails the test BY NAME instead of
hanging the whole suite.
"""
import json
import os
import queue
import subprocess
import sys
import threading

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PYTHON = sys.executable
CALL_TIMEOUT_S = 45.0

ARGS = {
    "body_local_worker": {"task": "summarise", "text": "hello"},
    "reflex_verify": {"expected": "nothing to verify"},
    "eyes_see_browser": {"url": "file:///" + os.path.join(
        ROOT, "tests", "fixtures", "test_page.html").replace("\\", "/")},
    "hands_open": {"url": "file:///" + os.path.join(
        ROOT, "tests", "fixtures", "test_page.html").replace("\\", "/")},
    "hands_click": {"target": "no-such-element"},
    "hands_type": {"field_ref": "no-such-field", "text": "x"},
    "hands_press": {"key": "Tab"},
    "hands_scroll": {"direction": "down"},
    "attach_browser": {"endpoint": "http://127.0.0.1:1"},
    "select_tab": {"tab_id": "none"},
    "browser_bridge": {"action": "status"},
    "body_open_external": {"url": "file:///" + os.path.join(
        ROOT, "tests", "fixtures", "test_page.html").replace("\\", "/")},
    "desktop_inspect": {"title": "NoSuchWindowAnywhere"},
    "desktop_click": {"title": "NoSuchWindowAnywhere", "control": "x"},
    "desktop_type": {"title": "NoSuchWindowAnywhere", "control": "x", "text": "y"},
    "desktop_read_value": {"title": "NoSuchWindowAnywhere", "control": "x"},
    "research_collect": {"urls": ["file:///" + os.path.join(
        ROOT, "tests", "fixtures", "article.html").replace("\\", "/")]},
    "research_source": {"source": "hackernews", "query": "test"},
    "research_any": {"query": "test"},
    "research_youtube_search": {"query": "test"},
    "research_sources": {},
    "legs_open_app": {"target": "notepad"},
    "memory_write": {"title": "stdio-smoke", "content": "smoke test"},
    "memory_search": {"query": "stdio-smoke"},
    "memory_delete": {"title": "stdio-smoke"},
    "body_workflow_start": {"title": "stdio-smoke"},
    "body_workflow_note": {"kind": "decision", "text": "smoke test"},
    "body_local_models": {"role": "worker"},
    "body_privacy_preflight": {},
    "privacy_vpn_connect": {},
    "body_console_start": {"port": 0},
    "body_console_stop": {},
    "body_task_start": {"label": "smoke", "command": "echo hi"},
    "body_task_status": {},
    "body_task_cancel": {},
    "body_cancel": {},
    "body_undo": {},
    "body_undo_list": {},
    "body_speak": {"text": ""},
    "body_stop_speaking": {},
    "body_voice_engines": {},
    "body_windows": {},
    "body_profile": {},
    "body_models": {},
    "body_recommend": {},
    "body_similarity_check": {"a": "x", "b": "y"},
    "body_roles": {},
    "body_role_start": {"role": "research"},
    "body_role_finish": {"role": "research"},
    "body_stop_all": {},
    "body_skill_save": {"name": "smoke", "text": "smoke"},
    "body_skill_list": {},
    "body_skill_replay": {"name": "smoke"},
    "body_lessons": {},
    "demo_learn": {"video_path": "no-such-video.mp4"},
    "eyes_see_desktop": {"as_image": False},
    "hands_batch": {"steps": []},
    "hands_parallel": {"tasks": []},
    "memory_export": {},
    "memory_list": {},
    "memory_note": {"filename": "smoke.md", "markdown": "smoke"},
    "privacy_session_start": {"label": "smoke"},
    "privacy_session_open": {"session_id": "none", "url": "file:///tmp/x"},
    "privacy_session_snapshot": {"session_id": "none"},
    "privacy_session_end": {"session_id": "none"},
}

# Tools whose minimal call legitimately waits for a HUMAN, a MIC, a real
# browser click, a live watcher thread or an external network video. Calling
# them here would make the guard hang; they are covered by their own tests.
SKIP = {
    "reflex_ask": "needs a human elicitation answer",
    "reflex_interview": "needs human elicitation answers",
    "ears_listen": "needs the microphone",
    "desktop_watch_start": "starts a live capture thread",
    "desktop_watch_read": "needs a live watch session",
    "desktop_watch_stop": "needs a live watch session",
    "research_video": "fetches a real video page (network)",
}


def _reader(stream, out: queue.Queue):
    try:
        for line in stream:
            out.put(line)
    finally:
        out.put(None)


def _rpc(proc, lines, msg_id, method, params=None, timeout=CALL_TIMEOUT_S):
    payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        payload["params"] = params
    proc.stdin.write(json.dumps(payload) + "\n")
    proc.stdin.flush()
    while True:
        try:
            line = lines.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"no MCP reply within {timeout:.0f}s")
        if line is None:
            raise AssertionError("server closed stdout")
        data = json.loads(line)
        if data.get("id") == msg_id:
            return data


def test_every_tool_callable_over_real_stdio():
    env = dict(os.environ)
    env["BODY_MCP_CONFIG_DIR"] = os.path.join(
        os.environ.get("TEMP", "/tmp"), "body_mcp_stdio_smoke")
    env["BODY_MCP_BROWSER_MODE"] = "headless"
    env["PYTHONIOENCODING"] = "utf-8"
    # CI has no human browser to connect: allow the managed Chromium in this
    # throwaway profile (real users keep own-browser-only = allow).
    from body_mcp import permissions as _perms

    _cfg = os.path.join(os.environ.get("TEMP", "/tmp"), "body_mcp_stdio_smoke")
    os.makedirs(_cfg, exist_ok=True)
    _prof = _perms.load_profile()
    _prof["capabilities"]["own_browser_only"] = "deny"
    with open(os.path.join(_cfg, "permissions.json"), "w", encoding="utf-8") as _f:
        json.dump(_prof, _f, indent=2)
    proc = subprocess.Popen(
        [PYTHON, "-m", "body_mcp.server"], cwd=ROOT, env=env,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1)
    lines: queue.Queue = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True).start()
    try:
        init = _rpc(proc, lines, 1, "initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "stdio-smoke", "version": "1"},
        })
        assert "result" in init, init
        proc.stdin.write(json.dumps({"jsonrpc": "2.0",
                                     "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()

        listed = _rpc(proc, lines, 2, "tools/list")
        names = [t["name"] for t in listed["result"]["tools"]]
        assert len(names) == 82, len(names)

        failures = []
        called = 0
        for i, name in enumerate(names, start=10):
            if name in SKIP:
                continue
            args = ARGS.get(name, {})
            try:
                reply = _rpc(proc, lines, i, "tools/call",
                             {"name": name, "arguments": args})
            except TimeoutError as exc:
                failures.append((name, str(exc)))
                break  # the stream is now out of sync; stop and report by name
            text = json.dumps(reply)
            if "error" in reply or "Exception" in text or "Traceback" in text:
                failures.append((name, text[:300]))
            called += 1
        # The one contract the tester flagged: a bad argument must still return
        # {success, message, data}, not raw pydantic text.
        bad = _rpc(proc, lines, 900, "tools/call",
                   {"name": "memory_search", "arguments": {"limit": "not-an-int"}})
        bad_text = bad.get("result", {}).get("content", [{}])[0].get("text", "")
        assert bad_text.strip().startswith("{"), bad_text
        parsed = json.loads(bad_text)
        assert parsed["success"] is False and parsed["data"]["validation"] is True, parsed

        assert not failures, f"tools that crashed or timed out over MCP:\n{failures}"
        assert called >= 71, f"only {called} tools were called"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
