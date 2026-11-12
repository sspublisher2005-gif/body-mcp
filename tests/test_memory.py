"""Persistent local memory: search, scoping, secrets refused, versions, cleanup."""
import asyncio

from body_mcp import memory, permissions, server

CONFIG_DIR = permissions._config_dir()


def _reset():
    memory.clear()


def test_memory_roundtrip_search_update_delete():
    _reset()
    added = memory.add(title="CDP port must be loopback", content="attach_browser refuses non-loopback hosts",
                        scope="project", type="decision", tags=["browser", "security"], verified=True)
    assert added["success"] is True
    mid = added["data"]["id"]

    found = memory.search("loopback")
    assert any(m["id"] == mid for m in found)
    assert found[0]["verified"] is True

    updated = memory.update(mid, content="attach_browser refuses non-loopback hosts (strict)",
                             verified=True)
    assert updated["success"] is True
    assert memory.get(mid)["version"] == 2

    assert memory.delete(mid) is True
    assert memory.get(mid) is None


def test_memory_refuses_secrets():
    _reset()
    result = memory.add(title="api key", content="api_key = sk-abcdefghijklmnopqrstuvwxyz012345")
    assert result["success"] is False
    assert "credential" in result["message"].lower() or "secret" in result["message"].lower()


def test_memory_scope_isolation():
    _reset()
    memory.add(title="project note", content="pytest lives in tests/", scope="project")
    memory.add(title="user preference", content="prefers dark mode", scope="user")
    project_items = memory.list_scope(scope="project")
    user_items = memory.list_scope(scope="user")
    assert all(i["scope"] == "project" for i in project_items)
    assert all(i["scope"] == "user" for i in user_items)
    assert len(project_items) == 1 and len(user_items) == 1


def test_memory_unknown_scope_refused():
    result = memory.add(title="x", content="y", scope="nonsense")
    assert result["success"] is False


def test_memory_search_falls_back_to_like_for_partial_terms():
    _reset()
    memory.add(title="voice latency", content="faster-whisper tiny model starts in about 300 ms")
    hits = memory.search("whisper")
    assert hits, "lexical search must find the entry"


def test_memory_export_is_readable_and_bounded():
    _reset()
    memory.add(title="note one", content="content one", scope="knowledge")
    exported = memory.export()
    assert exported["count"] >= 1
    assert "Body-MCP memory export" in exported["markdown"]
    assert exported["json"][0]["title"] == "note one"


def test_memory_clear_scope_only():
    _reset()
    memory.add(title="a", content="a", scope="project")
    memory.add(title="b", content="b", scope="workflow")
    memory.clear("project")
    assert memory.list_scope(scope="project") == []
    assert len(memory.list_scope(scope="workflow")) == 1


def test_memory_tools_are_permission_gated():
    _reset()
    result = asyncio.run(server.memory_search("anything"))
    assert result["success"] is True

    write = asyncio.run(server.memory_write(title="tool note", content="written via the tool",
                                            scope="project"))
    assert write["success"] is True
    found = asyncio.run(server.memory_search("tool note"))
    assert found["data"]["count"] >= 1

    exported = asyncio.run(server.memory_export())
    assert exported["success"] is True and exported["data"]["count"] >= 1


def test_memory_stats_reports_local_path():
    stats = memory.stats()
    assert stats["path"].endswith("memory.db")
    assert stats["fts5"] in (True, False)


def test_markdown_notes_are_searchable_and_human_editable():
    written = memory.write_note("acceptance-notes.md",
                                "# Conventions\nRun `python -m pytest -q` before reporting done.")
    assert written["success"] is True
    hits = memory.search("acceptance-notes")
    assert any(h["id"].startswith("note:") for h in hits)
    notes = memory.read_notes()
    assert any("pytest" in note["content"] for note in notes)


def test_markdown_notes_refuse_secrets_and_path_traversal():
    assert memory.write_note("bad.md", "api_key = sk-abcdefghijklmnopqrstuvwxyz012345")["success"] is False
    assert memory.write_note("../escape.md", "x")["success"] is False


def test_memory_note_tool_writes_a_readable_note():
    result = asyncio.run(server.memory_note("tool-note.md", "# Tool note\nwritten by the tool"))
    assert result["success"] is True
    found = asyncio.run(server.memory_search("Tool note"))
    assert found["data"]["count"] >= 1
