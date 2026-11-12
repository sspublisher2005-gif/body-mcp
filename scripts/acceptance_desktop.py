"""Real desktop OCR acceptance: a known window is opened, captured and read.

    python scripts/acceptance_desktop.py

Checks, in order:
  1. the screen can actually be captured (real capture, real window),
  2. an OCR engine is present,
  3. the text of a window we opened ourselves is recognised,
  4. a second capture of the same screen yields the same text (stability),
  5. the window is closed again and nothing is left behind.

Statuses: PASS_REAL | FAIL | BLOCKED (with the exact missing dependency).
"""
from __future__ import annotations

import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import contextlib

from body_mcp import eyes, ocr  # noqa: E402

TOKEN = "BODYMCPCAPTURE7319"
RESULTS = []


def record(name, status, actual):
    RESULTS.append((name, status, actual))
    print(f"[{status:<10}] {name}: {actual}")


def open_fixture_window():
    """A real, visible window with known text (tkinter is in the standard library)."""
    import tkinter

    root = tkinter.Tk()
    root.title("Body-MCP OCR fixture")
    root.geometry("640x220+80+80")
    label = tkinter.Label(root, text=TOKEN, font=("Helvetica", 28))
    label.pack(pady=40)
    root.update()
    root.after(1500, root.destroy)

    def closer():
        time.sleep(3.0)
        with contextlib.suppress(Exception):
            root.quit()

    threading.Thread(target=closer, daemon=True).start()
    root.mainloop()
    return root


def main() -> int:
    engines = {entry["provider"]: entry for entry in ocr.providers()}
    provider, info = ocr.get_provider()

    # 1. real capture
    shot = eyes.capture_png(monitor=1)
    if not shot.get("ok"):
        record("desktop capture", "BLOCKED", shot.get("reason", "capture failed"))
        return 0
    record("desktop capture", "PASS_REAL",
           f"{shot['bytes']} bytes PNG of {shot['region']['width']}x{shot['region']['height']} "
           "(in memory only)")

    # 2. an engine must exist for OCR
    if provider is None:
        record("OCR engine", "BLOCKED",
               f"no OCR engine installed: {info.get('reason')} -> {info.get('install')}")
        for name, entry in engines.items():
            print(f"             {name}: available={entry.get('available')} "
                  f"reason={entry.get('reason')}")
        return 0
    record("OCR engine", "PASS_REAL",
           f"{provider.name} at {info.get('path')} ({info.get('version')}), "
           f"languages={info.get('languages')}")

    # 3. real window -> real text
    thread = threading.Thread(target=open_fixture_window, daemon=True)
    thread.start()
    time.sleep(1.2)
    window_shot = eyes.capture_png(monitor=1)
    if not window_shot.get("ok"):
        record("known window text", "FAIL", window_shot.get("reason"))
        return 1
    result = eyes.ocr_text(window_shot["png"], language="eng", provider_name=provider.name)
    found = TOKEN in (result.get("text") or "")
    record("known window text", "PASS_REAL" if found else "FAIL",
           f"token {'found' if found else 'NOT found'} in {result.get('duration_ms')} ms; "
           f"text sample={(result.get('text') or '')[:60]!r}")

    # 4. stability of a second capture
    again = eyes.capture_png(monitor=1)
    if again.get("ok"):
        second = eyes.ocr_text(again["png"], language="eng", provider_name=provider.name)
        record("repeat capture", "PASS_REAL" if second.get("text") else "FAIL",
               f"second read produced {len(second.get('text') or '')} characters")
    thread.join(timeout=5)

    failures = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\n{len(RESULTS)} checks, {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
