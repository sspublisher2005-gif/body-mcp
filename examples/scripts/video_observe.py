"""PHASE A - eyes only: observe the search results and print them for the brain.

No clicking on results, no guessing. The output is what the agent (the brain) reads
before deciding which video to open.

    python scripts/video_observe.py "marco lou"
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CONFIG = os.path.join(os.path.expanduser("~"), ".config", "opencode", "opencode.jsonc")
QUERY = sys.argv[1] if len(sys.argv) > 1 else "marco lou"


def body_dev_command():
    with open(CONFIG, encoding="utf-8-sig") as handle:
        text = handle.read()
    without_strings = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    without_strings = re.sub(r"//[^\n]*", "", without_strings)
    cleaned = re.sub(r",(\s*[}\]])", r"\1", without_strings)
    strings = re.findall(r'"(?:\\.|[^"\\])*"', text)
    return json.loads(re.sub(r'""', lambda m: strings.pop(0) if strings else '""', cleaned))[
        "mcp"]["servers"]["body-dev"]["command"]


class Client:
    def __init__(self):
        self.proc = subprocess.Popen(body_dev_command(), stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.counter = 0
        self._send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                               "clientInfo": {"name": "video-observe", "version": "1"}}})
        self._read()
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def _send(self, obj):
        self.proc.stdin.write(json.dumps(obj).encode() + b"\n")
        self.proc.stdin.flush()

    def _read(self):
        return json.loads(self.proc.stdout.readline().decode("utf-8", "replace").strip())

    def call(self, name: str, arguments: dict) -> dict:
        self.counter += 1
        self._send({"jsonrpc": "2.0", "id": self.counter, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
        result = self._read()["result"]
        for block in result.get("content", []):
            if block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except Exception:
                    return {"text": block["text"]}
        return {}

    def close(self):
        with contextlib.suppress(Exception):
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def main() -> int:
    client = Client()
    try:
        print("### 1. open YouTube")
        client.call("hands_open", {"url": "https://www.youtube.com"})
        time.sleep(2)

        print("### 2. eyes: the search box")
        seen = client.call("eyes_see_browser", {}).get("data", {})
        search_ref = None
        for item in seen.get("inputs", []):
            blob = ((item.get("placeholder") or "") + " " + (item.get("name") or "")).lower()
            if "search" in blob or "query" in blob:
                search_ref = item.get("ref")
                break
        if not search_ref:
            print("no search field:", json.dumps(seen.get("inputs", []))[:300])
            return 1
        client.call("hands_type", {"field_ref": search_ref, "text": QUERY})
        client.call("hands_press", {"key": "Enter"})
        time.sleep(6)

        print("### 3. eyes: the results page (default order)")
        results = client.call("eyes_see_browser", {}).get("data", {})
        print("url:", results.get("url"), "| title:", results.get("title"))
        chips = [(b.get("ref"), b.get("text")) for b in results.get("buttons", []) if b.get("text")]
        links = [(entry.get("ref"), entry.get("text"), entry.get("href"))
                 for entry in results.get("links", [])]
        print("\n-- filter chips (buttons) --")
        for ref, text in chips[:30]:
            print(f"   {ref:<14} {text[:60]!r}")
        print("\n-- filter chips (links) --")
        for ref, text, href in links[:30]:
            print(f"   {ref:<14} {text[:50]!r} -> {(href or '')[:60]}")

        latest = None
        for ref, text in chips:
            if text.strip().lower() == "latest":
                latest = ref
                break
        if latest is None:
            for ref, text, href in links:
                if text.strip().lower() == "latest":
                    latest = ref
                    break
        if latest:
            print(f"\n### 4. clicking the 'Latest' filter ({latest})")
            client.call("hands_click", {"target": latest})
            time.sleep(6)
            results = client.call("eyes_see_browser", {}).get("data", {})
            print("url:", results.get("url"), "| title:", results.get("title"))
        else:
            print("\n### 4. no 'Latest' chip found - staying with the default order")

        print("\n### 5. THE OBSERVATION (this is what the brain reads)")
        print("-- every link with its ref --")
        for index, (ref, text, href) in enumerate(results.get("links", [])):
            print(f"   [{index:>3}] {ref:<14} {text[:58]!r} -> {(href or '')[:70]}")
        print("\n-- visible page text (the card details: channel, views, age) --")
        for line in (results.get("text") or "").splitlines():
            if line.strip():
                print("   ", line[:150])
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
