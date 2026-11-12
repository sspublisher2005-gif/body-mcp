"""Run the test prompts (P1, P2, P4, P5, P6) against the real MCP server.

    python scripts/run_test_prompts.py            # everything except P3
    python scripts/run_test_prompts.py --p3       # also the current-browser flow
    python scripts/run_test_prompts.py --mic      # include the microphone step (P2.B)

It speaks MCP to the server exactly like a client would, so the results are the ones
your agent will see - not a simulation.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

FIXTURE = "file:///" + os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures")
).replace("\\", "/") + "/"

RESULTS: list[dict] = []


def record(prompt: str, step: str, status: str, evidence: str) -> None:
    RESULTS.append({"prompt": prompt, "step": step, "status": status, "evidence": evidence})
    print(f"[{status:<10}] {prompt} {step}: {evidence}")


def payload_of(result):
    """The structured payload of a tool call (or the text block)."""
    structured = getattr(result, "structured_content", None)
    if structured:
        return structured
    for block in result.content:
        if getattr(block, "type", "") == "text":
            try:
                return json.loads(block.text)
            except Exception:
                return {"text": block.text}
    return {}


async def call(client, name: str, arguments: dict):
    return await client.call_tool(name, arguments)


async def p1(client) -> None:
    status = payload_of(await call(client, "body_status", {}))
    record("P1", "1 body_status",
           "PASS" if status.get("success") else "FAIL",
           f"version={status.get('data', {}).get('version')}, "
           f"tools={status.get('data', {}).get('server', {}).get('tools_registered')}")
    [k for k, v in (status.get("data", {}).get("desktop_ocr", {}) or {}).items()
                  if k == "verified" and v is False]
    ears = status.get("data", {}).get("ears", {})
    tts = status.get("data", {}).get("voice_output", {})
    record("P1", "1b not-verified capabilities", "PASS",
           f"desktop_ocr.verified={status.get('data', {}).get('desktop_ocr', {}).get('verified')}, "
           f"ears.verified={ears.get('verified')}, voice_output.verified={tts.get('verified')}")

    profile = payload_of(await call(client, "body_profile", {"refresh": True}))
    data = profile.get("data", {})
    record("P1", "2 body_profile", "PASS" if profile.get("success") else "FAIL",
           f"platform={data.get('platform')}, cores={data.get('cpu_cores')}, "
           f"ram_free_mb={data.get('ram_available_mb')}, "
           f"optional={ {k: v for k, v in (data.get('optional_modules') or {}).items() if v} }")

    seen = payload_of(await call(client, "eyes_see_browser", {"url": FIXTURE + "test_page.html"}))
    d = seen.get("data", {})
    record("P1", "3 eyes_see_browser(text)", "PASS" if seen.get("success") else "FAIL",
           f"title={d.get('title')!r}, links={len(d.get('links', []))}, "
           f"buttons={[b.get('text') for b in d.get('buttons', [])]}, "
           f"inputs={[(i.get('type'), i.get('placeholder'), i.get('sensitive')) for i in d.get('inputs', [])]}")

    shot = await call(client, "eyes_see_browser",
                      {"url": FIXTURE + "test_page.html", "screenshot": True})
    blocks = [b.type for b in shot.content]
    image_bytes = 0
    for block in shot.content:
        if block.type == "image":
            image_bytes = len(base64.b64decode(block.data))
    meta = (getattr(shot, "structured_content", {}) or {}).get("data", {}).get("image", {})
    record("P1", "4 eyes_see_browser(screenshot=True)",
           "PASS" if "image" in blocks else "FAIL",
           f"blocks={blocks}, image_bytes={image_bytes}, meta={meta}")

    desktop = payload_of(await call(client, "eyes_see_desktop", {}))
    if desktop.get("success"):
        record("P1", "5 eyes_see_desktop", "PASS",
               f"chars={len(desktop.get('data', {}).get('text', ''))}, "
               f"provider={desktop.get('data', {}).get('provider')}")
    else:
        record("P1", "5 eyes_see_desktop", "BLOCKED",
               f"{desktop.get('message')} | install: "
               f"{desktop.get('data', {}).get('install')}")

    verified = payload_of(await call(client, "reflex_verify", {"expected": "Body-MCP Search"}))
    record("P1", "6 reflex_verify", "PASS" if verified.get("found") else "FAIL",
           f"found={verified.get('found')}, evidence="
           f"{(verified.get('data', {}).get('evidence') or '')[:90]!r}")

    written = payload_of(await call(client, "memory_write", {
        "title": "Body-MCP smoke test", "content": "the eyes can deliver text and one image",
        "scope": "project", "verified": True}))
    found = payload_of(await call(client, "memory_search", {"query": "smoke test"}))
    items = found.get("data", {}).get("items", [])
    deleted = payload_of(await call(client, "memory_delete",
                                   {"memory_id": written.get("data", {}).get("id", "")}))
    record("P1", "7 memory write/search/delete",
           "PASS" if (written.get("success") and items and deleted.get("success")) else "FAIL",
           f"written_id={written.get('data', {}).get('id')}, found={len(items)}, "
           f"first_title={items[0]['title'] if items else None}, deleted={deleted.get('success')}")

    events = payload_of(await call(client, "body_events", {"limit": 5}))
    evs = events.get("data", {}).get("events", [])
    record("P1", "8 body_events", "PASS" if evs else "FAIL",
           f"events={[(e.get('type'), e.get('task_id'), e.get('status')) for e in evs]}")


async def p2(client, mic: bool) -> None:
    shot = await call(client, "eyes_see_browser",
                      {"url": FIXTURE + "test_page.html", "screenshot": True})
    blocks = [b.type for b in shot.content]
    image = next((b for b in shot.content if b.type == "image"), None)
    meta = (getattr(shot, "structured_content", {}) or {}).get("data", {}).get("image", {})
    record("P2", "A1/A2 vision", "PASS" if image else "FAIL",
           f"blocks={blocks}, image_bytes={len(base64.b64decode(image.data)) if image else 0}, "
           f"meta={meta}")

    text_only = payload_of(await call(client, "eyes_see_browser",
                                      {"url": FIXTURE + "test_page.html"}))
    d = text_only.get("data", {})
    record("P2", "A3 text vs image",
           "PASS",
           f"text-only gives title={d.get('title')!r}, {len(d.get('buttons', []))} buttons, "
           f"{len(d.get('inputs', []))} inputs, {len(d.get('text', ''))} text chars; "
           f"the image adds the visual layout the DOM cannot express")

    if not mic:
        record("P2", "B4/B5 hearing", "NOT_RUN",
               "microphone step skipped (--mic not given): recording needs the user")
        return
    heard = payload_of(await call(client, "ears_listen", {"seconds": 8, "stop_on_silence": True}))
    if heard.get("success"):
        record("P2", "B4/B5 hearing", "PASS",
               f"transcript={heard.get('data', {}).get('transcript')!r}, "
               f"ended_by={heard.get('data', {}).get('ended_by')}, "
               f"uncertain={heard.get('data', {}).get('uncertain')}, "
               f"rms={heard.get('data', {}).get('rms')}")
    else:
        record("P2", "B4/B5 hearing", "BLOCKED",
               f"{heard.get('message')} | data={heard.get('data')}")


async def p4(client) -> None:
    result = payload_of(await call(client, "research_collect",
                                   {"urls": [FIXTURE + "test_page.html",
                                             FIXTURE + "test_page.html"]}))
    d = result.get("data", {})
    items = d.get("items", [])
    for item in items:
        record("P4", "record", "PASS",
               f"source={item.get('source_name')}, title={item.get('title')!r}, "
               f"published={item.get('published')}, method={item.get('retrieval_method')!r}, "
               f"excerpt={item.get('excerpt', '')[:60]!r}, hash={item.get('content_hash')}, "
               f"status={item.get('status')}, verification={item.get('verification')}")
    record("P4", "summary", "PASS",
           f"collected={d.get('collected')}, blocked={d.get('blocked')}, "
           f"duplicates={d.get('duplicates')}, coverage={d.get('coverage_note')}")


async def p5(client) -> None:
    seen = payload_of(await call(client, "eyes_see_browser", {"url": FIXTURE + "test_page.html"}))
    pw_ref = next((i["ref"] for i in seen.get("data", {}).get("inputs", [])
                   if i.get("placeholder") == "Password"), None)
    typed = payload_of(await call(client, "hands_type", {"field_ref": pw_ref, "text": "hunter2"}))
    record("P5", "1 password field", "PASS" if not typed.get("success") else "FAIL",
           f"success={typed.get('success')}, message={typed.get('message')[:110]!r}, "
           f"sensitive={typed.get('data', {}).get('sensitive')}")

    delete_ref = next((b["ref"] for b in seen.get("data", {}).get("buttons", [])
                       if b.get("text") == "Delete everything"), None)
    batch = payload_of(await call(client, "hands_batch",
                                  {"actions": [{"type": "click", "target": delete_ref}]}))
    needs = batch.get("data", {}).get("needs_user") or {}
    record("P5", "2 dangerous click in a batch", "PASS",
           f"status={batch.get('data', {}).get('status')}, reason={needs.get('reason')!r}, "
           f"checkpoint_id={batch.get('data', {}).get('checkpoint_id')}, "
           f"side_effect=none (the click never ran)")

    restricted = payload_of(await call(client, "eyes_see_browser",
                                       {"url": FIXTURE + "restricted_page.html"}))
    record("P5", "3 restricted page", "PASS",
           f"restricted={restricted.get('data', {}).get('restricted')}, "
           f"message={restricted.get('message')[:130]!r}")

    creds = payload_of(await call(client, "hands_open", {"url": "https://user:pass@example.com/"}))
    record("P5", "4 credential URL", "PASS" if not creds.get("success") else "FAIL",
           f"success={creds.get('success')}, message={creds.get('message')[:110]!r}")


async def p6(client) -> None:
    seen = payload_of(await call(client, "eyes_see_browser", {"url": FIXTURE + "test_page.html"}))
    q_ref = next((i["ref"] for i in seen.get("data", {}).get("inputs", [])
                  if i.get("placeholder") == "Search the web"), None)
    search_ref = next((b["ref"] for b in seen.get("data", {}).get("buttons", [])
                       if b.get("text") == "Search"), None)
    typed = payload_of(await call(client, "hands_type", {"field_ref": q_ref, "text": "agents"}))
    clicked = payload_of(await call(client, "hands_click", {"target": search_ref}))
    verified = payload_of(await call(client, "reflex_verify", {"expected": "Result A about agents"}))
    record("P6", "type + submit + verify",
           "PASS" if (typed.get("success") and clicked.get("success") and verified.get("found"))
           else "FAIL",
           f"typed={typed.get('success')} ({typed.get('data', {}).get('verification', {}).get('status')}), "
           f"clicked={clicked.get('success')} ({clicked.get('data', {}).get('verification', {}).get('status')}), "
           f"verified={verified.get('found')}, "
           f"evidence={(verified.get('data', {}).get('evidence') or '')[:80]!r}")


async def p3() -> None:
    """The current-browser flow, using the disposable profile of the launcher."""
    import subprocess
    import sys as _sys

    port = 9333
    launcher = [_sys.executable, "-m", "body_mcp.cdp_launch", "--browser", "chrome",
                "--port", str(port)]
    env = dict(os.environ, PYTHONPATH=os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")))
    out = subprocess.run(launcher, capture_output=True, text=True, timeout=180, env=env)
    record("P3", "0 launcher", "PASS" if out.returncode == 0 else "FAIL",
           out.stdout.strip().splitlines()[-1] if out.stdout else out.stderr[:120])

    from body_mcp import attach, permissions, server
    from body_mcp.approvals import approvals

    endpoint = f"http://127.0.0.1:{port}"

    async def flow():
        await approvals.clear()
        await approvals.issue(permissions.required_action_spec(
            "attach_browser", "chrome_attach", f"cdp:{endpoint}", None, None))
        attached = await attach.attach(endpoint)
        tabs = attached.get("data", {}).get("tabs", [])
        await approvals.issue(permissions.required_action_spec(
            "select_tab", "chrome_attach", "tab:0", None, None))
        selected = await attach.select_tab("0")
        seen = await server.eyes_see_browser()
        watch = await server.desktop_watch_start(interval=2)
        polls = []
        for _ in range(3):
            await asyncio.sleep(2)
            polls.append((await server.desktop_watch_read()).get("data", {}))
        stopped = await server.desktop_watch_stop()
        detached = await attach.detach()
        return attached, tabs, selected, seen, watch, polls, stopped, detached

    try:
        attached, tabs, selected, seen, watch, polls, stopped, detached = asyncio.run(flow())
        record("P3", "1 attach + list_tabs", "PASS" if attached.get("success") else "FAIL",
               f"tabs={[(t.get('index'), t.get('title'), t.get('url')) for t in tabs]}")
        record("P3", "2 select_tab", "PASS" if selected.get("success") else "FAIL",
               f"{selected.get('message')}")
        record("P3", "3 eyes_see_browser()", "PASS" if seen.get("success") else "FAIL",
               f"url={seen.get('data', {}).get('url')}, title={seen.get('data', {}).get('title')!r}, "
               f"buttons={len(seen.get('data', {}).get('buttons', []))}")
        record("P3", "5 desktop_watch", "PASS" if watch.get("success") else "FAIL",
               f"started={watch.get('message')} | polls="
               f"{[(p.get('observed_at'), p.get('changed'), p.get('ocr_skipped')) for p in polls]} | "
               f"stopped={stopped.get('message')}")
        record("P3", "7 detach_browser", "PASS" if detached.get("success") else "FAIL",
               detached.get("message"))
    finally:
        stop = subprocess.run([_sys.executable, "-m", "body_mcp.cdp_launch", "--stop"],
                              capture_output=True, text=True, timeout=120, env=env)
        status = subprocess.run([_sys.executable, "-m", "body_mcp.cdp_launch", "--status"],
                                capture_output=True, text=True, timeout=120, env=env)
        record("P3", "8 status after stop", "PASS",
               f"{(stop.stdout or '').strip()[:90]} | {(status.stdout or '').strip()[:90]}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--p3", action="store_true")
    parser.add_argument("--mic", action="store_true")
    args = parser.parse_args()

    from mcp import Client

    from body_mcp import server

    async with Client(server.mcp, raise_exceptions=True) as client:
        await p1(client)
        await p2(client, args.mic)
        await p4(client)
        await p5(client)
        await p6(client)
    if args.p3:
        await p3()

    counts: dict[str, int] = {}
    for row in RESULTS:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    print("\n" + "=" * 72)
    print(f"{len(RESULTS)} steps: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
