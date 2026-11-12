"""REAL current-browser acceptance test (opt-in).

Runs against a REAL Chrome/Edge started with --remote-debugging-port on loopback
and a disposable profile. Nothing is mocked: the browser is a real process, the
CDP connection is real, and the page is a local fixture file.

Enable with:  BODY_MCP_REAL_CDP=1 pytest tests/test_attach_real.py -v
(or run the module directly: python tests/test_attach_real.py)

The approval inside this test stands in for the human clicking "yes" in
reflex_ask(); the approval scoping, binding and single-use behaviour are the
production code paths.
"""
import asyncio
import contextlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from body_mcp import attach, browser, permissions, server  # noqa: E402
from body_mcp.approvals import approvals  # noqa: E402

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]

def _find_browser() -> str | None:
    for path in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                 r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if os.path.isfile(path):
            return path
    return None


# These run against the real browser. They are skipped only when no browser is
# installed (or when BODY_MCP_REAL_CDP=0 is set explicitly).
pytestmark = pytest.mark.skipif(
    _find_browser() is None or os.environ.get("BODY_MCP_REAL_CDP") == "0",
    reason="real-browser acceptance test - needs Chrome or Edge installed")


def _find_browser() -> str | None:
    for path in CHROME_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def _free_port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cdp_ready(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


@pytest.fixture(scope="module")
def real_browser():
    exe = _find_browser()
    if not exe:
        pytest.skip("no Chrome/Edge executable found in standard locations")
    port = _free_port()
    profile = tempfile.mkdtemp(prefix="body_mcp_cdp_profile_")
    fixture = os.path.join(os.path.dirname(__file__), "fixtures", "test_page.html")
    url = "file:///" + os.path.abspath(fixture).replace("\\", "/")
    headed = os.environ.get("BODY_MCP_REAL_CDP_HEADED") == "1"
    argv = [exe, f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check", "--disable-gpu"]
    if not headed:
        argv.append("--headless=new")
    argv.append(url)
    proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not _cdp_ready(port):
        proc.terminate()
        pytest.skip("browser did not expose a CDP endpoint in time")
    yield {"exe": exe, "port": port, "proc": proc, "profile": profile}
    with contextlib.suppress(Exception):
        proc.terminate()
        proc.wait(timeout=10)


def test_real_cdp_attach_select_act_verify_detach(real_browser):
    port = real_browser["port"]
    endpoint = f"http://127.0.0.1:{port}"

    async def flow():
        await approvals.clear()
        # the human's "yes" for the attach action
        await approvals.issue(permissions.required_action_spec(
            "attach_browser", "chrome_attach", f"cdp:{endpoint}", None, None))

        attached = await attach.attach(endpoint)
        assert attached["success"] is True, attached
        tabs = attached["data"]["tabs"]
        assert len(tabs) >= 1
        assert any("test_page.html" in t["url"] for t in tabs), tabs

        # selecting the tab needs its own approval
        await approvals.issue(permissions.required_action_spec(
            "select_tab", "chrome_attach", "tab:0", None, None))
        selected = await attach.select_tab("0")
        assert selected["success"] is True, selected

        # hands/eyes must now act on the ATTACHED tab, not on a managed browser
        seen = await server.eyes_see_browser()
        assert seen["success"] is True, seen
        assert "test_page.html" in seen["data"]["url"]
        q_ref = next(i["ref"] for i in seen["data"]["inputs"]
                     if i.get("placeholder") == "Search the web")
        typed = await server.hands_type(q_ref, "agents")
        assert typed["success"] is True, typed
        assert typed["data"]["verification"]["status"] == "CONFIRMED"
        search_ref = next(b["ref"] for b in seen["data"]["buttons"]
                          if b["text"] == "Search")
        clicked = await server.hands_click(search_ref)
        assert clicked["success"] is True, clicked
        verified = await server.reflex_verify("Result A about agents")
        assert verified["found"] is True, verified

        # detach closes OUR connection only
        detached = await attach.detach()
        assert detached["success"] is True, detached
        assert attach.current_page() is None
        # the real browser is still running
        assert real_browser["proc"].poll() is None
        await approvals.clear()

    asyncio.run(flow())


def test_real_cdp_detach_clears_refs(real_browser):
    port = real_browser["port"]
    endpoint = f"http://127.0.0.1:{port}"

    async def flow():
        await approvals.clear()
        await approvals.issue(permissions.required_action_spec(
            "attach_browser", "chrome_attach", f"cdp:{endpoint}", None, None))
        await attach.attach(endpoint)
        await approvals.issue(permissions.required_action_spec(
            "select_tab", "chrome_attach", "tab:0", None, None))
        await attach.select_tab("0")
        await server.eyes_see_browser()
        assert browser.REF_MAP, "expected refs from the attached tab"
        await attach.detach()
        assert not browser.REF_MAP, "refs must not survive a detach"
        await approvals.clear()

    asyncio.run(flow())


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-s"]))
