"""Body-MCP QA campaign — executes every scenario and writes the test matrix.

    python scripts/campaign.py                 # 1 run per scenario, writes reports/qa-campaign
    python scripts/campaign.py --runs 3        # repeat the deterministic scenarios 3x

Every scenario really executes against the real component (real Chromium, real
Chrome over CDP, real SQLite, the real speech engine, a real subprocess MCP
server). The recorded status is derived from an explicit check, never asserted by
hand:

    PASS_REAL | PASS_LOCAL_INTEGRATION | PASS_MOCK_ONLY | FAIL | BLOCKED | NOT_RUN
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

PASS_REAL = "PASS_REAL"
PASS_LOCAL = "PASS_LOCAL_INTEGRATION"
PASS_MOCK = "PASS_MOCK_ONLY"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_RUN = "NOT_RUN"

TEST_TYPE = {PASS_REAL: "real", PASS_LOCAL: "local_integration", PASS_MOCK: "mock_only",
             FAIL: "real", BLOCKED: "real", NOT_RUN: "real"}

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
ROWS: list[dict] = []


def fixture(name: str) -> str:
    return "file:///" + os.path.abspath(os.path.join(FIXTURES, name)).replace("\\", "/")


def record(test_id, feature, scenario, run, status, command, expected, actual,
           evidence="", duration="", issue_id=""):
    ROWS.append({
        "test_id": test_id, "feature": feature, "scenario": scenario,
        "run_number": run, "test_type": TEST_TYPE.get(status, "real"), "status": status,
        "command": command, "expected_result": expected, "actual_result": actual,
        "evidence": evidence, "duration": duration, "issue_id": issue_id,
    })


def check(test_id, feature, scenario, run, ok, command, expected, actual,
          evidence="", duration="", issue_id="", status=None):
    record(test_id, feature, scenario, run, status or (PASS_REAL if ok else FAIL),
           command, expected, actual, evidence, duration, issue_id)


class Ctx:
    """One event loop for the whole campaign (like the MCP server's own loop)."""

    def __init__(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.config_dir = tempfile.mkdtemp(prefix="body_campaign_cfg_")
        os.environ["BODY_MCP_CONFIG_DIR"] = self.config_dir
        os.environ["BODY_MCP_BROWSER_MODE"] = "headless"
        os.environ["BODY_MCP_POLITE_DELAY_MS"] = "0"
        from body_mcp import permissions

        permissions.acknowledge_consent()

    def run(self, coro):
        return self.loop.run_until_complete(coro)

    def close(self):
        with contextlib.suppress(Exception):
            from body_mcp import browser

            self.loop.run_until_complete(browser.shutdown_browser())
        with contextlib.suppress(Exception):
            self.loop.close()


# ---------------------------------------------------------------- MCP protocol
def scenario_mcp(ctx, run):
    env = dict(os.environ)
    env["PYTHONPATH"] = os.path.join(REPO, "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["BODY_MCP_BROWSER_MODE"] = "headless"
    t0 = time.perf_counter()
    proc = subprocess.Popen([sys.executable, "-m", "body_mcp.server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                            cwd=os.path.join(REPO, "src"))
    lines = []

    def send(obj):
        proc.stdin.write(json.dumps(obj).encode() + b"\n")
        proc.stdin.flush()

    def read():
        line = proc.stdout.readline().decode("utf-8", "replace").strip()
        lines.append(line)
        return json.loads(line)

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                         "clientInfo": {"name": "campaign", "version": "1"}}})
        init = read()
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = read()["result"]["tools"]
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "body_status", "arguments": {}}})
        called = read()
        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
              "params": {"name": "definitely_not_a_tool", "arguments": {}}})
        unknown = read()
        send({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
              "params": {"name": "hands_click", "arguments": {"target": 12345}}})
        bad_args = read()
    finally:
        with contextlib.suppress(Exception):
            proc.stdin.close()
        with contextlib.suppress(Exception):
            proc.wait(timeout=15)
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"

    name = init["result"]["serverInfo"]["name"]
    check("MCP-01", "MCP protocol", "initialize handshake over stdio", run,
          name == "Body-MCP", "python -m body_mcp.server (subprocess)",
          "serverInfo.name == 'Body-MCP'", f"name={name}",
          f"protocolVersion={init['result'].get('protocolVersion')}", dt)
    check("MCP-02", "MCP protocol", "tool discovery", run,
          len(tools) > 0 and all(t.get("description") for t in tools), "tools/list",
          "every tool has a name and a description",
          f"{len(tools)} tools, all described: {all(t.get('description') for t in tools)}",
          f"first tool: {tools[0]['name']}", dt)
    schema_ok = all("inputSchema" in t for t in tools)
    check("MCP-03", "MCP protocol", "every advertised tool has an input schema", run,
          schema_ok, "tools/list", "inputSchema present for all tools",
          f"schema_ok={schema_ok}", "", dt)
    clean = all(line.startswith("{") for line in lines if line)
    check("MCP-04", "MCP protocol", "stdout carries only protocol messages", run,
          clean, "read stdout of the server process", "no banner or debug output",
          f"non_json_lines={sum(1 for line in lines if line and not line.startswith('{'))}",
          "", dt)
    payload = json.dumps(called["result"])
    check("MCP-05", "MCP protocol", "body_status tool call over the protocol", run,
          len(payload) > 0 and "Body-MCP" in payload, "tools/call body_status",
          "structured capability result", f"payload_bytes={len(payload)}", "", dt)
    is_error = ("error" in unknown) or unknown.get("result", {}).get("isError") is True
    check("MCP-06", "MCP protocol", "unknown tool returns a protocol error", run,
          is_error, "tools/call definitely_not_a_tool", "error, no crash",
          f"is_error={is_error}", "", dt)
    arg_error = ("error" in bad_args) or bad_args.get("result", {}).get("isError") is True
    check("MCP-07", "MCP protocol", "wrong argument type is rejected", run,
          arg_error, "tools/call hands_click {target: 12345}",
          "structured error, no traceback on stdout", f"is_error={arg_error}", "", dt)


# ---------------------------------------------------------------- browser/eyes
def scenario_browser(ctx, run):
    from body_mcp import browser, server

    async def see():
        return await server.eyes_see_browser(fixture("test_page.html"))

    t0 = time.perf_counter()
    seen = ctx.run(see())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    title_ok = seen["data"]["title"] == "Body-MCP Test Page"
    structure = (len(seen["data"]["links"]) >= 1 and len(seen["data"]["buttons"]) >= 2
                 and len(seen["data"]["inputs"]) >= 3)
    check("BRW-01", "Eyes", "read a local fixture page", run,
          title_ok and structure, "eyes_see_browser(file://fixture)",
          "title, links, buttons, inputs and refs",
          f"title={seen['data']['title']!r}, links={len(seen['data']['links'])}, "
          f"buttons={len(seen['data']['buttons'])}, inputs={len(seen['data']['inputs'])}",
          f"ref sample: {seen['data']['buttons'][0].get('ref')}", dt)

    async def click_flow():
        seen = await server.eyes_see_browser(fixture("test_page.html"))
        save_ref = next(b["ref"] for b in seen["data"]["buttons"] if b["text"] == "Save")
        clicked = await server.hands_click(save_ref)
        verified = await server.reflex_verify("Saved")
        return clicked, verified

    t0 = time.perf_counter()
    clicked, verified = ctx.run(click_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("BRW-02", "Hands", "click a safe button and verify the page state", run,
          clicked["success"] and verified["found"],
          "hands_click(Save) + reflex_verify('Saved')",
          "the click runs and the page shows 'Saved'",
          f"clicked={clicked['success']}, verified={verified['found']}",
          f"click verification={clicked['data']['verification']['status']}", dt)

    async def ambiguous_flow():
        await server.eyes_see_browser(fixture("ambiguous_page.html"))
        return await server.hands_click("Continue")

    t0 = time.perf_counter()
    ambiguous = ctx.run(ambiguous_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("BRW-03", "Hands", "an ambiguous target is refused, not guessed", run,
          ambiguous["success"] is False and "ambiguous" in ambiguous["message"].lower(),
          "hands_click('Continue') on a page with two matching buttons",
          "a refusal that names the ambiguity",
          f"success={ambiguous['success']}, message={ambiguous['message'][:70]!r}", "", dt)

    async def sensitive_flow():
        seen = await server.eyes_see_browser(fixture("test_page.html"))
        pw_ref = next(i["ref"] for i in seen["data"]["inputs"]
                      if i.get("placeholder") == "Password")
        return await server.hands_type(pw_ref, "hunter2")

    t0 = time.perf_counter()
    sensitive = ctx.run(sensitive_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("SEC-01", "Security", "typing into a password field is refused", run,
          sensitive["success"] is False and sensitive["data"].get("sensitive") is True,
          "hands_type(password_ref, 'hunter2')", "refusal, nothing typed",
          f"success={sensitive['success']}, sensitive={sensitive['data'].get('sensitive')}",
          "", dt)

    async def stale_flow():
        seen = await server.eyes_see_browser(fixture("test_page.html"))
        q_ref = next(i["ref"] for i in seen["data"]["inputs"]
                     if i.get("placeholder") == "Search the web")
        await server.eyes_see_browser(fixture("article.html"))
        return await server.hands_type(q_ref, "agents")

    t0 = time.perf_counter()
    stale = ctx.run(stale_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("BRW-04", "Hands", "a ref from an older snapshot is refused as stale", run,
          stale["success"] is False and stale["data"].get("stale") is True,
          "eyes -> eyes -> hands_type(old_ref)", "stale refusal, no typing",
          f"success={stale['success']}, stale={stale['data'].get('stale')}", "", dt)

    async def restricted_flow():
        opened = await server.hands_open(fixture("restricted_page.html"))
        seen = await server.eyes_see_browser(fixture("restricted_page.html"))
        return opened, seen

    t0 = time.perf_counter()
    opened, seen = ctx.run(restricted_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("SEC-02", "Security", "a restricted page stops automation", run,
          opened["success"] is False and seen["data"]["restricted"] is True,
          "hands_open + eyes_see_browser(restricted_page.html)",
          "open refused, observation flags the restriction",
          f"open_success={opened['success']}, restricted={seen['data']['restricted']}", "", dt)

    async def url_flow():
        creds = await server.hands_open("https://user:pass@example.com/")
        scheme = await server.hands_open("ftp://example.com/")
        outside = await server.hands_open("file:///C:/Windows/System32/drivers/etc/hosts")
        return creds, scheme, outside

    t0 = time.perf_counter()
    creds, scheme, outside = ctx.run(url_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("SEC-03", "Security", "credential URLs, bad schemes and out-of-CWD files are refused",
          run, not creds["success"] and not scheme["success"] and not outside["success"],
          "hands_open with hostile URLs", "all three refused",
          f"creds={creds['success']}, scheme={scheme['success']}, outside_cwd={outside['success']}",
          "", dt)

    async def slow_flow():
        return await server.eyes_see_browser(fixture("slow_page.html"))

    t0 = time.perf_counter()
    slow = ctx.run(slow_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("BRW-05", "Eyes", "a page with a delayed element is read without crashing", run,
          slow["success"] and slow["data"]["title"] == "Slow Element",
          "eyes_see_browser(slow_page.html)", "the page is read",
          f"success={slow['success']}, title={slow['data']['title']!r}", "", dt)

    async def private_flow():
        return await server.eyes_see_browser(fixture("test_page.html"), private=True)

    t0 = time.perf_counter()
    private = ctx.run(private_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    refs_omitted = all(b.get("ref") is None for b in private["data"]["buttons"])
    check("BRW-06", "Eyes", "a private read-only session works and drops refs", run,
          private["success"] and refs_omitted, "eyes_see_browser(url, private=True)",
          "snapshot without refs, context closed",
          f"success={private['success']}, refs_omitted={refs_omitted}", "", dt)

    async def crash_flow():
        page = await browser.ensure_page()
        await page.close()
        return await server.eyes_see_browser(fixture("test_page.html"))

    t0 = time.perf_counter()
    crashed = ctx.run(crash_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("REC-01", "Recovery", "a closed page is recovered by relaunching", run,
          crashed["success"] is True, "page.close() then eyes_see_browser",
          "the next call works again", f"success={crashed['success']}", "", dt)


# ---------------------------------------------------------------- batch
def scenario_batch(ctx, run):
    from body_mcp import server

    async def validation_flow():
        return await server.hands_batch([{"type": "click"}, {"type": "nonsense"},
                                         {"type": "goto", "url": "javascript:alert(1)"}])

    t0 = time.perf_counter()
    validation = ctx.run(validation_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    errors = validation["data"].get("validation_errors", [])
    check("BAT-01", "Batch", "an invalid batch is rejected before anything executes", run,
          len(errors) == 3, "hands_batch with invalid steps",
          "validation errors, no execution", f"errors={len(errors)}", "", dt)

    async def happy_flow():
        seen = await server.eyes_see_browser(fixture("test_page.html"))
        q_ref = next(i["ref"] for i in seen["data"]["inputs"]
                     if i.get("placeholder") == "Search the web")
        search_ref = next(b["ref"] for b in seen["data"]["buttons"] if b["text"] == "Search")
        return await server.hands_batch([
            {"type": "fill", "field_ref": q_ref, "text": "agents"},
            {"type": "click", "target": search_ref},
            {"type": "verify_text", "expected": "Result A about agents"},
        ])

    t0 = time.perf_counter()
    happy = ctx.run(happy_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("BAT-02", "Batch", "a valid batch completes with verification evidence", run,
          happy["data"]["status"] == "completed"
          and happy["data"]["verification"]["status"] == "CONFIRMED",
          "hands_batch(fill, click, verify_text)", "status completed + CONFIRMED",
          f"status={happy['data']['status']}, verification={happy['data']['verification']['status']}",
          f"steps={len(happy['data']['completed_steps'])}", dt)

    async def failure_flow():
        return await server.hands_batch([
            {"type": "goto", "url": fixture("test_page.html")},
            {"type": "verify_text", "expected": "text that does not exist here"},
            {"type": "scroll", "direction": "down", "amount": 1},
        ])

    t0 = time.perf_counter()
    failure = ctx.run(failure_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("BAT-03", "Batch", "a failing step stops the batch and is reported", run,
          failure["data"]["status"] == "failed" and len(failure["data"]["completed_steps"]) == 1,
          "hands_batch with a failing verify_text", "status failed, later steps skipped",
          f"status={failure['data']['status']}, completed={len(failure['data']['completed_steps'])}",
          f"reason={failure['data']['failed_step']['reason'][:60]}", dt)

    async def duplicate_flow():
        seen = await server.eyes_see_browser(fixture("test_page.html"))
        delete_ref = next(b["ref"] for b in seen["data"]["buttons"]
                          if b["text"] == "Delete everything")
        return await server.hands_batch([
            {"type": "click", "target": delete_ref},
            {"type": "click", "target": delete_ref},
        ])

    t0 = time.perf_counter()
    duplicate = ctx.run(duplicate_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("BAT-04", "Batch", "a duplicated consequential action is refused", run,
          duplicate["data"]["status"] in ("needs_user", "blocked"),
          "hands_batch with the same dangerous click twice",
          "the second click is refused",
          f"status={duplicate['data']['status']}", "", dt)

    async def cancel_flow():
        from body_mcp import runtime

        runtime.registry.request_cancel("cancel-me")
        return await server.hands_batch(
            [{"type": "scroll", "direction": "down", "amount": 1}], task_id="cancel-me")

    t0 = time.perf_counter()
    cancelled = ctx.run(cancel_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("REC-02", "Recovery", "a cancelled task stops and reports CANCELLED", run,
          cancelled["data"]["status"] == "cancelled"
          and cancelled["data"]["verification"]["status"] == "CANCELLED",
          "runtime cancel flag + hands_batch(task_id=...)",
          "status cancelled, not 'completed'",
          f"status={cancelled['data']['status']}, "
          f"verification={cancelled['data']['verification']['status']}", "", dt)

    async def parallel_flow():
        return await server.hands_parallel([
            {"id": "a", "actions": [{"type": "goto", "url": fixture("test_page.html")},
                                    {"type": "verify_text", "expected": "Body-MCP Search"}]},
            {"id": "b", "actions": [{"type": "goto", "url": fixture("article.html")},
                                    {"type": "verify_text", "expected": "computer-use agents"}]},
        ])

    t0 = time.perf_counter()
    parallel = ctx.run(parallel_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    results = parallel["data"].get("results", [])
    ids = [r.get("task_id") for r in results]
    check("PAR-01", "Parallel", "two independent tasks run isolated", run,
          len(results) == 2 and all(r.get("success") for r in results),
          "hands_parallel with two goto+verify tasks",
          "both tasks succeed",
          f"results={[(r.get('task_id'), r.get('success')) for r in results]}", "", dt)
    check("PAR-02", "Parallel", "parallel results stay associated with their task", run,
          ids == ["a", "b"], "inspect hands_parallel results", "ids a and b present",
          f"ids={ids}", "", dt)


# ---------------------------------------------------------------- permissions
def scenario_permissions(ctx, run):
    from body_mcp import permissions, server
    from body_mcp.approvals import approvals

    async def flow():
        await approvals.clear()
        spec = permissions.required_action_spec("hands_click", "consequential", "Delete",
                                                 None, "task-A")
        await approvals.issue(spec)
        cross = await permissions.authorize("consequential", tool="hands_click",
                                            target="Delete", risk="high", action="x",
                                            task_id="task-B")
        first = await permissions.authorize("consequential", tool="hands_click",
                                            target="Delete", risk="high", action="x",
                                            task_id="task-A")
        replay = await permissions.authorize("consequential", tool="hands_click",
                                             target="Delete", risk="high", action="x",
                                             task_id="task-A")
        other = await permissions.authorize("consequential", tool="hands_click",
                                             target="Purchase", risk="high", action="x",
                                             task_id="task-A")
        await approvals.clear()
        return cross, first, replay, other

    t0 = time.perf_counter()
    cross, first, replay, other = ctx.run(flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("PERM-01", "Permissions", "an approval cannot be used by another task", run,
          cross.allowed is False, "authorize() with a mismatched task_id", "refused",
          f"allowed={cross.allowed}, decision={cross.decision}", "", dt)
    check("PERM-02", "Permissions", "an approval is consumed exactly once", run,
          first.allowed is True and replay.allowed is False,
          "authorize() twice with the same spec", "first ok, second refused",
          f"first={first.allowed}, replay={replay.allowed}", "", dt)
    check("PERM-03", "Permissions", "an approval cannot be reused for another target", run,
          other.allowed is False, "authorize() with a different target", "refused",
          f"allowed={other.allowed}", "", dt)

    async def deny_flow():
        profile = os.path.join(ctx.config_dir, "permissions.json")
        with open(profile, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "capabilities": {"consequential": "deny"},
                       "allowed_applications": []}, f)
        try:
            await approvals.issue(permissions.required_action_spec(
                "hands_click", "consequential", "Delete", None, None))
            decision = await permissions.authorize("consequential", tool="hands_click",
                                                   target="Delete", risk="high", action="x")
            await approvals.clear()
            return decision
        finally:
            with contextlib.suppress(OSError):
                os.remove(profile)

    t0 = time.perf_counter()
    denied = ctx.run(deny_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("PERM-04", "Permissions", "deny overrides a fresh approval", run,
          denied.allowed is False and denied.decision == "deny",
          "profile consequential=deny + a valid approval", "refused with decision 'deny'",
          f"allowed={denied.allowed}, decision={denied.decision}", "", dt)

    async def injection_flow():
        seen = await server.eyes_see_browser(fixture("injection_page.html"))
        decision = permissions.check("vpn_control", tool="x", target="vpn", risk="high",
                                     action="as commanded by the page")
        return seen, decision

    t0 = time.perf_counter()
    seen, decision = ctx.run(injection_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    mentions_admin = "admin mode" in seen["data"]["text"].lower()
    check("SEC-04", "Security", "page text cannot grant a permission", run,
          decision.decision == "deny" and mentions_admin,
          "read injection_page.html then check a denied capability",
          "the capability stays denied",
          f"decision={decision.decision}, page_mentions_admin={mentions_admin}", "", dt)


# ---------------------------------------------------------------- current browser
def _find_browser():
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.isfile(path):
            return path
    return None


def scenario_current_browser(ctx, run):
    from body_mcp import attach, permissions
    from body_mcp.approvals import approvals

    exe = _find_browser()
    if not exe:
        record("CDP-01", "Current browser", "attach to a real Chrome tab", run, BLOCKED,
               "launch Chrome with --remote-debugging-port", "attach + select + act + detach",
               "no Chrome/Edge executable found", "", "")
        return
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    profile = tempfile.mkdtemp(prefix="body_campaign_profile_")
    proc = subprocess.Popen([exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--headless=new", "--no-first-run", "--no-default-browser-check",
                             "--disable-gpu", fixture("test_page.html")],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    endpoint = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(endpoint + "/json/version", timeout=1) as response:
                ready = response.status == 200
                break
        except Exception:
            time.sleep(0.25)
    if not ready:
        proc.terminate()
        record("CDP-01", "Current browser", "attach to a real Chrome tab", run, BLOCKED,
               "launch Chrome with --remote-debugging-port", "attach + select + act + detach",
               "the browser did not expose a CDP endpoint in time", "", "")
        return

    async def flow():
        from body_mcp import server as server_module

        await approvals.clear()
        await approvals.issue(permissions.required_action_spec(
            "attach_browser", "chrome_attach", f"cdp:{endpoint}", None, None))
        attached = await attach.attach(endpoint)
        selector = "0"
        for tab in attached["data"].get("tabs", []):
            if "test_page.html" in tab["url"]:
                selector = str(tab["index"])
                break
        await approvals.issue(permissions.required_action_spec(
            "select_tab", "chrome_attach", f"tab:{selector}", None, None))
        selected = await attach.select_tab(selector)
        seen = await server_module.eyes_see_browser()
        q_ref = next(i["ref"] for i in seen["data"]["inputs"]
                     if i.get("placeholder") == "Search the web")
        typed = await server_module.hands_type(q_ref, "agents")
        detached = await attach.detach()
        return attached, selected, typed, detached, proc.poll() is None

    t0 = time.perf_counter()
    try:
        attached, selected, typed, detached, alive = ctx.run(flow())
        dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
        check("CDP-01", "Current browser", "attach to a real Chrome tab", run,
              attached["success"] and selected["success"] and typed["success"],
              "Chrome with --remote-debugging-port + attach_browser/select_tab",
              "the tab is listed, selected and driven",
              f"tabs={len(attached['data'].get('tabs', []))}, selected={selected['success']}, "
              f"typed={typed['success']}",
              f"typed verification={typed['data']['verification']['status']}", dt)
        check("CDP-02", "Current browser", "detach closes only our session", run,
              detached["success"] and alive, "detach_browser()",
              "the browser keeps running, our page is released",
              f"detached={detached['success']}, browser_alive={alive}", "", dt)
    finally:
        with contextlib.suppress(Exception):
            proc.terminate()
            proc.wait(timeout=10)

    verdict = attach._valid_endpoint("http://192.168.1.10:9222")
    check("CDP-03", "Security", "a non-loopback CDP endpoint is refused", run,
          verdict["ok"] is False, "attach_browser('http://192.168.1.10:9222')",
          "refused before any connection", f"reason={verdict['reason'][:70]}", "", "")

    async def denied_flow():
        await approvals.clear()
        result = await attach.attach(endpoint)
        await approvals.clear()
        return result

    denied = ctx.run(denied_flow())
    check("CDP-04", "Security", "attaching without an approval is refused", run,
          denied["success"] is False and denied["data"].get("permission") == "ask",
          "attach_browser without an approval", "refused with the required action spec",
          f"success={denied['success']}, permission={denied['data'].get('permission')}", "", "")


# ---------------------------------------------------------------- platform
def scenario_platform(ctx, run):
    from body_mcp import console as console_mod
    from body_mcp import events, memory, server, sysprofile

    console = console_mod.get_console()
    console.port = 8801
    console.start()

    def get(path, headers=None):
        request = urllib.request.Request(path, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "replace")

    try:
        base = f"http://127.0.0.1:{console.port}"
        t0 = time.perf_counter()
        status_no_token, _ = get(base + "/api/state")
        status_ok, body = get(base + "/api/state?token=" + console.token)
        status_bad_host, _ = get(base + "/api/state?token=" + console.token,
                                 headers={"Host": "evil.example.com"})
        status_bad_origin, _ = get(base + "/api/state?token=" + console.token,
                                   headers={"Origin": "http://evil.example.com"})
        dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
        check("CON-01", "Console", "the console API requires the session token", run,
              status_no_token == 401, "GET /api/state without a token", "401",
              f"status={status_no_token}", "", dt)
        check("CON-02", "Console", "the console serves real state with the token", run,
              status_ok == 200 and "events" in body, "GET /api/state?token=...",
              "200 with JSON state", f"status={status_ok}, has_events={'events' in body}",
              "", dt)
        check("CON-03", "Console", "a foreign Host header is refused", run,
              status_bad_host == 403, "GET /api/state with Host: evil.example.com", "403",
              f"status={status_bad_host}", "", dt)
        check("CON-04", "Console", "a foreign Origin is refused", run,
              status_bad_origin == 403, "GET /api/state with Origin: http://evil.example.com",
              "403", f"status={status_bad_origin}", "", dt)
    finally:
        console.stop()

    events.bus.clear()

    async def observation_flow():
        await server.eyes_see_browser(fixture("test_page.html"))

    t0 = time.perf_counter()
    ctx.run(observation_flow())
    items = events.bus.recent(limit=10)
    types = [item["type"] for item in items]
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("EVT-01", "Events", "the executor emits real events", run,
          "observation" in types, "eyes_see_browser then read the event bus",
          "an observation event exists", f"types={types}", "", dt)

    t0 = time.perf_counter()
    written = memory.add(title="campaign note", content="a harmless durable lesson",
                          scope="project", verified=True)
    found = memory.search("campaign note")
    deleted = memory.delete(written["data"]["id"])
    secret = memory.add(title="k", content="api_key = sk-abcdefghijklmnopqrstuvwxyz012345")
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("MEM-01", "Memory", "write, search and delete a memory", run,
          bool(found) and deleted, "memory.add/search/delete",
          "the entry is found and removed",
          f"found={len(found)}, deleted={deleted}", "", dt)
    check("MEM-02", "Memory", "credentials are refused", run,
          secret["success"] is False, "memory.add with an api key", "refused",
          f"success={secret['success']}", "", dt)

    memory.add(title="persistence probe", content="written before the child process reads",
               scope="capability", verified=True)
    env = dict(os.environ)
    env["BODY_MCP_CONFIG_DIR"] = ctx.config_dir
    probe = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s');"
         "from body_mcp import memory; hits = memory.search('persistence probe');"
         "print(hits[0]['title'] if hits else 0)" % os.path.join(REPO, "src")],
        capture_output=True, text=True, timeout=60, env=env)
    child_saw = probe.stdout.strip()
    check("MEM-03", "Memory", "memory survives a process restart", run,
          child_saw == "persistence probe",
          "read memory.search() from a second process with the same config dir",
          "the second process sees the stored entry", f"child_process_saw={child_saw!r}",
          "", "")

    from body_mcp import research

    t0 = time.perf_counter()
    result = ctx.run(research.collect([fixture("test_page.html"), fixture("test_page.html")]))
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("RES-01", "Research", "evidence records carry metadata and deduplicate", run,
          result["data"]["collected"] == 1 and result["data"]["duplicates"] == 1
          and result["data"]["items"][0]["content_hash"],
          "research_collect([same url twice])",
          "one collected, one duplicate, full metadata",
          f"collected={result['data']['collected']}, duplicates={result['data']['duplicates']}, "
          f"title={result['data']['items'][0]['title']!r}",
          f"hash={result['data']['items'][0]['content_hash'][:8]}", dt)

    t0 = time.perf_counter()

    async def privacy_flow():
        started = await server.privacy_session_start("campaign")
        session_id = started["data"]["session_id"]
        opened = await server.privacy_session_open(session_id, fixture("test_page.html"))
        snap = await server.privacy_session_snapshot(session_id)
        ended = await server.privacy_session_end(session_id)
        return opened, snap, ended

    opened, snap, ended = ctx.run(privacy_flow())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("PRV-01", "Privacy", "a privacy session is isolated and cleaned up", run,
          opened["success"] and ended["data"]["cleanup_verified"] is True,
          "privacy_session_start/open/snapshot/end",
          "the context is closed and the cleanup is verified",
          f"opened={opened['success']}, cleanup_verified={ended['data']['cleanup_verified']}",
          "", dt)

    t0 = time.perf_counter()
    profile = sysprofile.collect(refresh=True)
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("SYS-01", "System", "the system inventory reports real facts", run,
          profile["cpu"]["logical_cores"] >= 1, "body_profile(refresh=True)",
          "CPU/RAM/optional modules reported",
          f"cores={profile['cpu']['logical_cores']}, "
          f"ram_available_mb={profile['memory']['available_mb']}", "", dt)

    t0 = time.perf_counter()
    recommendation = ctx.run(server.body_recommend(needs=["tools"]))
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("SYS-02", "System", "the backend recommender is a dry run", run,
          recommendation["data"]["dry_run"] is True
          and bool(recommendation["data"]["recommended"]),
          "body_recommend(needs=['tools'])", "ranked options, nothing installed",
          f"recommended={recommendation['data']['recommended']}, "
          f"dry_run={recommendation['data']['dry_run']}", "", dt)

    t0 = time.perf_counter()
    spoken = ctx.run(server.body_speak("Body MCP campaign voice check."))
    stopped = ctx.run(server.body_stop_speaking())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("VOI-01", "Voice out", "local TTS synthesises, plays and stops", run,
          spoken["success"] and stopped["data"]["stopped"] is True,
          "body_speak + body_stop_speaking", "audio produced, playback stopped",
          f"bytes={spoken['data'].get('audio_bytes')}, "
          f"synthesis_ms={spoken['data'].get('synthesis_ms')}, stopped={stopped['data']['stopped']}",
          "audible output itself is not machine-verifiable", dt)

    t0 = time.perf_counter()
    empty = ctx.run(server.body_speak(""))
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("VOI-02", "Voice out", "empty text is refused", run,
          empty["success"] is False, "body_speak('')", "refused",
          f"success={empty['success']}", "", dt)


# ---------------------------------------------------------------- blocked deps
def scenario_blocked(ctx, run):
    from body_mcp import ears
    from body_mcp.config import tesseract_cmd

    if tesseract_cmd():
        from body_mcp import eyes

        try:
            result = eyes.see_desktop()
            ok = result["success"] and bool(result["data"].get("text"))
            check("DSK-01", "Desktop", "real desktop capture + OCR", run, ok,
                  "eyes_see_desktop()", "text extracted from the real screen",
                  f"chars={len(result['data'].get('text', ''))}", "", "")
        except Exception as exc:
            check("DSK-01", "Desktop", "real desktop capture + OCR", run, False,
                  "eyes_see_desktop()", "text extracted", f"{type(exc).__name__}: {exc}",
                  "", "")
    else:
        record("DSK-01", "Desktop", "real desktop capture + OCR", run, BLOCKED,
               "eyes_see_desktop()", "text extracted from the real screen",
               "Tesseract is not installed (winget install -e --id UB-Mannheim.TesseractOCR)",
               "", "")

    try:
        import faster_whisper  # noqa: F401

        record("VOI-03", "Voice in", "live microphone capture + local transcription", run,
               NOT_RUN, "ears_listen(5)", "a real transcript",
               "recording needs the user's explicit consent (--allow-mic)", "", "")
    except Exception:
        record("VOI-03", "Voice in", "live microphone capture + local transcription", run,
               BLOCKED, "ears_listen(5)", "a real transcript",
               "faster-whisper is not installed (pip install -e '.[voice]')", "", "")

    import numpy as np

    original_record = ears.record_mic
    original_transcribe = ears.transcribe
    try:
        ears.record_mic = lambda seconds: np.zeros(16000, dtype=np.float32)

        def _never(audio, model_size=None):
            raise AssertionError("silence must not reach the transcriber")

        ears.transcribe = _never
        silence = ears.listen(1)
        check("VOI-04", "Voice in", "silence is detected instead of inventing words", run,
              silence["success"] is False and silence["data"].get("silence") is True,
              "ears.listen with a silent buffer", "a 'no speech detected' result",
              f"success={silence['success']}, silence={silence['data'].get('silence')}",
              "", "", status=PASS_MOCK)
    finally:
        ears.record_mic = original_record
        ears.transcribe = original_transcribe


def scenario_desktop(ctx, run):
    """Desktop capture, OCR discovery and the live observation session."""
    from body_mcp import eyes, watch

    t0 = time.perf_counter()
    shot = eyes.capture_png(monitor=1)
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    ok_capture = bool(shot.get("ok")) and shot.get("bytes", 0) > 1000
    check("DES-01", "Desktop", "capture the real screen", run, ok_capture,
          "eyes.capture_png(monitor=1)", "a real PNG of the primary screen",
          f"ok={shot.get('ok')}, bytes={shot.get('bytes')}, "
          f"region={shot.get('region')}", "in memory only, nothing written to disk", dt)

    t0 = time.perf_counter()
    status = eyes.ocr_status()
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    honest = all(("available" in entry and (entry.get("available") or entry.get("reason")))
                 for entry in status["providers"])
    check("OCR-01", "Desktop", "OCR engines are discovered, never assumed", run, honest,
          "eyes.ocr_status()", "every engine reports availability and a reason",
          f"selected={status['selected']}, "
          f"engines={[(e['provider'], e['available']) for e in status['providers']]}", "", dt)

    t0 = time.perf_counter()
    if status["selected"] is None:
        # no engine -> the session cannot run; that is a blocker, not a failure
        record("OCR-02", "Desktop", "a live observation session starts, reads and stops",
               run, BLOCKED, "desktop_watch_start / _read / _stop",
               "the session runs and releases its resources",
               "no OCR engine is installed - install Tesseract "
               "(winget install -e --id UB-Mannheim.TesseractOCR)", "", dt)
        return
    started = watch.start(monitor=1, interval=1.0)
    session_id = started["data"]["session_id"] if started.get("success") else None
    read = watch.read(session_id) if session_id else {"success": False}
    stopped = watch.stop(session_id) if session_id else {"success": False}
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    ok_session = bool(started.get("success")) and read.get("success") is True \
        and stopped.get("success") is True and watch.sessions() == []
    check("OCR-02", "Desktop", "a live observation session starts, reads and stops", run,
          ok_session, "desktop_watch_start / _read / _stop",
          "the session runs and releases its resources",
          f"started={started.get('success')}, read={read.get('success')}, "
          f"stopped={stopped.get('success')}",
          f"ocr runs={stopped.get('data', {}).get('ocr_runs')}", dt)


def scenario_vision(ctx, run):
    """Vision mode: a real page is rendered, captured and handed over as an image."""
    from mcp import Client

    from body_mcp import server, vision

    t0 = time.perf_counter()
    fixture = "file:///" + os.path.abspath(os.path.join(FIXTURES, "test_page.html")).replace("\\", "/")

    async def run_client():
        async with Client(server.mcp, raise_exceptions=True) as client:
            return await client.call_tool("eyes_see_browser",
                                          {"url": fixture, "screenshot": True})

    result = ctx.run(run_client())
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    blocks = [b.type for b in result.content]
    has_image = "image" in blocks
    image_bytes = 0
    if has_image:
        image = [b for b in result.content if b.type == "image"][0]
        image_bytes = len(image.data)
    check("VIS-01", "Vision", "a page is delivered as text AND an image", run,
          has_image and image_bytes > 1000 and "text" in blocks,
          "eyes_see_browser(screenshot=True) through a real MCP client",
          "a text block and an image block arrive",
          f"blocks={blocks}, image_base64_chars={image_bytes}",
          f"structured image meta={result.structured_content['data'].get('image')}", dt)

    t0 = time.perf_counter()
    prepared = vision.prepare_image(b"")
    dt = f"{int((time.perf_counter() - t0) * 1000)} ms"
    check("VIS-02", "Vision", "an empty image is refused, not shipped", run,
          prepared.get("ok") is False, "vision.prepare_image(b'')",
          "a refusal instead of a broken image",
          f"ok={prepared.get('ok')}, reason={prepared.get('reason')}", "", dt)


def main() -> int:
    parser = argparse.ArgumentParser(description="Body-MCP QA campaign")
    parser.add_argument("--runs", type=int, default=1, help="repeats per scenario")
    parser.add_argument("--out", default=os.path.join(REPO, "reports", "qa-campaign"))
    args = parser.parse_args()

    ctx = Ctx()
    started = time.time()
    try:
        for run in range(1, args.runs + 1):
            print(f"--- run {run} ---", flush=True)
            scenario_mcp(ctx, run)
            scenario_browser(ctx, run)
            scenario_batch(ctx, run)
            scenario_permissions(ctx, run)
            scenario_current_browser(ctx, run)
            scenario_platform(ctx, run)
            scenario_desktop(ctx, run)
            scenario_vision(ctx, run)
            scenario_blocked(ctx, run)
    finally:
        ctx.close()

    os.makedirs(args.out, exist_ok=True)
    matrix_path = os.path.join(args.out, "test-matrix.csv")
    fields = ["test_id", "feature", "scenario", "run_number", "test_type", "status",
              "command", "expected_result", "actual_result", "evidence", "duration", "issue_id"]
    with open(matrix_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in ROWS:
            writer.writerow(row)

    counts: dict[str, int] = {}
    for row in ROWS:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print(f"\n{len(ROWS)} executions in {int(time.time() - started)} s -> {matrix_path}")
    for status in sorted(counts):
        print(f"  {status}: {counts[status]}")
    return 1 if counts.get(FAIL) else 0


if __name__ == "__main__":
    sys.exit(main())
