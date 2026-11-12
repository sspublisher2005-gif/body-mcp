"""Optional Body Console — a small local activity view of what the body is doing.

    python -m body_mcp.console          # standalone: reads the event file
    body_console_start()                # from inside the MCP server (tool)

Security model:
  - binds to 127.0.0.1 only (never the LAN),
  - every request must carry the session token (printed once at startup),
  - the Host header and Origin are validated (loopback only, no DNS rebinding),
  - fixed routes only, request bodies bounded, no filesystem access.

The console shows real executor events: task lifecycle, actions, verification
results, blockers and where the user must act. It can request cancellation of the
running task and disconnect the browser. It never shows page content.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import events, runtime

MAX_BODY = 4096
TOKEN_HEADER = "X-Body-Token"


def _state_snapshot() -> dict:
    from . import attach

    attached = None
    try:
        status = attach.attached_status()
        if status.get("attached"):
            attached = {"title": status.get("title"), "url": status.get("url"),
                        "endpoint": status.get("endpoint")}
    except Exception:
        attached = None
    active = runtime.registry.active()
    return {
        "now": time.time(),
        "active_task": active,
        "tasks": runtime.registry.list_tasks()[-8:],
        "attached_tab": attached,
        "events": events.bus.recent(limit=60),
    }


def _page_html(token: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Body-MCP console</title>
<style>
 body {{ font: 13px/1.45 ui-monospace, Consolas, monospace; margin: 0; background:#0f1115; color:#d7dbe0 }}
 header {{ padding: 10px 14px; border-bottom:1px solid #232833; display:flex; gap:14px; align-items:center; flex-wrap:wrap }}
 h1 {{ font-size:14px; margin:0; font-weight:600 }}
 .pill {{ border:1px solid #2b3240; border-radius:999px; padding:2px 9px; color:#9fb0c6 }}
 button {{ background:#1b2331; color:#d7dbe0; border:1px solid #2b3240; border-radius:6px; padding:5px 10px; cursor:pointer }}
 button:hover {{ background:#243044 }}
 #timeline {{ padding: 8px 14px 40px }}
 .ev {{ border-left:2px solid #2b3240; padding:3px 0 3px 10px; margin:2px 0 }}
 .t {{ color:#6f7c8f }} .ty {{ color:#9ad1a5 }} .st-FAILED {{ color:#ff8b8b }} .st-BLOCKED {{ color:#ffcf7a }}
 .st-UNCONFIRMED {{ color:#ffd479 }} .st-CONFIRMED {{ color:#8fd6a0 }} .st-CANCELLED {{ color:#c39bff }}
 .need {{ color:#ffcf7a; font-weight:600 }}
 .sc {{ color:#8b98a9 }}
</style></head>
<body>
<header>
  <h1>Body-MCP console</h1>
  <span class="pill" id="task">task: -</span>
  <span class="pill" id="tab">tab: -</span>
  <button onclick="call('/api/cancel')">Cancel task</button>
  <button onclick="call('/api/disconnect')">Disconnect browser</button>
  <span class="pill" id="conn"></span>
</header>
<div id="timeline"></div>
<script>
const TOKEN = {json.dumps(token)};
let last = 0;
async function refresh() {{
  try {{
    const r = await fetch('/api/state?token=' + encodeURIComponent(TOKEN), {{cache:'no-store'}});
    if (!r.ok) {{ document.getElementById('conn').textContent = 'offline'; return; }}
    const s = await r.json();
    document.getElementById('conn').textContent = 'live';
    document.getElementById('task').textContent = 'task: ' + (s.active_task ? s.active_task.task_id + ' (' + s.active_task.state + ')' : 'idle');
    document.getElementById('tab').textContent = 'tab: ' + (s.attached_tab ? s.attached_tab.title : 'managed browser');
    const box = document.getElementById('timeline');
    const rows = s.events.map(e => `
      <div class="ev">
        <span class="t">${{new Date(e.ts*1000).toLocaleTimeString()}}</span>
        <span class="ty">${{e.type}}</span>
        <span class="st-${{e.status || ''}}">${{e.status || ''}}</span>
        <span class="need">${{e.user_action_required ? 'ACTION NEEDED ' : ''}}</span>
        <span>${{e.summary || ''}}</span>
        <span class="sc">${{e.error_code ? '[' + e.error_code + ']' : ''}}</span>
      </div>`).join('');
    box.innerHTML = rows;
  }} catch (e) {{ document.getElementById('conn').textContent = 'offline'; }}
}}
async function call(path) {{
  await fetch(path + '?token=' + encodeURIComponent(TOKEN), {{method:'POST'}});
  refresh();
}}
setInterval(refresh, 800);
refresh();
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    server_version = "BodyMCPConsole/0.3"

    def log_message(self, fmt, *args):  # keep the console quiet
        return

    # -- security helpers -------------------------------------------------
    def _token_ok(self, query: dict) -> bool:
        supplied = (query.get("token", [""])[0]
                    or self.headers.get(TOKEN_HEADER, ""))
        return bool(supplied) and secrets.compare_digest(supplied, self.server.console_token)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip()
        name = host.split(":")[0].strip("[]").lower()
        return name in ("127.0.0.1", "localhost", "::1")

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = urlparse(origin).hostname or ""
        return host.lower() in ("127.0.0.1", "localhost", "::1")

    def _reject(self, code: int, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- routes -----------------------------------------------------------
    def do_GET(self):  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._host_ok():
            return self._reject(403, "host not allowed")
        if not self._origin_ok():
            return self._reject(403, "origin not allowed")
        if parsed.path == "/":
            if not self._token_ok(query):
                return self._reject(401, "token required")
            page = _page_html(self.server.console_token).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)
            return
        if not self._token_ok(query):
            return self._reject(401, "token required")
        if parsed.path == "/api/state":
            body = json.dumps(_state_snapshot()).encode("utf-8")
        elif parsed.path == "/api/events":
            since = float(query.get("since", ["0"])[0] or 0)
            body = json.dumps({"events": events.bus.recent(limit=100, since=since)}).encode("utf-8")
        else:
            return self._reject(404, "not found")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802 - stdlib naming
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._host_ok():
            return self._reject(403, "host not allowed")
        if not self._origin_ok():
            return self._reject(403, "origin not allowed")
        if not self._token_ok(query):
            return self._reject(401, "token required")
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._reject(413, "body too large")
        if length:
            self.rfile.read(length)
        if parsed.path == "/api/cancel":
            task_id = runtime.registry.request_cancel()
            result = {"cancelled": task_id}
        elif parsed.path == "/api/disconnect":
            import asyncio

            from . import attach

            try:
                loop = self.server.loop
                result = asyncio.run_coroutine_threadsafe(attach.detach(), loop).result(timeout=15)
            except Exception as exc:
                result = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        else:
            return self._reject(404, "not found")
        body = json.dumps(result, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Console:
    """A console bound to one process (the MCP server) so it sees live events."""

    def __init__(self, port: int = 8765):
        self.port = port
        self.token = secrets.token_urlsafe(16)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> dict:
        if self._server is not None:
            return self.info()
        try:
            import asyncio

            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        server = ThreadingHTTPServer(("127.0.0.1", self.port), _Handler)
        server.console_token = self.token
        server.loop = loop
        server.daemon_threads = True
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.3},
                                        daemon=True, name="body-console")
        self._thread.start()
        return self.info()

    def info(self) -> dict:
        return {
            "status": "running" if self._server else "stopped",
            "url": f"http://127.0.0.1:{self.port}/?token={self.token}",
            "port": self.port,
            "token": self.token,
            "note": "loopback only; keep the token private — it authorises cancel/disconnect",
        }

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        self._thread = None


_console: Console | None = None


def get_console() -> Console:
    global _console
    if _console is None:
        _console = Console()
    return _console


def main() -> int:
    """Standalone console: shows the event file written by a running server."""
    import argparse

    parser = argparse.ArgumentParser(description="Body-MCP activity console (read-only view)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    console = Console(port=args.port)
    info = console.start()
    print(f"Body-MCP console: {info['url']}")
    print("This view is read-only; start it from the MCP server for cancel/disconnect.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.stop()
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
