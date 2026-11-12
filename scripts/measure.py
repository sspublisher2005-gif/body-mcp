"""Measure real startup, latency and payload sizes (no mocks)."""
import json
import os
import subprocess
import sys
import time

src = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
env = dict(os.environ)
env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
env["BODY_MCP_BROWSER_MODE"] = "headless"

t0 = time.perf_counter()
proc = subprocess.Popen([sys.executable, "-m", "body_mcp.server"], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=src)
proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                                        "clientInfo": {"name": "measure", "version": "1"}}}).encode() + b"\n")
proc.stdin.flush()
proc.stdout.readline()
handshake_ms = (time.perf_counter() - t0) * 1000

proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized",
                             "params": {}}).encode() + b"\n")
proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                             "params": {}}).encode() + b"\n")
proc.stdin.flush()
listed = json.loads(proc.stdout.readline())
tools_ms = (time.perf_counter() - t0) * 1000

proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "body_status", "arguments": {}}}).encode() + b"\n")
proc.stdin.flush()
called = json.loads(proc.stdout.readline())
call_ms = (time.perf_counter() - t0) * 1000
proc.stdin.close()
proc.wait(timeout=15)

tools = listed["result"]["tools"]
print(f"startup + initialize handshake : {handshake_ms:.0f} ms")
print(f"+ tools/list                    : {tools_ms:.0f} ms")
print(f"+ body_status call              : {call_ms:.0f} ms")
print(f"tool count                      : {len(tools)}")
print(f"tool schema bytes (all tools)   : {len(json.dumps(tools))}")
print(f"body_status payload bytes       : {len(json.dumps(called['result']))}")
print(f"mean bytes per tool schema      : {len(json.dumps(tools)) // max(1, len(tools))}")
