"""Keep the body-dev server (and its visible browser) alive after opening YouTube.

Starts the server as a child process with a stdin pipe that is never closed, runs the
tool calls, and then holds the pipe open - so the Chromium window with YouTube stays on
the user's screen until they close it.

    python scripts/keep_bodydev_alive.py [--url https://www.youtube.com]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

CONFIG = os.path.join(os.path.expanduser("~"), ".config", "opencode", "opencode.jsonc")


def body_dev_command():
    import re

    with open(CONFIG, encoding="utf-8-sig") as handle:
        text = handle.read()
    without_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    without_strings = re.sub(r"//[^\n]*", "", without_strings)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", without_strings)
    strings = re.findall(r'"(?:\\.|[^"\\])*"', text)
    return json.loads(re.sub(r'""', lambda m: strings.pop(0) if strings else '""', cleaned))[
        "mcp"]["servers"]["body-dev"]["command"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://www.youtube.com")
    parser.add_argument("--minutes", type=int, default=120)
    args = parser.parse_args()

    command = body_dev_command()
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)

    def send(obj):
        proc.stdin.write(json.dumps(obj).encode() + b"\n")
        proc.stdin.flush()

    def read():
        return json.loads(proc.stdout.readline().decode("utf-8", "replace").strip())

    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                     "clientInfo": {"name": "keep-alive", "version": "1"}}})
    read()
    send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
          "params": {"name": "hands_open", "arguments": {"url": args.url}}})
    opened = json.loads(read()["result"]["content"][0]["text"])
    print("hands_open:", opened.get("message")[:120], flush=True)
    print("  url:", opened.get("data", {}).get("url"), flush=True)

    send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
          "params": {"name": "eyes_see_browser", "arguments": {}}})
    seen = json.loads(read()["result"]["content"][0]["text"])
    data = seen.get("data", {})
    print("  title:", data.get("title"), "| buttons:", len(data.get("buttons", [])),
          "| links:", len(data.get("links", [])), flush=True)
    print("  note:", seen.get("message")[:100], flush=True)

    print(f"keeping the server and its browser alive for {args.minutes} minutes "
          f"(pid {proc.pid}) - close the window or kill that process to stop it",
          flush=True)
    try:
        time.sleep(args.minutes * 60)
    except KeyboardInterrupt:
        pass
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()
        with contextlib.suppress(Exception):
            proc.terminate()
    return 0


if __name__ == "__main__":
    import contextlib

    sys.exit(main())
