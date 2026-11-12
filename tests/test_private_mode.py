"""Private mode: preflight, the assistant tab, and the honest warnings."""
import asyncio
import os

from body_mcp import local_worker, privacy, server


def test_preflight_reports_what_is_installed_and_running():
    result = privacy.preflight()
    assert result["ok"] is True
    assert "browsers" in result and "vpn" in result
    assert isinstance(result["warnings"], list)
    assert result["not_anonymous"]


def test_preflight_warns_when_the_local_model_is_not_configured(monkeypatch):
    monkeypatch.delenv("BODY_MCP_LOCAL_MODEL", raising=False)
    result = privacy.preflight()
    assert result["local_model"]["configured"] is False
    assert any("reasoning model" in warning.lower() for warning in result["warnings"])


def test_preflight_accepts_a_configured_local_model(monkeypatch, tmp_path):
    model = tmp_path / "model.gguf"
    model.write_bytes(b"GGUF")
    monkeypatch.setenv("BODY_MCP_LOCAL_MODEL", str(model))
    result = privacy.preflight()
    assert result["local_model"]["configured"] is True
    assert not any("reasoning model" in warning.lower() for warning in result["warnings"])


def test_preflight_warns_when_brave_is_missing(monkeypatch):
    monkeypatch.setattr(privacy, "_browser_executable", lambda name: None)
    result = privacy.preflight()
    assert any("brave" in warning.lower() for warning in result["warnings"])


def test_exit_ip_is_not_fetched_by_default():
    result = privacy.preflight()
    assert "not checked" in result["exit_ip"]


def test_private_mode_needs_an_installed_browser(monkeypatch):
    monkeypatch.setattr(privacy, "_browser_executable", lambda name: None)
    result = privacy.start(mode="private", browser="brave")
    assert result["success"] is False
    assert "brave" in result["message"].lower()


def test_private_mode_records_the_requested_posture():
    result = privacy.start(label="private run", mode="private", browser="chromium",
                           vpn=True, assistant=True)
    assert result["success"] is True
    data = result["data"]
    assert data["mode"] == "private"
    assert data["assistant_url"].startswith("https://venice.ai")
    assert data["warnings"]
    privacy._sessions.clear()


def test_standard_mode_works_without_a_browser_install():
    result = privacy.start(label="plain")
    assert result["success"] is True
    assert result["data"]["mode"] == "standard"
    privacy._sessions.clear()


def test_preflight_reports_the_content_policy(monkeypatch):
    monkeypatch.setattr(local_worker, "status",
                        lambda: {"available": False, "ollama_installed": False,
                                 "ollama_models": [], "gguf": None, "selected": None,
                                 "note": "n/a", "ollama_reachable": False,
                                 "ollama_url": None})
    result = privacy.preflight()
    policy = result["content_policy"]
    assert policy["browsing"].startswith("local")
    assert policy["content_local_possible"] is False
    assert any("NO LOCAL MODEL" in warning for warning in result["warnings"])


def test_a_session_can_keep_the_page_content_local(monkeypatch):
    started = privacy.start(label="local content", keep_content_local=True)
    assert started["success"] is True
    assert started["data"]["keep_content_local"] is True
    privacy._sessions.clear()


def test_the_content_is_withheld_when_no_local_model_exists(monkeypatch):
    monkeypatch.setattr(local_worker, "status",
                        lambda: {"available": False, "ollama_installed": False,
                                 "ollama_models": [], "gguf": None, "selected": None,
                                 "note": "n/a", "ollama_reachable": False,
                                 "ollama_url": None})

    async def flow():
        started = privacy.start(label="withheld", keep_content_local=True)
        session_id = started["data"]["session_id"]
        opened = await privacy.open(session_id, "file:///" + os.path.abspath(
            os.path.join(os.path.dirname(__file__), "fixtures", "test_page.html")
        ).replace("\\", "/"))
        assert opened["success"] is True
        snap = await privacy.snapshot(session_id)
        assert snap["success"] is False
        assert snap["data"]["withheld"] is True
        assert "text" not in snap["data"] or snap["data"]["text"] is None
        await privacy.end(session_id)

    asyncio.run(flow())


def test_the_content_is_redacted_locally_when_a_worker_exists(monkeypatch):
    monkeypatch.setattr(local_worker, "status",
                        lambda: {"available": True, "ollama_installed": True,
                                 "ollama_models": [{"name": "qwen3:0.6b"}], "gguf": None,
                                 "selected": "qwen3:0.6b", "note": "n/a",
                                 "ollama_reachable": True, "ollama_url": "http://127.0.0.1:11434"})
    monkeypatch.setattr(local_worker, "run",
                        lambda task, text: {"ok": True, "text": f"[{task}] {text[:20]}",
                                             "model": "qwen3:0.6b", "runtime": "ollama",
                                             "duration_ms": 1})

    async def flow():
        started = privacy.start(label="local", keep_content_local=True)
        session_id = started["data"]["session_id"]
        await privacy.open(session_id, "file:///" + os.path.abspath(
            os.path.join(os.path.dirname(__file__), "fixtures", "test_page.html")
        ).replace("\\", "/"))
        snap = await privacy.snapshot(session_id)
        assert snap["success"] is True, snap
        assert snap["data"]["text"] is None, "the raw text must not be returned"
        assert snap["data"]["content_local"] is True
        assert snap["data"]["summary"].startswith("[summarise]")
        await privacy.end(session_id)

    asyncio.run(flow())


def test_preflight_tool_is_exposed():
    async def names():
        tools = await server.mcp.list_tools()
        return [tool.name for tool in tools]

    assert "body_privacy_preflight" in asyncio.run(names())


def test_session_open_and_close_roundtrip():
    async def flow():
        started = privacy.start(label="roundtrip")
        session_id = started["data"]["session_id"]
        opened = await privacy.open(session_id, "file:///" + os.path.abspath(
            os.path.join(os.path.dirname(__file__), "fixtures", "test_page.html")).replace("\\", "/"))
        assert opened["success"] is True, opened
        snap = await privacy.snapshot(session_id)
        assert snap["success"] is True
        assert snap["data"]["text"]
        ended = await privacy.end(session_id)
        assert ended["success"] is True
        assert ended["data"]["cleanup_verified"] is True
        assert privacy.get(session_id) is None

    asyncio.run(flow())
