"""Open a URL in the USER'S OWN browser, through the real body-dev server.

    python scripts/open_in_my_browser.py https://www.youtube.com chrome

Calls body_open_external on the configured body-dev MCP server. With a browser name
(chrome | edge | brave | firefox) the URL opens in THAT browser - as a new tab in
the window you already have open. Without it, the OS default browser is used.
"""
import contextlib
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
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com"
    browser = sys.argv[2] if len(sys.argv) > 2 else ""
    command = body_dev_command()
    print("body-dev:", " ".join(command))
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)

    def send(obj):
        proc.stdin.write(json.dumps(obj).encode() + b"\n")
        proc.stdin.flush()

    def read():
        return json.loads(proc.stdout.readline().decode("utf-8", "replace").strip())

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                         "clientInfo": {"name": "open-in-my-browser", "version": "1"}}})
        read()
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "body_open_external",
                         "arguments": {"url": url, "browser": browser}}})
        payload = json.loads(read()["result"]["content"][0]["text"])
        print("body_open_external:", payload.get("message"))
        print("  data:", json.dumps(payload.get("data", {})))
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()

    time.sleep(3)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
    from body_mcp import windows

    for entry in windows.browser_windows().get("browsers", []):
        print("  visible browser window:", repr(entry["title"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
