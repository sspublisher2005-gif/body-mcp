"""Demonstration learning, role contracts, skills and the fallback chain."""
import asyncio
import os

from body_mcp import demo, roles, server, skills, sources


def test_demo_pipeline_builds_steps_from_frames():
    frames = [{"index": 0, "path": "a.png", "at_s": 0.0},
              {"index": 1, "path": "b.png", "at_s": 3.0},
              {"index": 2, "path": "c.png", "at_s": 6.0}]
    texts = ["Home\nFeed\nPost", "Home\nFeed\nPost", "Home\nFeed\nNew Post\nPublish"]
    steps = demo.steps_from_frames(frames, texts)
    assert len(steps) == 2, "an unchanged frame is not a new step"
    assert steps[1]["controls"], "visible buttons should be noticed"
    assert "Publish" in steps[1]["controls"]


def test_demo_questions_ask_the_essentials():
    steps = [{"at_s": 0, "screen": "x", "controls": [], "text_seen": "", "kind": "observed"}]
    questions = demo.questions_from_steps(steps)
    blob = " ".join(questions).lower()
    assert "exact workflow" in blob
    assert "publish" in blob or "approval" in blob
    assert len(questions) >= 3


def test_demo_reports_a_missing_file_honestly():
    result = demo.learn(os.path.join("nope", "missing.mp4"))
    assert result["success"] is False
    assert result["status"] == "BLOCKED"


def test_demo_blocks_without_an_ocr_engine(monkeypatch, tmp_path):
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"not a real video")
    monkeypatch.setattr(demo, "extract_frames", lambda path, max_frames=60, interval_s=3.0: {
        "ok": True, "tool": "ffmpeg",
        "frames": [{"index": 0, "path": str(video), "at_s": 0.0}], "reason": ""})
    monkeypatch.setattr(demo, "read_frame_text",
                        lambda path, language="eng": {"ok": False, "text": "",
                                                     "reason": "no OCR engine"})
    result = demo.learn(str(video))
    assert result["success"] is False
    assert result["stage"] == "ocr"
    assert "Tesseract" in result["next"]


def test_skill_save_and_list():
    from body_mcp import memory

    memory.clear("workflow")
    saved = skills.save(name="daily post", goal="post a reel", verified=False,
                        steps=[{"type": "click", "target": "Publish"}],
                        why="the user showed the flow")
    assert saved["success"] is True
    listing = skills.list_skills()
    assert listing and listing[0]["title"].startswith("skill:")
    assert listing[0]["steps"]
    memory.clear("workflow")


def test_unverified_skill_is_not_replayed():
    from body_mcp import memory

    memory.clear("workflow")
    saved = skills.save(name="draft flow", goal="x", verified=False,
                        steps=[{"type": "click", "target": "Publish"}])
    result = asyncio.run(skills.replay(saved["data"]["id"]))
    assert result["success"] is False
    assert "never verified" in result["message"]
    memory.clear("workflow")


def test_role_contract_has_a_budget_and_produces():
    opened = roles.start("research", "find the best tools", budget={"max_actions": 5,
                                                                  "max_seconds": 60})
    assert opened["success"] is True
    assert opened["data"]["tools"]
    snapshot = roles.status(opened["data"]["role_id"])
    assert snapshot["data"]["budget"]["max_actions"] == 5
    closed = roles.finish(opened["data"]["role_id"], evidence="3 sources cited", verified=True)
    assert closed["success"] is True
    assert closed["data"]["state"] == "verified"


def test_unknown_role_is_refused():
    assert roles.start("wizard", "x")["success"] is False


def test_emergency_stop_closes_contracts():
    opened = roles.start("execution", "click things")
    stopped = roles.stop_all("test")
    assert stopped["success"] is True
    assert roles.status(opened["data"]["role_id"])["data"]["state"] == "cancelled"


def test_source_fallback_chain_tries_the_next_source(monkeypatch):
    def fake_search(source, query, limit=8):
        if source == "hackernews":
            return {"success": False, "items": [], "reason": "HTTP 403", "count": 0}
        return {"success": True, "items": [{"title": "t", "source": source}],
                "reason": "", "count": 1}

    monkeypatch.setattr(sources, "search", fake_search)
    monkeypatch.setattr(sources, "BROWSER_FALLBACKS", {})
    result = sources.search_any("agents", limit=2)
    assert result["success"] is True
    assert result["source"] != "hackernews"
    assert [entry["source"] for entry in result["tried"]][0] == "hackernews"


def test_fallback_chain_reports_everything_it_tried(monkeypatch):
    def fake_search(source, query, limit=8):
        return {"success": False, "items": [], "reason": "HTTP 403", "count": 0}

    monkeypatch.setattr(sources, "search", fake_search)
    monkeypatch.setattr(sources, "BROWSER_FALLBACKS", {})
    result = sources.search_any("agents", limit=2)
    assert result["success"] is False
    assert len(result["tried"]) >= 3
    assert "HTTP 403" in result["reason"]


def test_new_tools_are_exposed():
    async def names():
        from mcp.server.mcpserver.server import MCPServer

        tools = await MCPServer.list_tools(server.mcp)  # full registry, not the focus view
        return [tool.name for tool in tools]

    listed = asyncio.run(names())
    for tool in ("demo_learn", "body_roles", "body_role_start", "body_role_finish",
                 "body_stop_all", "body_skill_save", "body_skill_list", "body_skill_replay",
                 "research_any"):
        assert tool in listed, tool
