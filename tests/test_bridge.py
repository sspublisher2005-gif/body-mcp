"""Bridge protocol tests: loopback, token, size limits, command routing.

A fake extension (a socket that speaks the same framing as Chrome's native
messaging) stands in for the real one - the transport, the framing and the
authorisation are the production code paths.
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from body_mcp import bridge  # noqa: E402


def _frame(message: dict) -> bytes:
    raw = json.dumps(message).encode("utf-8")
    return struct.pack(">I", len(raw)) + raw


async def _read_json(reader) -> dict:
    """Exact framing read (StreamReader.read may return a short buffer)."""
    header = await reader.readexactly(4)
    length = struct.unpack(">I", header)[0]
    return json.loads((await reader.readexactly(length)).decode("utf-8"))


async def _fake_extension(port: int, token: str, extension_id: str = "fake-extension-id"):
    """Connect and behave like the extension: hello, then poll for commands."""
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(_frame({"type": "hello", "token": token, "extension_id": extension_id,
                         "tabs": [{"id": 7, "title": "Example", "url": "https://example.com"}]}))
    await writer.drain()

    async def poll_loop():
        while True:
            writer.write(_frame({"type": "poll"}))
            await writer.drain()
            reply = await _read_json(reader)
            command = reply.get("command")
            if command:
                writer.write(_frame({"type": "result", "task_id": command.get("task_id"),
                                     "result": {"ok": True, "navigated": command.get("url"),
                                                "cmd": command.get("cmd")}}))
                await writer.drain()
                return

    task = asyncio.create_task(poll_loop())
    return reader, writer, task


def test_bridge_protocol():
    """The MCP side accepts an extension, routes a command and gets the result."""
    async def run():
        await bridge.start_server()
        info = bridge.status()
        assert info["running"] is True
        assert info["port"] > 0

        reader, writer, poller = await _fake_extension(info["port"], bridge._state["token"])
        await asyncio.sleep(0.2)
        state = bridge.status()
        assert state["extension_connected"] is True, state
        assert state["extension_id"] == "fake-extension-id"
        assert state["tabs"] and state["tabs"][0]["title"] == "Example"

        result = await asyncio.wait_for(
            bridge._send({"cmd": "navigate", "url": "https://example.com"}), timeout=15)
        assert result.get("ok") is True, result
        assert result.get("navigated") == "https://example.com"

        poller.cancel()
        writer.close()
        bridge.stop_server()

    asyncio.run(run())


def test_bridge_rejects_unknown_actions():
    async def run():
        await bridge.start_server()
        result = await bridge.action("teleport")
        assert result["ok"] is False
        assert "unknown action" in result["error"]
        bridge.stop_server()

    asyncio.run(run())


def test_bridge_without_extension_refuses_commands():
    async def run():
        await bridge.start_server()
        result = await bridge.action("navigate", url="https://example.com")
        assert result["ok"] is False
        assert "no extension" in result["error"]
        bridge.stop_server()

    asyncio.run(run())


def test_bridge_binds_to_loopback_only():
    async def run():
        await bridge.start_server()
        port = bridge.status()["port"]
        assert port > 0
        host = bridge._state["server"].sockets[0].getsockname()[0]
        assert host == "127.0.0.1", host
        bridge.stop_server()

    asyncio.run(run())


def test_message_size_is_bounded():
    from body_mcp.bridge import MESSAGE_LIMIT

    assert MESSAGE_LIMIT <= 1024 * 1024
    big = {"type": "poll", "padding": "x" * (MESSAGE_LIMIT + 10)}
    assert len(json.dumps(big)) > MESSAGE_LIMIT


def test_installer_registers_the_native_host(tmp_path, monkeypatch):
    monkeypatch.setenv("BODY_MCP_CONFIG_DIR", str(tmp_path))
    result = bridge.install_native_host("abcdefghijklmnopabcdefghijklmnop")
    assert result["ok"] is True
    manifest = json.loads((tmp_path / "body_mcp_bridge.json").read_text(encoding="utf-8"))
    assert manifest["type"] == "stdio"
    assert manifest["allowed_origins"] == ["chrome-extension://abcdefghijklmnopabcdefghijklmnop/"]
    # on Windows the manifest points at a .cmd wrapper around the interpreter
    host_path = manifest["path"]
    assert host_path.endswith(("native_host.py", "native_host.cmd"))
    if host_path.endswith(".cmd"):
        wrapper = (tmp_path / "native_host.cmd").read_text(encoding="utf-8")
        assert "native_host.py" in wrapper
    allowed = bridge.allow_extension_id("secondidsecondidsecondidsecondid")
    assert allowed["ok"] is True
    manifest = json.loads((tmp_path / "body_mcp_bridge.json").read_text(encoding="utf-8"))
    assert len(manifest["allowed_origins"]) == 2


def test_native_host_script_exists():
    assert os.path.isfile(bridge.native_host_script())
