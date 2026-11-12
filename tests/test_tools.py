"""Tool registration, browser behavior against fixtures, mocked ears/desktop eyes.

NOTE: each test drives ALL its tool calls inside ONE asyncio.run(...), because the
MCP server is a single event loop that owns one shared browser page. Splitting a
flow across multiple asyncio.run calls would relaunch a blank browser mid-test.
"""
import asyncio
import os

import numpy as np

from body_mcp import browser, ears, eyes, reflex, server


def fixture_url(name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "fixtures", name)
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def expected_tools():
    return {
        "eyes_see_desktop", "eyes_see_browser", "ears_listen",
        "hands_open", "hands_click", "hands_type", "hands_press", "hands_scroll",
        "hands_batch", "hands_parallel",
        "legs_open_app",
        "attach_browser", "list_tabs", "select_tab", "detach_browser",
        "body_events", "body_cancel",
        "memory_search", "memory_write", "memory_list", "memory_delete", "memory_export",
        "body_profile", "body_models", "body_recommend", "research_collect",
        "body_speak", "body_stop_speaking", "body_voice_engines", "body_windows",
        "browser_bridge", "body_open_external", "research_video",
        "desktop_inspect", "desktop_click", "desktop_type", "desktop_read_value",
        "research_youtube_search",
        "research_sources", "research_source", "reflex_interview",
        "body_task_start", "body_task_status", "body_task_cancel",
        "body_undo", "body_undo_list",
        "demo_learn", "body_roles", "body_role_start", "body_role_finish", "body_stop_all",
        "body_skill_save", "body_skill_list", "body_skill_replay", "research_any",
        "body_similarity_check",
        "body_workflow_start", "body_workflow_note", "body_workflow_report", "body_lessons",
        "desktop_watch_start", "desktop_watch_read", "desktop_watch_stop", "desktop_monitors",
        "privacy_session_start", "privacy_session_open", "privacy_session_snapshot",
        "privacy_session_end", "memory_note",
        "body_console_start", "body_console_stop",
        "reflex_verify", "reflex_ask", "body_status",
    }


def ref_by_text(buttons, text):
    return next(b["ref"] for b in buttons if text.lower() in b["text"].lower())


def ref_by_placeholder(inputs, placeholder):
    return next(i["ref"] for i in inputs if i.get("placeholder") == placeholder)


def test_all_tools_registered():
    from mcp import Client

    async def run():
        async with Client(server.mcp, raise_exceptions=True) as client:
            tools = await client.list_tools()
            return {t.name for t in tools.tools}

    assert asyncio.run(run()) == expected_tools()


def test_body_status_reports_capabilities():
    result = asyncio.run(server.body_status())
    assert result["success"] is True
    data = result["data"]
    assert data["server"]["tools_registered"] == len(expected_tools())
    assert data["safety"]["mode"] == "strict"
    assert data["batch"]["supported"] is True
    assert data["parallel"]["supported"] is True
    assert "permissions" in data
    assert data["ears"]["verified"] is False


def test_browser_eyes_reads_fixture_page():
    async def flow():
        result = await server.eyes_see_browser(fixture_url("test_page.html"))
        assert result["success"] is True
        data = result["data"]
        assert data["title"] == "Body-MCP Test Page"
        assert data["headings"][0]["text"] == "Body-MCP Search"
        texts = [b["text"] for b in data["buttons"]]
        assert "Search" in texts
        by_placeholder = {i["placeholder"]: i for i in data["inputs"]}
        assert by_placeholder["Password"]["sensitive"] is True
        assert by_placeholder["Password"]["value"] == "***"
        assert data["restricted"] is False
        assert browser.REF_MAP

    asyncio.run(flow())


def test_browser_search_flow_click_and_verify():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        data = seen["data"]
        q_ref = ref_by_placeholder(data["inputs"], "Search the web")
        search_ref = ref_by_text(data["buttons"], "Search")
        typed = await server.hands_type(q_ref, "agents")
        assert typed["success"] is True
        clicked = await server.hands_click(search_ref)
        assert clicked["success"] is True
        verified = await server.reflex_verify("Result A about agents")
        assert verified["found"] is True
        assert verified["data"]["evidence"]

    asyncio.run(flow())


def test_hands_type_into_password_field_refused():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        pw_ref = ref_by_placeholder(seen["data"]["inputs"], "Password")
        refused = await server.hands_type(pw_ref, "hunter2")
        assert refused["success"] is False
        assert "sensitive" in refused["message"].lower()

    asyncio.run(flow())


def test_dangerous_click_requires_scoped_approval():
    async def flow():

        from body_mcp import permissions as _perms
        from body_mcp.approvals import approvals as _approvals

        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        delete_ref = ref_by_text(seen["data"]["buttons"], "Delete")
        url = seen["data"]["url"]
        refused = await server.hands_click(delete_ref)
        assert refused["success"] is False

        # user approves EXACTLY the action (as reflex_ask would issue it)
        spec = _perms.required_action_spec("hands_click", "consequential",
                                           "Delete everything", url, None)
        await _approvals.issue(spec)
        clicked = await server.hands_click(delete_ref)
        assert clicked["success"] is True
        # one approval = one click: a second identical click needs a fresh approval
        # (and is refused — proof the token was consumed)
        again = await server.hands_click(delete_ref)
        assert again["success"] is False

    asyncio.run(flow())


def test_safe_button_click_needs_no_approval():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        save_ref = ref_by_text(seen["data"]["buttons"], "Save")
        clicked = await server.hands_click(save_ref)
        assert clicked["success"] is True
        verified = await server.reflex_verify("Saved")
        assert verified["found"] is True

    asyncio.run(flow())


def test_navigation_between_fixture_pages():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        article_ref = next(lk["ref"] for lk in seen["data"]["links"] if "article" in lk["text"].lower())
        clicked = await server.hands_click(article_ref)
        assert clicked["success"] is True
        verified = await server.reflex_verify("computer-use agents")
        assert verified["found"] is True

    asyncio.run(flow())


def test_restricted_page_stops_automation():
    async def flow():
        opened = await server.hands_open(fixture_url("restricted_page.html"))
        assert opened["success"] is False
        assert "manually" in opened["message"].lower()
        seen = await server.eyes_see_browser(fixture_url("restricted_page.html"))
        assert seen["data"]["restricted"] is True
        assert seen["message"].startswith("STOP")
        clicked = await server.hands_click("Search")
        assert clicked["success"] is False

    asyncio.run(flow())


def test_eyes_see_browser_without_page_reports_url_needed():
    async def flow():
        # close whatever page a previous test left open: the "no page" path must be
        # exercised on its own terms
        from body_mcp import browser

        page = await browser.ensure_page()
        await page.close()
        return await server.eyes_see_browser()

    result = asyncio.run(flow())
    assert result["success"] is False
    assert "url" in result["message"].lower()


def test_eyes_see_browser_refuses_embedded_credentials():
    result = asyncio.run(server.eyes_see_browser("https://user:pass@example.com/"))
    assert result["success"] is False
    assert "credentials" in result["message"].lower()


def test_reflex_verify_empty_expected():
    result = asyncio.run(server.reflex_verify(""))
    assert result["success"] is False


def test_ears_listen_with_mocked_mic_and_whisper(monkeypatch):
    # a silent buffer would (correctly) be rejected as "no speech" - use noise
    noise = np.random.default_rng(3).normal(0, 0.2, 16000).astype(np.float32)
    monkeypatch.setattr(ears, "record_speech",
                        lambda max_seconds=15, silence_ms=700: (
                            noise, {"started": True, "ended_by": "silence", "seconds": 1.0}))
    monkeypatch.setattr(ears, "transcribe", lambda audio, model_size=None:
                        {"model": "fake", "language": "en", "text": "hello world", "segments": []})
    result = asyncio.run(server.ears_listen(1))
    assert result["success"] is True
    assert result["data"]["transcript"] == "hello world"


def test_ears_listen_mic_failure_is_graceful(monkeypatch):
    def boom(max_seconds=15, silence_ms=700):
        raise RuntimeError("no input device")

    monkeypatch.setattr(ears, "record_speech", boom)
    result = asyncio.run(server.ears_listen(1))
    assert result["success"] is False
    assert "no input device" in result["message"]


def test_desktop_eyes_without_tesseract_is_helpful(monkeypatch):

    monkeypatch.setattr(eyes, "capture_png",
                        lambda monitor=1, region=None: {"ok": True, "png": b"fake-png",
                                                        "bytes": 8, "region": {}})
    monkeypatch.setattr(eyes, "get_provider",
                        lambda name=None: (None, {"available": False,
                                                  "reason": "the Tesseract OCR binary was not found",
                                                  "install": "winget install -e --id UB-Mannheim.TesseractOCR"}))
    result = eyes.see_desktop()
    assert result["success"] is False
    assert "winget" in result["message"] + str(result["data"])


def test_desktop_eyes_with_mocked_ocr(monkeypatch):
    from body_mcp.ocr.base import OcrResult

    class FakeProvider:
        name = "tesseract"

        def available(self):
            return {"provider": "tesseract", "available": True, "path": "fake",
                    "languages": ["eng"], "reason": None}

        def recognize(self, png_bytes, language="eng"):
            return OcrResult(text="Invoice due tomorrow. Sign in required.",
                              provider="tesseract", language=language, duration_ms=5)

    monkeypatch.setattr(eyes, "capture_png",
                        lambda monitor=1, region=None: {"ok": True, "png": b"fake-png",
                                                        "bytes": 8, "region": {}})
    monkeypatch.setattr(eyes, "get_provider", lambda name=None: (FakeProvider(), {"available": True}))
    result = eyes.see_desktop()
    assert result["success"] is True
    assert "Invoice due tomorrow" in result["data"]["text"]
    assert result["data"]["safety"]["mode"] == "sensitive"


def test_reflex_ask_messagebox_fallback_approved(monkeypatch):
    monkeypatch.setattr(reflex, "_ask_via_messagebox", lambda question: True)
    result = asyncio.run(reflex.ask("Delete the fixture?", None))
    assert result["approved"] is True
    # a plain question issues no scoped approval
    assert result["data"]["scoped_approval"] is False


def test_reflex_ask_with_action_issues_scoped_approval(monkeypatch):
    import json as _json

    from body_mcp.approvals import approvals

    monkeypatch.setattr(reflex, "_ask_via_messagebox", lambda question: True)
    spec = {"tool": "hands_click", "capability": "consequential",
            "target": "Delete everything", "url": "https://x.test/a?token=secret",
            "task_id": "task-1"}

    async def flow():
        await approvals.clear()
        result = await reflex.ask("Delete the fixture?", None,
                                  action=_json.dumps(spec))
        assert result["approved"] is True
        assert result["data"]["scoped_approval"] is True
        # the issued approval matches exactly (query stripped, task bound)
        assert await approvals.peek(spec) is True
        # and not a different task
        other = dict(spec, task_id="task-2")
        assert await approvals.peek(other) is False
        await approvals.clear()

    asyncio.run(flow())


def test_reflex_ask_messagebox_fallback_denied(monkeypatch):
    monkeypatch.setattr(reflex, "_ask_via_messagebox", lambda question: False)
    result = asyncio.run(reflex.ask("Delete the fixture?", None))
    assert result["approved"] is False
    assert result["data"]["scoped_approval"] is False


def test_tool_return_shape(monkeypatch):
    """Every tool returns a dict with success/message/data."""
    monkeypatch.setattr(ears, "record_mic", lambda s: np.zeros(1600, dtype=np.float32))
    # the VAD recorder must be mocked too - a test must never open the real microphone
    monkeypatch.setattr(ears, "record_speech",
                        lambda max_seconds=15, silence_ms=700: (
                            np.zeros(1600, dtype=np.float32),
                            {"started": True, "ended_by": "silence", "seconds": 0.1}))
    monkeypatch.setattr(ears, "transcribe", lambda a, m=None:
                        {"model": "fake", "language": "en", "text": "ok", "segments": []})
    monkeypatch.setattr(eyes, "capture_png",
                        lambda monitor=1, region=None: {"ok": True, "png": b"png",
                                                        "bytes": 3, "region": {}})
    monkeypatch.setattr(eyes, "get_provider",
                        lambda name=None: (None, {"available": False, "reason": "no engine"}))
    monkeypatch.setattr(reflex, "_ask_via_messagebox", lambda q: False)

    class FakeCtx:
        async def elicit(self, message, schema):
            raise RuntimeError("client has no elicitation support")

    async def call_all():
        results = {}
        fixture = fixture_url("test_page.html")
        results["eyes_see_browser"] = await server.eyes_see_browser(fixture)
        results["hands_scroll"] = await server.hands_scroll("down", 1)
        results["hands_open"] = await server.hands_open(fixture)
        results["eyes_see_browser_2"] = await server.eyes_see_browser(fixture)
        q_ref = ref_by_placeholder(results["eyes_see_browser_2"]["data"]["inputs"], "Search the web")
        results["hands_type"] = await server.hands_type(q_ref, "x")
        search_ref = ref_by_text(results["eyes_see_browser_2"]["data"]["buttons"], "Search")
        results["hands_click"] = await server.hands_click(search_ref)
        results["hands_press"] = await server.hands_press("Tab")
        results["reflex_verify"] = await server.reflex_verify("Body-MCP")
        results["reflex_ask"] = await server.reflex_ask("Approve?", FakeCtx())
        results["body_status"] = await server.body_status()
        results["ears_listen"] = await server.ears_listen(1)
        results["eyes_see_desktop"] = await server.eyes_see_desktop()
        return results

    results = asyncio.run(call_all())
    # all 11 distinct tool entry points plus one extra eyes_see_browser refresh
    assert len(results) == 12
    for name, result in results.items():
        assert isinstance(result, dict), name
        for key in ("success", "message", "data"):
            assert key in result, f"{name} missing {key}"
