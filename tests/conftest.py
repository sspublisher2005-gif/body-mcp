import asyncio
import contextlib
import json
import os
import tempfile
import threading

import pytest

os.environ.setdefault("BODY_MCP_BROWSER_MODE", "headless")
os.environ.setdefault("BODY_MCP_POLITE_DELAY_MS", "0")

# Isolated permission/consent/audit dir for the whole suite; consent acknowledged
# so high-risk flows reach the per-action approval gate. Permission tests override
# this explicitly with monkeypatch.
_CFG = tempfile.mkdtemp(prefix="body_mcp_test_cfg_")
os.environ["BODY_MCP_CONFIG_DIR"] = _CFG

from body_mcp import attach, browser, permissions, restrictions  # noqa: E402
from body_mcp.approvals import approvals  # noqa: E402

permissions.acknowledge_consent()

# The suite deliberately uses Body-MCP's managed Chromium in headless CI (no
# human browser to connect). Real users keep the default 'allow' =
# own-browser-only, so the body never opens a test browser for them.
_test_profile = permissions.load_profile()
_test_profile["capabilities"]["own_browser_only"] = "deny"
# mic now defaults to 'ask' (consent per recording); the suite grants it so the
# mocked-microphone tests can exercise the real code path.
_test_profile["capabilities"]["mic"] = "allow"
with open(os.path.join(_CFG, "permissions.json"), "w", encoding="utf-8") as _f:
    json.dump(_test_profile, _f, indent=2)


def _clear_cooldowns():
    restrictions._cap_cooldowns.clear()


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture_url(name: str) -> str:
    return "file:///" + os.path.join(FIXTURES, name).replace("\\", "/")


@pytest.fixture(autouse=True, scope="session")
def _shared_event_loop():
    """One event loop for the whole session.

    Playwright's driver process belongs to the loop that created it. With one loop
    per test the driver stayed unclosed when that loop died (the "unclosed transport"
    warnings) and Chromium was relaunched for every single test. One loop means:
    one browser, closed properly, and a much faster suite.
    """
    original_run = asyncio.run
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main_thread = threading.current_thread()

    def shared_run(coro, *, debug=None):
        # a background thread must run its OWN loop (Body-MCP's background tasks do)
        if threading.current_thread() is not main_thread:
            return original_run(coro, debug=debug)
        return loop.run_until_complete(coro)

    asyncio.run = shared_run
    try:
        yield loop
    finally:
        asyncio.run = original_run
        with contextlib.suppress(Exception):
            loop.run_until_complete(browser.shutdown_browser())
        with contextlib.suppress(Exception):
            loop.close()
        asyncio.set_event_loop(None)


@pytest.fixture(autouse=True)
def reset_browser_state():
    browser.REF_MAP.clear()
    _clear_cooldowns()
    with contextlib.suppress(Exception):
        asyncio.run(approvals.clear())
    with contextlib.suppress(Exception):
        asyncio.run(attach._disconnect(silent=True))
    yield
    browser.REF_MAP.clear()
    _clear_cooldowns()
    with contextlib.suppress(Exception):
        asyncio.run(approvals.clear())
