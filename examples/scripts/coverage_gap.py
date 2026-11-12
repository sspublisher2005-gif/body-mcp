"""Close the last coverage gaps: the three tools the campaign did not call directly.

  LEG-01  legs_open_app with an app that is NOT in the allowlist  -> refused
  LEG-02  legs_open_app with a real allowlisted app (notepad)      -> launched, then closed
  LEG-03  legs_open_app with a shell injection in the name         -> refused
  ASK-01  reflex_ask with a human "no"                            -> no approval issued
  ASK-02  reflex_ask with a human "yes" + an action spec          -> one scoped approval issued
  TAB-01  list_tabs on an attached CDP session                    -> the real tabs are listed
"""
import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

RESULTS = []


def record(name, ok, actual):
    RESULTS.append({"test": name, "status": "PASS_REAL" if ok else "FAIL", "actual": actual})
    print(f"[{'PASS_REAL' if ok else 'FAIL':<10}] {name}: {actual}")


def main() -> int:
    cfg = tempfile.mkdtemp(prefix="body_coverage_cfg_")
    os.environ["BODY_MCP_CONFIG_DIR"] = cfg
    os.environ["BODY_MCP_BROWSER_MODE"] = "headless"
    os.environ["BODY_MCP_POLITE_DELAY_MS"] = "0"

    from body_mcp import permissions

    permissions.acknowledge_consent()

    # ---- legs_open_app ------------------------------------------------
    profile = os.path.join(cfg, "permissions.json")
    with open(profile, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "capabilities": {"app_launch": "allow"},
                   "allowed_applications": []}, f)

    from body_mcp import legs

    refused = asyncio.run(legs.open_app("notepad"))
    record("LEG-01", refused["success"] is False and "allowlist" in refused["message"].lower(),
           f"success={refused['success']}, message={refused['message'][:70]!r}")

    with open(profile, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "capabilities": {"app_launch": "allow"},
                   "allowed_applications": ["notepad"]}, f)

    launched = {"cmd": None}

    class FakeProc:
        def __init__(self, *a, **k):
            launched["cmd"] = a[0]

    original_popen = legs.subprocess.Popen
    legs.subprocess.Popen = FakeProc
    try:
        allowed = asyncio.run(legs.open_app("notepad"))
    finally:
        legs.subprocess.Popen = original_popen
    record("LEG-02", allowed["success"] is True and launched["cmd"][0] == "powershell",
           f"success={allowed['success']}, command={launched['cmd']}")

    injection = asyncio.run(legs.open_app("notepad' & calc"))
    record("LEG-03", injection["success"] is False,
           f"success={injection['success']}, message={injection['message'][:60]!r}")

    # a real launch (a harmless app) and closing it again
    with open(profile, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "capabilities": {"app_launch": "allow"},
                   "allowed_applications": ["notepad"]}, f)
    before = _notepad_pids()
    real = asyncio.run(legs.open_app("notepad"))
    time.sleep(2)
    after = _notepad_pids()
    started = [p for p in after if p not in before]
    record("LEG-04", real["success"] is True and bool(started),
           f"launch_success={real['success']}, new_notepad_pids={started}")
    for pid in started:
        with contextlib.suppress(Exception):
            subprocess.run(["taskkill", "/PID", str(pid), "/T"], capture_output=True, timeout=20)

    # ---- reflex_ask --------------------------------------------------
    from body_mcp import reflex
    from body_mcp.approvals import approvals

    async def denied():
        await approvals.clear()
        original = reflex._ask_via_messagebox
        reflex._ask_via_messagebox = lambda question: False
        try:
            result = await reflex.ask("Allow?", None, action=json.dumps(
                {"tool": "hands_click", "capability": "consequential", "target": "Delete"}))
            spec = {"tool": "hands_click", "capability": "consequential", "target": "Delete"}
            peeked = await approvals.peek(spec)
            return result, peeked
        finally:
            reflex._ask_via_messagebox = original
            await approvals.clear()

    result, peeked = asyncio.run(denied())
    record("ASK-01", result["approved"] is False and peeked is False,
           f"approved={result['approved']}, approval_issued={peeked}")

    async def approved():
        await approvals.clear()
        original = reflex._ask_via_messagebox
        reflex._ask_via_messagebox = lambda question: True
        try:
            spec = {"tool": "hands_click", "capability": "consequential", "target": "Delete",
                    "url": None, "task_id": None}
            result = await reflex.ask("Allow?", None, action=json.dumps(spec))
            peeked = await approvals.peek(spec)
            return result, peeked
        finally:
            reflex._ask_via_messagebox = original
            await approvals.clear()

    result, peeked = asyncio.run(approved())
    record("ASK-02", result["approved"] is True and peeked is True
           and result["data"]["scoped_approval"] is True,
           f"approved={result['approved']}, scoped_approval={result['data']['scoped_approval']}, "
           f"issued={peeked}")

    # ---- list_tabs ----------------------------------------------------
    from body_mcp import attach, server

    exe = None
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"):
        if os.path.isfile(path):
            exe = path
            break
    if exe is None:
        record("TAB-01", False, "no Chrome executable found")
    else:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        profile_dir = tempfile.mkdtemp(prefix="body_coverage_profile_")
        fixture = "file:///" + os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures",
                         "test_page.html")).replace("\\", "/")
        proc = subprocess.Popen([exe, f"--remote-debugging-port={port}",
                                 f"--user-data-dir={profile_dir}", "--headless=new",
                                 "--no-first-run", "--no-default-browser-check", "--disable-gpu",
                                 fixture],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        endpoint = f"http://127.0.0.1:{port}"
        for _ in range(60):
            try:
                with urllib.request.urlopen(endpoint + "/json/version", timeout=1) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.25)
        try:
            async def flow():
                await approvals.clear()
                await approvals.issue(permissions.required_action_spec(
                    "attach_browser", "chrome_attach", f"cdp:{endpoint}", None, None))
                await attach.attach(endpoint)
                tabs = await server.list_tabs()
                await attach.detach()
                return tabs

            tabs = asyncio.run(flow())
            listed = tabs["data"].get("tabs", [])
            record("TAB-01", tabs["success"] is True and len(listed) >= 1,
                   f"tabs_listed={len(listed)}, first={listed[0]['title'] if listed else '-'!r}")
        finally:
            with contextlib.suppress(Exception):
                proc.terminate()
                proc.wait(timeout=10)

    failures = [r for r in RESULTS if r["status"] == "FAIL"]
    print(f"\n{len(RESULTS)} executions, {len(failures)} failure(s)")
    return 1 if failures else 0


def _notepad_pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq notepad.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, timeout=20)
    pids = []
    for line in (out.stdout or "").splitlines():
        parts = [p.strip('" ') for p in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


if __name__ == "__main__":
    sys.exit(main())
