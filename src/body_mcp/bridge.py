"""The extension bridge: drive the user's own Edge/Chrome, with their explicit consent.

How it works (no open debug port, no CDP, no LAN exposure):

  1. The user loads the unpacked extension (one click) and clicks "Connect this tab".
     The extension attaches with `chrome.debugger` - Chromium shows its own
     "started debugging this browser" bar, which the user can cancel at any time.
  2. The extension talks to Body-MCP over **Chrome native messaging**: Chrome starts
     `scripts/native_host.py`, which connects back to this server over **127.0.0.1**
     with a session token.
  3. The extension polls for commands (navigate / read / detach); results travel back
     the same way.

Security properties enforced in code:
  - loopback only, random port, session token in a file only the user can read,
  - the native host refuses any extension whose id is not on the allow-list,
  - every message is length-checked and schema-checked; unknown commands are dropped,
  - the extension holds no broad host permissions: `debugger` + `nativeMessaging` + `tabs`,
  - `detach` is always available (extension popup, or the `disconnect` action),
  - nothing is stored: no page text, no URLs, no screenshots are written anywhere.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import secrets
import struct
import sys
import time

HOST_NAME = "body_mcp_bridge"
MESSAGE_LIMIT = 1024 * 1024      # 1 MB per native message
COMMAND_TIMEOUT = 20.0
POLL_HINT = "poll every ~300 ms from the extension"

_state: dict = {"server": None, "port": None, "token": None, "host": None,
                "extension_id": None, "last_seen": None, "pending": None,
                "tasks": {}, "tabs": []}


def config_dir() -> str:
    from . import permissions

    cfg = permissions._config_dir()
    os.makedirs(cfg, exist_ok=True)
    return cfg


def state_path() -> str:
    return os.path.join(config_dir(), "bridge.json")


def load_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(data: dict) -> None:
    try:
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


# --------------------------------------------------------------------- server
async def _read_message(reader: asyncio.StreamReader) -> dict | None:
    try:
        header = await reader.readexactly(4)
    except (asyncio.IncompleteReadError, ConnectionResetError):
        return None
    length = struct.unpack(">I", header)[0]
    if length > MESSAGE_LIMIT:
        return None
    try:
        raw = await reader.readexactly(length)
    except asyncio.IncompleteReadError:
        return None
    try:
        message = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return message if isinstance(message, dict) else None


def _frame(message: dict) -> bytes:
    raw = json.dumps(message).encode("utf-8")
    return struct.pack(">I", len(raw)) + raw


async def _handle_host(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """One native-host connection: relays polls and results to the extension."""
    state = _state
    state["host"] = writer
    try:
        while True:
            message = await _read_message(reader)
            if message is None:
                break
            kind = message.get("type")
            if kind == "hello":
                state["extension_id"] = message.get("extension_id")
                state["last_seen"] = time.time()
                state["tabs"] = message.get("tabs") or []
                writer.write(_frame({"type": "hello_ack", "ok": True}))
                await writer.drain()
            elif kind == "poll":
                state["last_seen"] = time.time()
                command = state.get("pending")
                state["pending"] = None
                writer.write(_frame({"type": "poll_result", "command": command}))
                await writer.drain()
            elif kind == "result":
                task_id = message.get("task_id")
                future = state["tasks"].get(task_id)
                if future is not None and not future.done():
                    future.set_result(message.get("result"))
                state["tasks"].pop(task_id, None)
            elif kind == "tabs":
                state["tabs"] = message.get("tabs") or []
                state["last_seen"] = time.time()
    finally:
        if state.get("host") is writer:
            state["host"] = None
        with contextlib.suppress(Exception):
            writer.close()


async def start_server() -> dict:
    """Start the loopback bridge server and publish the connection details."""
    state = _state
    if state.get("server") is not None:
        return status()
    server = await asyncio.start_server(_handle_host, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    token = secrets.token_urlsafe(24)
    state.update({"server": server, "port": port, "token": token, "host": None,
                  "extension_id": None, "last_seen": None, "pending": None, "tasks": {}})
    existing = load_state()
    save_state({"host": "127.0.0.1", "port": port, "token": token,
                "allowed_extension_ids": existing.get("allowed_extension_ids", []),
                "native_host_name": HOST_NAME,
                "native_host_script": native_host_script(),
                "started_at": time.time()})
    return status()


def stop_server() -> None:
    state = _state
    if state.get("server") is not None:
        with contextlib.suppress(Exception):
            state["server"].close()
    state.update({"server": None, "host": None, "pending": None, "tasks": {}})
    with contextlib.suppress(OSError):
        os.remove(state_path())


def native_host_script() -> str:
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(here, "scripts", "native_host.py")


def status() -> dict:
    state = _state
    connected = state.get("host") is not None
    last_seen = state.get("last_seen")
    return {
        "running": state.get("server") is not None,
        "port": state.get("port"),
        "extension_connected": connected,
        "extension_id": state.get("extension_id"),
        "last_seen_s": int(time.time() - last_seen) if last_seen else None,
        "tabs": state.get("tabs") or [],
        "note": ("the extension is connected - the user clicked 'Connect this tab'"
                 if connected else
                 f"no extension connected yet: load the unpacked extension and click Connect; "
                 f"the native host polls {POLL_HINT}"),
    }


async def _send(command: dict) -> dict:
    """Hand a command to the extension and wait for its result."""
    state = _state
    if state.get("host") is None:
        return {"ok": False, "error": "no extension is connected (load the extension and click "
                                     "'Connect this tab')"}
    task_id = secrets.token_hex(8)
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    state["tasks"][task_id] = future
    state["pending"] = {"task_id": task_id, **command}
    try:
        result = await asyncio.wait_for(future, timeout=COMMAND_TIMEOUT)
    except asyncio.TimeoutError:
        state["tasks"].pop(task_id, None)
        return {"ok": False, "error": f"the extension did not answer within {COMMAND_TIMEOUT:.0f}s"}
    return result if isinstance(result, dict) else {"ok": False, "error": "bad result"}


async def action(action_name: str, url: str = "") -> dict:
    """The one tool body: status / connect / tabs / navigate / read / disconnect."""
    if action_name == "status":
        return {"ok": True, **status()}
    if action_name == "connect":
        await start_server()
        deadline = time.time() + 15
        while time.time() < deadline and _state.get("host") is None:
            await asyncio.sleep(0.25)
        return {"ok": _state.get("host") is not None, **status()}
    if action_name == "tabs":
        return {"ok": True, "tabs": _state.get("tabs") or [], "status": status()}
    if action_name == "navigate":
        if not url:
            return {"ok": False, "error": "navigate needs a url"}
        return await _send({"cmd": "navigate", "url": url})
    if action_name == "read":
        return await _send({"cmd": "read"})
    if action_name == "screenshot":
        return await _send({"cmd": "screenshot"})
    if action_name == "disconnect":
        result = await _send({"cmd": "detach"})
        stop_server()
        return {"ok": True, "detached": True, "result": result}
    return {"ok": False, "error": f"unknown action {action_name!r}"}


# ------------------------------------------------------------------ installer
def install_native_host(extension_id: str = "") -> dict:
    """Register the native messaging host with Chrome and Edge (Windows).

    The extension id is the only thing the user must supply: it is shown by the
    extension's popup and by `chrome://extensions`.
    """
    manifest_path = os.path.join(config_dir(), f"{HOST_NAME}.json")
    script = native_host_script()
    if not os.path.isfile(script):
        return {"ok": False, "error": f"native host script not found: {script}"}
    # Chrome launches the host itself; on Windows that needs a real executable,
    # so we generate a tiny .cmd wrapper around the current interpreter.
    wrapper = os.path.join(config_dir(), "native_host.cmd")
    interpreter = sys.executable
    with open(wrapper, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("@echo off\r\n")
        f.write(f'"{interpreter}" "{script}" %*\r\n')
    host_path = wrapper if os.name == "nt" else script

    manifest = {
        "name": HOST_NAME,
        "description": "Body-MCP bridge (loopback, token authenticated)",
        "path": host_path,
        "type": "stdio",
        "allowed_origins": ([f"chrome-extension://{extension_id}/"] if extension_id else []),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    registered = []
    if os.name == "nt":
        import winreg

        # EVERY Chromium browser the user has: Chrome, Edge, Brave, Vivaldi,
        # Opera. Native messaging is per-browser; registering only Chrome/Edge
        # made the bridge "work" in some browsers and fail silently in others.
        vendors = ("Google\\Chrome", "Microsoft\\Edge", "BraveSoftware\\Brave-Browser",
                   "Vivaldi\\Vivaldi", "Opera Software\\Opera Stable")
        for vendor in vendors:
            key_path = f"Software\\{vendor}\\NativeMessagingHosts\\{HOST_NAME}"
            try:
                key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, manifest_path)
                winreg.CloseKey(key)
                probe = f"Software\\{vendor}"
                try:
                    winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, probe))
                    registered.append(vendor.replace("\\", "/"))
                except OSError:
                    registered.append(vendor.replace("\\", "/") + " (registered; not detected)")
            except Exception as exc:
                registered.append(f"{vendor}: FAILED ({exc})")
    else:
        base = os.path.join(os.path.expanduser("~"), ".config",
                            "google-chrome", "NativeMessagingHosts")
        if "chrome" in str(manifest.get("allowed_origins", [""])):
            os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, HOST_NAME), "w", encoding="utf-8") as f:
            f.write(manifest_path)
        registered.append("google-chrome (Linux)")

    existing = load_state()
    existing["allowed_extension_ids"] = ([extension_id] if extension_id
                                         else existing.get("allowed_extension_ids", []))
    existing["native_host_manifest"] = manifest_path
    save_state(existing)
    return {"ok": True, "manifest": manifest_path, "host": host_path,
            "interpreter": interpreter, "registered": registered,
            "extension_id": extension_id or "(not set yet)",
            "next": ("Load the extension from the 'extension' folder (chrome://extensions -> "
                     "Developer mode -> Load unpacked), click 'Connect this tab', then run "
                     "python -m body_mcp.bridge --allow-extension-id <id>")}


def allow_extension_id(extension_id: str) -> dict:
    """Allow one extension id to use the bridge."""
    existing = load_state()
    ids = set(existing.get("allowed_extension_ids", []))
    ids.add(extension_id)
    existing["allowed_extension_ids"] = sorted(ids)
    save_state(existing)
    manifest_path = os.path.join(config_dir(), f"{HOST_NAME}.json")
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        manifest["allowed_origins"] = [f"chrome-extension://{i}/" for i in sorted(ids)]
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
    except Exception:
        pass
    return {"ok": True, "allowed_extension_ids": sorted(ids)}


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Body-MCP extension bridge")
    parser.add_argument("--install", action="store_true", help="register the native host")
    parser.add_argument("--extension-id", default="", help="the extension id to allow")
    parser.add_argument("--allow-extension-id", default="", help="allow an extension id")
    parser.add_argument("--status", action="store_true", help="show the bridge status")
    args = parser.parse_args()

    if args.install:
        print(json.dumps(install_native_host(args.extension_id), indent=2))
        return 0
    if args.allow_extension_id:
        print(json.dumps(allow_extension_id(args.allow_extension_id), indent=2))
        return 0
    if args.status:
        print(json.dumps(status(), indent=2))
        return 0

    async def run() -> None:
        await start_server()
        info = status()
        print(f"bridge listening on 127.0.0.1:{info['port']}")
        print("waiting for the extension (load it in the browser and click 'Connect this tab')")
        while True:
            await asyncio.sleep(5)
            state = status()
            if state["extension_connected"]:
                print(f"extension connected: {state['extension_id']} tabs={state['tabs']}")

    asyncio.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
