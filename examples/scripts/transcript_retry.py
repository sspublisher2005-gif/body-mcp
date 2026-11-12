"""Retry: does the in-page transcript panel expose the caption lines?

Clicks "more" -> "Show transcript", waits, scrolls the panel into view and reads
the page text again - looking for timestamped caption sentences.
"""
from __future__ import annotations

import asyncio
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from body_mcp import server  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=RveQCVgxyjs"


async def main() -> int:
    await server.hands_open({"url": URL})
    await asyncio.sleep(6)
    page = await server.eyes_see_browser({})
    data = page.get("data", {})
    print("title:", data.get("title"))

    def find(items, needle, exact=False):
        for item in items:
            text = (item.get("text") or "").strip().lower()
            if (text == needle) if exact else (needle in text):
                return item.get("ref")
        return None

    more = find(data.get("buttons", []), "more")
    if more:
        await server.hands_click({"target": more})
        await asyncio.sleep(3)
        data = (await server.eyes_see_browser({})).get("data", {})
    transcript = find(data.get("buttons", []), "transcript")
    print("transcript control:", transcript)
    if transcript:
        await server.hands_click({"target": transcript})
        for wait in (5, 8, 12):
            await asyncio.sleep(wait)
            data = (await server.eyes_see_browser({})).get("data", {})
            text = data.get("text", "")
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            stamps = [line for line in lines if re.match(r"^\d{1,2}:\d{2}\s+\S", line)]
            print(f"  after {wait}s: {len(lines)} text lines, {len(stamps)} timestamped lines")
            if len(stamps) > 2:
                for line in stamps[:40]:
                    print("    ", line[:160])
                return 0
        print("  no caption lines in the DOM; last 40 lines of the page:")
        for line in lines[-40:]:
            print("    ", line[:150])
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
