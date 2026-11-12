"""Open YouTube with the REAL body-dev server (the one OpenCode runs).

Speaks MCP to `D:\\Projects\\body parts of agents\\.venv\\Scripts\\python.exe -m body_mcp.server`
exactly as configured in ~/.config/opencode/opencode.jsonc, then calls the tools an agent
would call.
"""
import contextlib
import json
import os
import subprocess
import sys

CONFIG = os.path.join(os.path.expanduser("~"), ".config", "opencode", "opencode.jsonc")


def body_dev_command():
    import re

    with open(CONFIG, encoding="utf-8-sig") as handle:
        text = handle.read()
    without_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    without_strings = re.sub(r"//[^\n]*", "", without_strings)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", without_strings)
    strings = re.findall(r'"(?:\\.|[^"\\])*"', text)
    data = json.loads(re.sub(r'""', lambda m: strings.pop(0) if strings else '""', cleaned))
    return data["mcp"]["servers"]["body-dev"]["command"]


def send(proc, obj):
    proc.stdin.write(json.dumps(obj).encode() + b"\n")
    proc.stdin.flush()


def read(proc):
    line = proc.stdout.readline().decode("utf-8", "replace").strip()
    return json.loads(line)


def main() -> int:
    command = body_dev_command()
    print("body-dev command:", " ".join(command))
    env = dict(os.environ)
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    try:
        send(proc, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                               "clientInfo": {"name": "open-youtube", "version": "1"}}})
        init = read(proc)
        print("handshake:", init["result"]["serverInfo"]["name"])
        send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "hands_open",
                               "arguments": {"url": "https://www.youtube.com"}}})
        opened = read(proc)
        text = opened["result"]["content"][0]["text"]
        payload = json.loads(text)
        print("hands_open:", payload.get("message"))
        print("  url:", payload.get("data", {}).get("url"))
        print("  title:", payload.get("data", {}).get("title"))
        print("  http_status:", payload.get("data", {}).get("http_status"))

        send(proc, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "eyes_see_browser", "arguments": {}}})
        seen = read(proc)
        payload = json.loads(seen["result"]["content"][0]["text"])
        data = payload.get("data", {})
        print("eyes_see_browser:", payload.get("message"))
        print("  url:", data.get("url"))
        print("  title:", data.get("title"))
        print("  headings:", data.get("headings"))
        print("  buttons seen:", len(data.get("buttons", [])), "| links:", len(data.get("links", [])))
        print("  first text:", (data.get("text") or "")[:220].replace("\n", " "))
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
