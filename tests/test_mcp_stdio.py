"""Layer C: real MCP integration over stdio.

Spawns the server as a SEPARATE PROCESS (exactly how an agent starts it), speaks
JSON-RPC on stdin/stdout and checks:
  - the handshake succeeds,
  - tool discovery returns the documented tools,
  - a tool call returns a structured result,
  - stdout carries ONLY protocol messages (no print/log noise),
  - the server shuts down cleanly when stdin closes.
"""
import contextlib
import json
import os
import subprocess
import sys
import time

PROTOCOL_VERSION = "2026-07-28"
PYTHON = sys.executable
SRC = os.path.join(os.path.dirname(__file__), "..", "src")


def _send(proc, message: dict) -> None:
    payload = json.dumps(message).encode("utf-8")
    proc.stdin.write(payload + b"\n")
    proc.stdin.flush()


def _read_message(proc, timeout: float = 30.0) -> dict:
    """Read one JSON-RPC message from stdout (skipping nothing: noise is a failure)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                raise AssertionError(f"server exited early (rc={proc.returncode})")
            continue
        text = line.decode("utf-8", errors="replace").strip()
        if not text:
            continue
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"non-protocol output on stdout: {text!r} ({exc})") from exc
    raise AssertionError("timed out waiting for a protocol message")


def test_stdio_handshake_tool_discovery_and_clean_shutdown():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.abspath(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["BODY_MCP_BROWSER_MODE"] = "headless"
    env["BODY_MCP_POLITE_DELAY_MS"] = "0"

    proc = subprocess.Popen([PYTHON, "-m", "body_mcp.server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=os.path.abspath(SRC))
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": PROTOCOL_VERSION,
                                "capabilities": {},
                                "clientInfo": {"name": "body-mcp-integration-test", "version": "1"}}})
        init = _read_message(proc)
        assert init["jsonrpc"] == "2.0"
        assert init["id"] == 1
        assert "result" in init, init
        assert init["result"]["serverInfo"]["name"] == "Body-MCP"

        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = _read_message(proc)
        names = {t["name"] for t in listed["result"]["tools"]}
        for expected in ("eyes_see_browser", "hands_click", "hands_batch", "attach_browser",
                         "detach_browser", "reflex_ask", "body_status", "body_events",
                         "memory_search", "research_collect"):
            assert expected in names, sorted(names)
        assert len(names) == 75, sorted(names)  # matches the documented tool set

        _send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "body_status", "arguments": {}}})
        called = _read_message(proc)
        assert called["id"] == 3
        assert "result" in called, called
        payload = json.dumps(called["result"])
        assert "Body-MCP" in payload
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            raise AssertionError("server did not exit when stdin closed")
        stderr = proc.stderr.read().decode("utf-8", errors="replace")
        assert "Traceback" not in stderr, stderr[-2000:]


def test_unknown_tool_returns_a_protocol_error_not_a_crash():
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.abspath(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    env["BODY_MCP_BROWSER_MODE"] = "headless"

    proc = subprocess.Popen([PYTHON, "-m", "body_mcp.server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=os.path.abspath(SRC))
    try:
        _send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                "clientInfo": {"name": "t", "version": "1"}}})
        _read_message(proc)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                     "params": {"name": "definitely_not_a_tool", "arguments": {}}})
        response = _read_message(proc)
        assert response.get("id") == 2
        assert "error" in response or response.get("result", {}).get("isError") is True, response
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
