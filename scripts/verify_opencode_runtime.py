"""Verify the EXACT OpenCode MCP configuration: real handshake + tool discovery.

Uses the command from ~/.config/opencode/opencode.jsonc (body-dev) verbatim.
"""
import json
import os
import subprocess
import sys
import time

CONFIG = os.path.join(os.path.expanduser("~"), ".config", "opencode", "opencode.jsonc")


def opencode_command():
    """Extract the body-dev command from the OpenCode config (jsonc -> json)."""
    with open(CONFIG, encoding="utf-8-sig") as handle:  # opencode may write a BOM
        text = handle.read()
    # strip // comments (outside strings) and trailing commas: opencode's config is JSONC
    import re

    without_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    without_strings = re.sub(r"//[^\n]*", "", without_strings)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", without_strings)
    # put the strings back
    strings = re.findall(r'"(?:\\.|[^"\\])*"', text)

    def restore(match):
        return strings.pop(0) if strings else '""'

    cleaned = re.sub(r'""', restore, cleaned)
    data = json.loads(cleaned)
    entry = data["mcp"]["servers"]["body-dev"]
    return entry["command"], entry.get("type")


def _payload(result):
    """MCP tool result -> the dict the tool returned."""
    if isinstance(result, dict):
        if "structuredContent" in result and result["structuredContent"]:
            return result["structuredContent"]
        for item in result.get("content", []) or []:
            if item.get("type") == "text":
                raw = item["text"]
                for _ in range(2):
                    if isinstance(raw, str):
                        try:
                            raw = json.loads(raw)
                            continue
                        except Exception:
                            return {"text": raw}
                    break
                return raw
    return result


def main() -> int:
    command, kind = opencode_command()
    print(f"opencode config : {CONFIG}")
    print(f"body-dev entry  : type={kind}")
    print(f"command         : {' '.join(command)}")

    env = dict(os.environ)
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)

    def send(obj):
        proc.stdin.write(json.dumps(obj).encode() + b"\n")
        proc.stdin.flush()

    def read():
        return json.loads(proc.stdout.readline().decode("utf-8", "replace").strip())

    try:
        t0 = time.perf_counter()
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                         "clientInfo": {"name": "opencode-config-check", "version": "1"}}})
        init = read()
        handshake_ms = (time.perf_counter() - t0) * 1000
        print(f"\ninitialize      : OK in {handshake_ms:.0f} ms")
        print(f"serverInfo      : {init['result']['serverInfo']}")

        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = read()
        tools = listed["result"]["tools"]
        print(f"tools discovered : {len(tools)}")

        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "body_status", "arguments": {}}})
        called = read()
        data = _payload(called["result"])
        print(f"body_status     : version={data['data']['version']}, "
              f"tools={data['data']['server']['tools_registered']}, "
              f"transport={data['data']['server']['transport']}")

        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
              "params": {"name": "body_profile", "arguments": {}}})
        profile = read()
        pdata = _payload(profile["result"])
        print(f"body_profile    : python={pdata['data']['python']} "
              f"cores={pdata['data']['cpu_cores']} "
              f"ram_free_mb={pdata['data']['ram_available_mb']}")
        print("\nRESULT: the configured OpenCode server starts, handshakes and serves tools.")
    finally:
        with contextlib_suppress():
            proc.stdin.close()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


class contextlib_suppress:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return exc_type is not None and issubclass(exc_type, OSError)


if __name__ == "__main__":
    sys.exit(main())
