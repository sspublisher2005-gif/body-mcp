#!/usr/bin/env python3
"""Chrome/Edge native-messaging host for the Body-MCP bridge.

Chrome starts this script and speaks the native messaging protocol on stdio:
4-byte big-endian length + JSON payload. The extension polls; this host relays
between Chrome and the Body-MCP bridge server on 127.0.0.1.

Security:
  - argv[1] is the extension id Chrome passes; it must be on the allow-list in
    <config>/bridge.json, otherwise this host exits immediately,
  - messages are size-limited and must be JSON objects,
  - the bridge connection needs the session token from <config>/bridge.json.
"""
from __future__ import annotations

import json
import os
import socket
import struct
import sys

MESSAGE_LIMIT = 1024 * 1024


def config_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".config", "body_mcp")


def read_exact(stream, count: int) -> bytes | None:
    data = b""
    while len(data) < count:
        chunk = stream.read(count - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def read_message(stream) -> dict | None:
    header = read_exact(stream, 4)
    if header is None:
        return None
    length = struct.unpack(">I", header)[0]
    if length > MESSAGE_LIMIT:
        return None
    raw = read_exact(stream, length)
    if raw is None:
        return None
    try:
        message = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return message if isinstance(message, dict) else None


def write_message(stream, message: dict) -> None:
    raw = json.dumps(message).encode("utf-8")
    stream.write(struct.pack(">I", len(raw)) + raw)
    stream.flush()


def send_frame(sock_file, message: dict) -> None:
    raw = json.dumps(message).encode("utf-8")
    sock_file.write(struct.pack(">I", len(raw)) + raw)
    sock_file.flush()


def read_frame(sock_file) -> dict | None:
    header = read_exact(sock_file, 4)
    if header is None:
        return None
    length = struct.unpack(">I", header)[0]
    if length > MESSAGE_LIMIT:
        return None
    raw = read_exact(sock_file, length)
    if raw is None:
        return None
    try:
        message = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    return message if isinstance(message, dict) else None


def main() -> int:
    extension_id = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        with open(os.path.join(config_dir(), "bridge.json"), encoding="utf-8") as f:
            settings = json.load(f)
    except Exception:
        sys.stderr.write("bridge.json missing - run: python -m body_mcp.bridge --install\n")
        return 1

    allowed = settings.get("allowed_extension_ids") or []
    if extension_id not in allowed:
        sys.stderr.write(f"extension {extension_id!r} is not allowed to use the bridge\n")
        return 1

    try:
        connection = socket.create_connection((settings.get("host", "127.0.0.1"),
                                              int(settings.get("port", 0))), timeout=10)
    except Exception as exc:
        sys.stderr.write(f"cannot reach the bridge server: {exc}\n")
        return 1

    sock_file = connection.makefile("rb")
    send_frame(sock_file, {"type": "hello", "token": settings.get("token", ""),
                           "extension_id": extension_id})

    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    while True:
        message = read_message(stdin)
        if message is None:
            break
        try:
            send_frame(sock_file, message)
        except Exception:
            break
        answer = read_frame(sock_file)
        if answer is None:
            break
        write_message(stdout, answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())
