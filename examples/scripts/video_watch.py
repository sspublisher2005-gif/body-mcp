"""PHASE B - act on a decision, then verify, watch and hear.

The brain (the agent) decides WHICH video; this script executes the decision and
brings back the evidence:
  1. open the channel's "Latest" tab (a stable public URL: ?view=0&sort=dd),
  2. eyes: observe the ordered results (title + how long ago),
  3. hands: click the newest video,
  4. verify: reflex_verify the title, and read the page (channel, views, date),
  5. hear: open the video's own transcript (official captions - no model download),
  6. watch: capture a frame of the playing video (vision mode),
  7. print everything for the report.
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
CHANNEL = sys.argv[1] if len(sys.argv) > 1 else "@marc-lou"
LATEST_URL = f"https://www.youtube.com/{CHANNEL}/videos?view=0&sort=dd"


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
                               "clientInfo": {"name": "video-watch", "version": "1"}}})
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


def find_ref(items, needle: str, exact: bool = True) -> str | None:
    for item in items:
        text = (item.get("text") or "").strip().lower()
        if (text == needle) if exact else (needle in text):
            return item.get("ref")
    return None


def main() -> int:
    client = Client()
    try:
        print("### 1. open the channel's Latest tab:", LATEST_URL)
        client.call("hands_open", {"url": LATEST_URL})
        time.sleep(7)

        print("### 2. eyes: the ordered channel videos")
        page = client.call("eyes_see_browser", {}).get("data", {})
        print("   url:", page.get("url"), "| title:", page.get("title"))
        print("   channel line:", [line for line in (page.get("text") or "").splitlines()
                                  if "subscribers" in line.lower()][:2])
        cards = []
        for link in page.get("links", []):
            href = link.get("href") or ""
            text = (link.get("text") or "").strip()
            if "/watch" in href and text and "watch?v" in href and not any(
                    href == existing for existing, _t, _r in cards):
                cards.append((href, text, link.get("ref")))
        print("   videos in order:")
        for index, (href, text, _ref) in enumerate(cards[:12]):
            print(f"      [{index}] {text[:70]!r} -> {href[:60]}")

        if not cards:
            print("   !! no video links; page text:", (page.get("text") or "")[:500])
            return 1

        href, title, ref = cards[0]
        print(f"\n### 3. hands: open the newest video -> {title[:60]!r}")
        client.call("hands_click", {"target": ref})
        time.sleep(8)

        print("### 4. verify: what is actually on screen")
        watch = client.call("eyes_see_browser", {}).get("data", {})
        print("   url:", watch.get("url"))
        print("   title:", watch.get("title"))
        verified = client.call("reflex_verify", {"expected": title.split("\n")[0][:40]})
        print("   reflex_verify:", verified.get("found"),
              "|", (verified.get("data", {}).get("evidence") or "")[:120])
        meta = [b.get("text") for b in watch.get("buttons", []) if b.get("text")]
        for m in meta:
            if "view" in m.lower() or " ago" in m.lower() or "subscriber" in m.lower():
                print("   meta:", m[:160])
        print("   headings:", [h.get("text") for h in watch.get("headings", []) if h.get("text")][:12])

        print("### 5. hear: the video's own captions")
        more = find_ref(watch.get("buttons", []), "more", exact=False)
        if more:
            client.call("hands_click", {"target": more})
            time.sleep(2)
            watch = client.call("eyes_see_browser", {}).get("data", {})
        transcript = find_ref(watch.get("buttons", []), "transcript", exact=False)
        if transcript:
            client.call("hands_click", {"target": transcript})
            time.sleep(5)
            panel = client.call("eyes_see_browser", {}).get("data", {})
            lines = [line.strip() for line in (panel.get("text") or "").splitlines() if line.strip()]
            print("   transcript lines:", len(lines))
            for line in lines[:160]:
                print("     ", line[:170])
        else:
            print("   no transcript control reachable - the captions are not exposed in the DOM")
            print("   description/first text:")
            for line in (watch.get("text") or "").splitlines()[:40]:
                if line.strip():
                    print("     ", line[:160])

        print("### 6. watch: a frame of the playing video")
        client.call("eyes_see_browser", {"screenshot": True})
        print("   image captured (vision mode) - the model sees the frame")
        print("   note: the browser window stays open until the server exits")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
