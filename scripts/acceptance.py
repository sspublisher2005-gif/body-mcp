"""Body-MCP acceptance runner.

Runs the checks that need a REAL environment and reports honest states:

    PASS_REAL       exercised against the real thing (real browser, real speech engine)
    PASS_MOCK_ONLY  exercised with a stubbed dependency (not a hardware pass)
    FAIL            executed and failed
    BLOCKED         cannot run here - the exact blocker is named
    NOT_RUN         deliberately skipped (e.g. recording needs your consent)

    python scripts/acceptance.py                 # everything that is safe to run
    python scripts/acceptance.py --allow-mic     # also record 5 seconds of microphone audio
    python scripts/acceptance.py --public-url URL   # add one public source to the research check
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

PASS_REAL = "PASS_REAL"
PASS_MOCK_ONLY = "PASS_MOCK_ONLY"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_RUN = "NOT_RUN"

RESULTS: list[dict] = []


def record(name: str, status: str, detail: str = "") -> None:
    RESULTS.append({"check": name, "status": status, "detail": detail})
    print(f"[{status:<14}] {name}: {detail}")


def fixture_url(name: str) -> str:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "fixtures", name)
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def check_mcp_handshake() -> None:
    """Real subprocess, real protocol."""
    env = dict(os.environ)
    src = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    env["BODY_MCP_BROWSER_MODE"] = "headless"
    proc = subprocess.Popen([sys.executable, "-m", "body_mcp.server"], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=src)
    try:
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2026-07-28", "capabilities": {},
                                         "clientInfo": {"name": "acceptance", "version": "1"}}})
        proc.stdin.write(payload.encode() + b"\n")
        proc.stdin.flush()
        line = proc.stdout.readline().decode("utf-8", "replace").strip()
        message = json.loads(line)
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized",
                                     "params": {}}).encode() + b"\n")
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                                     "params": {}}).encode() + b"\n")
        proc.stdin.flush()
        listed = json.loads(proc.stdout.readline().decode("utf-8", "replace").strip())
        count = len(listed["result"]["tools"])
        if message["result"]["serverInfo"]["name"] == "Body-MCP" and count > 0:
            record("MCP handshake + tool discovery", PASS_REAL,
                   f"server '{message['result']['serverInfo']['name']}', {count} tools over stdio")
        else:
            record("MCP handshake + tool discovery", FAIL, str(message)[:200])
    except Exception as exc:
        record("MCP handshake + tool discovery", FAIL, f"{type(exc).__name__}: {exc}")
    finally:
        import contextlib

        with contextlib.suppress(Exception):
            proc.stdin.close()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_managed_browser() -> None:
    """Real Chromium, real fixture page, real verification."""
    from body_mcp import server

    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        q_ref = next(i["ref"] for i in seen["data"]["inputs"]
                     if i.get("placeholder") == "Search the web")
        typed = await server.hands_type(q_ref, "agents")
        search_ref = next(b["ref"] for b in seen["data"]["buttons"] if b["text"] == "Search")
        clicked = await server.hands_click(search_ref)
        verified = await server.reflex_verify("Result A about agents")
        return typed, clicked, verified

    try:
        typed, clicked, verified = asyncio.run(flow())
        ok = (typed["success"] and clicked["success"] and verified["found"]
              and typed["data"]["verification"]["status"] == "CONFIRMED")
        record("Managed browser: see -> type -> click -> verify", PASS_REAL if ok else FAIL,
               f"typed={typed['data'].get('verification', {}).get('status')}, "
               f"verified={verified['found']}")
    except Exception as exc:
        record("Managed browser: see -> type -> click -> verify", FAIL, f"{type(exc).__name__}: {exc}")


def _find_browser() -> str | None:
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.isfile(path):
            return path
    return None


def check_current_browser() -> None:
    """Real Chrome over CDP: attach -> select -> act -> detach (our session only)."""
    import socket
    import urllib.request

    from body_mcp import attach, permissions
    from body_mcp.approvals import approvals

    exe = _find_browser()
    if not exe:
        record("Current browser (CDP attach/select/detach)", BLOCKED,
               "no Chrome/Edge executable found in the standard locations")
        return
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    profile = tempfile.mkdtemp(prefix="body_acceptance_profile_")
    url = fixture_url("test_page.html")
    proc = subprocess.Popen([exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                             "--headless=new", "--no-first-run", "--no-default-browser-check",
                             "--disable-gpu", url],
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
        record("Current browser (CDP attach/select/detach)", BLOCKED,
               "the browser did not expose a CDP endpoint in time")
        return

    async def flow():
        await approvals.clear()
        await approvals.issue(permissions.required_action_spec(
            "attach_browser", "chrome_attach", f"cdp:{endpoint}", None, None))
        attached = await attach.attach(endpoint)
        # pick the tab that actually shows the fixture (headless Chrome also opens
        # an about:blank tab)
        selector = "0"
        for tab in attached["data"].get("tabs", []):
            if "test_page.html" in tab["url"]:
                selector = str(tab["index"])
                break
        await approvals.issue(permissions.required_action_spec(
            "select_tab", "chrome_attach", f"tab:{selector}", None, None))
        selected = await attach.select_tab(selector)
        from body_mcp import server

        seen = await server.eyes_see_browser()
        q_ref = next(i["ref"] for i in seen["data"]["inputs"]
                     if i.get("placeholder") == "Search the web")
        typed = await server.hands_type(q_ref, "agents")
        detached = await attach.detach()
        alive = proc.poll() is None
        return attached, selected, typed, detached, alive

    try:
        attached, selected, typed, detached, alive = asyncio.run(flow())
        ok = (attached["success"] and selected["success"] and typed["success"]
              and detached["success"] and alive)
        record("Current browser (CDP attach/select/detach)", PASS_REAL if ok else FAIL,
               f"tabs={len(attached['data'].get('tabs', []))}, typed={typed['success']}, "
               f"detached={detached['success']}, browser still running={alive}")
    except Exception as exc:
        record("Current browser (CDP attach/select/detach)", FAIL, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def check_desktop_ocr() -> None:
    """Real screenshot + real OCR, if Tesseract is installed."""
    from body_mcp import eyes
    from body_mcp.config import tesseract_cmd

    cmd = tesseract_cmd()
    if not cmd:
        record("Desktop capture + OCR", BLOCKED,
               "Tesseract is not installed (winget install -e --id UB-Mannheim.TesseractOCR)")
        return
    try:
        result = eyes.see_desktop()
        record("Desktop capture + OCR", PASS_REAL if result["success"] else FAIL,
               (result["data"].get("text", "")[:60] if result["success"]
                else result["message"][:120]))
    except Exception as exc:
        record("Desktop capture + OCR", FAIL, f"{type(exc).__name__}: {exc}")


def check_microphone(allow_mic: bool) -> None:
    """Real microphone capture + real local transcription (needs your consent)."""
    from body_mcp import ears

    if not allow_mic:
        record("Microphone capture + local STT", NOT_RUN,
               "recording needs your consent - rerun with --allow-mic")
        return
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        record("Microphone capture + local STT", BLOCKED,
               "faster-whisper is not installed (pip install -e '.[voice]')")
        return
    try:
        result = ears.listen(5)
        if result["success"]:
            record("Microphone capture + local STT", PASS_REAL,
                   f"transcribed {len(result['data']['transcript'])} chars")
        elif result["data"].get("silence"):
            record("Microphone capture + local STT", FAIL,
                   "the recording was silent - speak during the 5 seconds")
        else:
            record("Microphone capture + local STT", BLOCKED, result["message"][:140])
    except Exception as exc:
        record("Microphone capture + local STT", FAIL, f"{type(exc).__name__}: {exc}")


def check_tts() -> None:
    """Real local speech synthesis + playback start."""
    from body_mcp import tts

    info = tts.available()
    if not info["available"]:
        record("Local TTS (synthesis + playback)", BLOCKED, info["reason"])
        return
    try:
        result = tts.speak("Body MCP acceptance test.")
        if result["success"]:
            time.sleep(0.5)
            stopped = tts.stop()
            record("Local TTS (synthesis + playback)", PASS_REAL,
                   f"{result['data']['audio_bytes']} bytes, synthesis "
                   f"{result['data']['synthesis_ms']} ms, playback stopped={stopped['data']['stopped']} "
                   f"(audible output itself is not machine-verifiable)")
        else:
            record("Local TTS (synthesis + playback)", FAIL, result["message"][:140])
    except Exception as exc:
        record("Local TTS (synthesis + playback)", FAIL, f"{type(exc).__name__}: {exc}")


def check_permissions_and_isolation() -> None:
    """Real permission decisions: denial, scoped approval, cross-task reuse."""
    from body_mcp import permissions
    from body_mcp.approvals import approvals

    async def flow():
        await approvals.clear()
        spec = permissions.required_action_spec("hands_click", "consequential", "Delete", None, "task-A")
        await approvals.issue(spec)
        cross = await permissions.authorize("consequential", tool="hands_click", target="Delete",
                                            risk="high", action="x", task_id="task-B")
        right = await permissions.authorize("consequential", tool="hands_click", target="Delete",
                                            risk="high", action="x", task_id="task-A")
        replay = await permissions.authorize("consequential", tool="hands_click", target="Delete",
                                              risk="high", action="x", task_id="task-A")
        await approvals.clear()
        return cross, right, replay

    try:
        cross, right, replay = asyncio.run(flow())
        ok = (cross.allowed is False and right.allowed is True and replay.allowed is False)
        record("Permissions: deny, scoped approval, cross-task + replay refusal",
               PASS_REAL if ok else FAIL,
               f"cross_task_refused={not cross.allowed}, approved_once={right.allowed}, "
               f"replay_refused={not replay.allowed}")
    except Exception as exc:
        record("Permissions: deny, scoped approval, cross-task + replay refusal", FAIL,
               f"{type(exc).__name__}: {exc}")


def check_truthful_outcomes() -> None:
    """Real failure classification and honest states."""
    from body_mcp import server

    async def flow():
        restricted = await server.hands_open(fixture_url("restricted_page.html"))
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        q_ref = next(i["ref"] for i in seen["data"]["inputs"]
                     if i.get("placeholder") == "Search the web")
        typed = await server.hands_type(q_ref, "agents")
        return restricted, typed

    try:
        restricted, typed = asyncio.run(flow())
        ok = (restricted["success"] is False
              and restricted["data"].get("status") in ("needs_user", "blocked")
              and typed["data"]["verification"]["status"] == "CONFIRMED")
        record("Truthful outcomes: restriction stops, typing verified",
               PASS_REAL if ok else FAIL,
               f"restriction_status={restricted['data'].get('status')}, "
               f"type_status={typed['data']['verification']['status']}")
    except Exception as exc:
        record("Truthful outcomes: restriction stops, typing verified", FAIL,
               f"{type(exc).__name__}: {exc}")


def check_event_stream() -> None:
    """Real activity events produced by the executor."""
    from body_mcp import events, server

    async def flow():
        events.bus.clear()
        await server.eyes_see_browser(fixture_url("test_page.html"))
        return events.bus.recent(limit=20)

    try:
        items = asyncio.run(flow())
        types = {item["type"] for item in items}
        ok = "observation" in types
        record("Live activity events", PASS_REAL if ok else FAIL,
               f"event types seen: {sorted(types)}")
    except Exception as exc:
        record("Live activity events", FAIL, f"{type(exc).__name__}: {exc}")


def check_research(public_url: str | None) -> None:
    """Evidence collection with metadata + a public source when allowed."""
    from body_mcp import server

    urls = [fixture_url("test_page.html")]
    if public_url:
        urls.append(public_url)
    try:
        result = asyncio.run(server.research_collect(urls))
        item = result["data"]["items"][0]
        ok = item["status"] == "COLLECTED" and item["title"] and item["collected_at"]
        record("Research evidence collection", PASS_REAL if ok else FAIL,
               f"collected={result['data']['collected']}, blocked={result['data']['blocked']}, "
               f"hash={item['content_hash'][:8]}, method={item['retrieval_method'][:40]}"
               + (f", limitation={item['limitation']}" if item.get("limitation") else ""))
    except Exception as exc:
        record("Research evidence collection", FAIL, f"{type(exc).__name__}: {exc}")


def check_memory() -> None:
    """Local memory: write, search, secret refusal, delete."""
    from body_mcp import memory

    try:
        memory.clear("capability")
        memory.add(title="acceptance note", content="local memory works",
                    scope="capability", verified=True)
        found = memory.search("acceptance note")
        secret = memory.add(title="key", content="api_key = sk-abcdefghijklmnopqrstuvwxyz012345")
        memory.clear("capability")
        ok = bool(found) and secret["success"] is False
        record("Persistent local memory", PASS_REAL if ok else FAIL,
               f"search_hit={bool(found)}, secret_refused={secret['success'] is False}")
    except Exception as exc:
        record("Persistent local memory", FAIL, f"{type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Body-MCP acceptance runner")
    parser.add_argument("--allow-mic", action="store_true",
                        help="record 5 seconds of microphone audio (needs your consent)")
    parser.add_argument("--public-url", default=None,
                        help="one extra public URL for the research check")
    parser.add_argument("--skip-browser", action="store_true",
                        help="skip the checks that launch a browser")
    args = parser.parse_args()

    # the runner works in a THROWAWAY config dir: it never touches your real
    # permissions, consent marker, audit log or memory
    os.environ.setdefault("BODY_MCP_CONFIG_DIR", tempfile.mkdtemp(prefix="body_acceptance_cfg_"))
    os.environ.setdefault("BODY_MCP_BROWSER_MODE", "headless")
    os.environ.setdefault("BODY_MCP_POLITE_DELAY_MS", "0")
    from body_mcp import permissions

    permissions.acknowledge_consent()

    print("Body-MCP acceptance runner")
    print("=" * 70)
    check_mcp_handshake()
    if not args.skip_browser:
        check_managed_browser()
        check_current_browser()
    check_desktop_ocr()
    check_microphone(args.allow_mic)
    check_tts()
    check_permissions_and_isolation()
    check_truthful_outcomes()
    check_event_stream()
    check_research(args.public_url)
    check_memory()

    counts: dict[str, int] = {}
    for item in RESULTS:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    print("=" * 70)
    print(", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    failures = counts.get(FAIL, 0)
    print("no result here means 'not proven' - see the detail column")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
