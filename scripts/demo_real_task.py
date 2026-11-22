"""ONE REAL TASK, end to end, on a local fixture page. No network, no installs.

    python scripts/demo_real_task.py

EYES   inspect the page (title, links, refs)
BRAIN  choose the next single action (recorded in the output)
HANDS  click the "Read the full article" link
VERIFY prove the postcondition: the article page is actually showing
REPORT print the evidence chain

The fixture is served over a local file:// URL - no external site is contacted.
The permission profile is a throwaway temp dir: your real profile is untouched.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

# A disposable profile: the demo must never touch the user's memory or audit log.
_TMP = os.path.join(ROOT, "reports", "validation", "_demo_profile")
os.makedirs(_TMP, exist_ok=True)
os.environ["BODY_MCP_CONFIG_DIR"] = _TMP
os.environ.setdefault("BODY_MCP_BROWSER_MODE", "headless")
os.environ.setdefault("BODY_MCP_POLITE_DELAY_MS", "0")

from body_mcp import permissions, server  # noqa: E402

# The demo is a reproducible fixture test: it uses Body-MCP's own headless
# Chromium, not a human's browser. Opt this throwaway profile into that mode;
# real users keep the default (own-browser-only) and are never given a test
# browser.
_demo_profile = permissions.load_profile()
_demo_profile["capabilities"]["own_browser_only"] = "deny"
with open(os.path.join(_TMP, "permissions.json"), "w", encoding="utf-8") as _f:
    import json as _json

    _json.dump(_demo_profile, _f, indent=2)


def fixture(name: str) -> str:
    return "file:///" + os.path.join(ROOT, "tests", "fixtures", name).replace("\\", "/")


async def main() -> int:
    permissions.acknowledge_consent()
    steps = []

    # EYES — see the page before acting.
    seen = await server.eyes_see_browser(url=fixture("test_page.html"))
    assert seen["success"], seen
    links = [item.get("text", "") for item in seen["data"].get("links", [])]
    assert any("Read the full article" in text for text in links), links
    steps.append({"step": "EYES", "status": "CONFIRMED",
                  "evidence": f"title={seen['data']['title']!r}, "
                              f"links={links[:4]}, refs issued"})
    print(f"[EYES]   {steps[-1]['evidence']}")

    # BRAIN — write the decision down before the action.
    decision = "the article link is the only permitted navigation on this page"
    steps.append({"step": "BRAIN", "status": "DECIDED", "evidence": decision})
    print(f"[BRAIN]  {decision}")

    # HANDS — one validated action (a normal link, not a dangerous button).
    clicked = await server.hands_click("Read the full article")
    assert clicked["success"], clicked
    steps.append({"step": "HANDS", "status": clicked["data"].get("verification", {}).get(
        "status", "UNCONFIRMED"),
        "evidence": f"message={clicked['message']!r}, title={clicked['data'].get('title')!r}"})
    print(f"[HANDS]  {steps[-1]['evidence']}  (state: {steps[-1]['status']})")

    # VERIFY — prove what is actually on screen now.
    verified = await server.reflex_verify("Body-MCP Article")
    assert verified["success"] and verified.get("found"), verified
    steps.append({"step": "VERIFY", "status": "CONFIRMED",
                  "evidence": f"found={verified['found']}, source={verified['data']['source']}, "
                              f"evidence={verified['data']['evidence']!r}"})
    print(f"[VERIFY] {steps[-1]['evidence']}")

    await server.browser.shutdown_browser()
    report = {"task": "inspect a page, click a permitted link, verify the result",
              "fixture": fixture("test_page.html"), "steps": steps,
              "verdict": "CONFIRMED" if steps[-1]["status"] == "CONFIRMED" else "UNCONFIRMED",
              "note": "no external network; throwaway profile; no installs"}
    out = os.path.join(ROOT, "reports", "validation", "real-task-proof.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    print(f"\nRESULT: {report['verdict']}  | evidence: {out}")
    return 0 if report["verdict"] == "CONFIRMED" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
