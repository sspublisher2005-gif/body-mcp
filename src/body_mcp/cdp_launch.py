"""Launch Chrome/Edge with a loopback debug port so Body-MCP can attach.

This is ALWAYS an explicit user act: `python -m body_mcp.cdp_launch --browser chrome`.
It never runs from the MCP server.

Security posture (all enforced here, not just documented):
  - the debug port is bound to 127.0.0.1 only (`--remote-debugging-address`),
  - the browser runs with a DISPOSABLE profile by default, inside the Body-MCP
    config dir - your everyday Chrome profile, cookies and history are never opened
    unless you explicitly pass `--user-data-dir <your profile>` and accept the warning,
  - the debug port is UNAUTHENTICATED: while it is open, any local process can drive
    that browser. `python -m body_mcp.cdp_launch --stop` closes the browser *we*
    started (we know its PID); your own browser is never touched,
  - `--status` shows whether a debug port is open and who owns it.

Nothing here bypasses an access control: the browser starts normally, with its own
profile and its own security model.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

LOOPBACK = "127.0.0.1"
CANDIDATES = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "edge": [
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ],
}


def state_path() -> str:
    from . import permissions

    cfg = permissions._config_dir()
    os.makedirs(cfg, exist_ok=True)
    return os.path.join(cfg, "cdp_session.json")


def own_profile_dir(browser: str = "chrome") -> str | None:
    """The everyday profile directory of the user's own browser (if we can find it)."""
    os.path.expanduser("~")
    if browser == "edge":
        candidate = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge",
                                 "User Data")
    else:
        candidate = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome",
                                 "User Data")
    return candidate if candidate and os.path.isdir(candidate) else None


def default_profile_dir(port: int) -> str:
    """A DISPOSABLE profile, unique per launch.

    A fixed path would make a second launch silently reuse the browser that is
    already running with that profile (and then the new debug port never opens).
    A unique directory guarantees a fresh, isolated browser every time.
    """
    from . import permissions

    base = os.path.join(permissions._config_dir(), "cdp-profile")
    os.makedirs(base, exist_ok=True)
    path = os.path.join(base, f"p{port}-{int(time.time())}")
    os.makedirs(path, exist_ok=True)
    return path


def owned_pids(profile_dir: str) -> list[int]:
    """PIDs of browser processes started with OUR profile directory."""
    if not profile_dir:
        return []
    try:
        script = (
            "$p = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "
            f"'*{profile_dir}*' }}; "
            "if ($p) { $p | Select-Object -ExpandProperty ProcessId }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=60)
    except Exception:
        return []
    pids = []
    for line in (out.stdout or "").splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def endpoint_answers(port: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://{LOOPBACK}:{port}/json/version", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def port_listeners(port: int) -> list[str]:
    """Which addresses is the port bound to? (loopback only is what we want).

    Uses Get-NetTCPConnection (exact); falls back to parsing `netstat -ano`.
    """
    listeners: list[str] = []
    try:
        script = (f"Get-NetTCPConnection -LocalPort {port} -ErrorAction SilentlyContinue "
                  "| Select-Object -ExpandProperty LocalAddress -Unique")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=45)
        for line in (out.stdout or "").splitlines():
            address = line.strip()
            if address:
                listeners.append(f"{address}:{port}")
        if listeners:
            return listeners
    except Exception:
        pass
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True, timeout=30)
    except Exception:
        return listeners
    for line in (out.stdout or "").splitlines():
        if f":{port}" not in line or "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) > 1:
            listeners.append(parts[1])
    return listeners


def read_state() -> dict:
    try:
        with open(state_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_state(data: dict) -> None:
    try:
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def clear_state() -> None:
    with_state = state_path()
    with contextlib.suppress(OSError):
        os.remove(with_state)


def _pid_alive(pid: int) -> bool:
    try:
        import psutil  # optional
    except Exception:
        psutil = None
    if psutil is not None:
        return psutil.pid_exists(pid)
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=20)
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _terminate_via_wmi(pid: int) -> bool:
    """Last resort for processes taskkill refuses (orphaned children)."""
    try:
        script = (f"$p = Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\"; "
                   "if ($p) { Invoke-CimMethod -InputObject $p -MethodName Terminate | "
                   "Out-Null }; 'done'")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=60)
        return "done" in (out.stdout or "")
    except Exception:
        return False


def stop_owned_browser() -> int:
    """Terminate only the browser instance we started (never the user's own).

    Chrome may hand the process over to a child process, so we match every
    process whose command line contains OUR unique profile directory.
    """
    state = read_state()
    profile = state.get("profile") or ""
    pids = owned_pids(profile)
    pid = state.get("pid")
    if pid and _pid_alive(int(pid)) and int(pid) not in pids:
        pids.append(int(pid))
    if not pids:
        clear_state()
        print("no Body-MCP-started browser is running")
        return 0
    for target in pids:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(target), "/T", "/F"],
                           capture_output=True, timeout=30)
            _terminate_via_wmi(target)
        else:
            with contextlib.suppress(OSError):
                os.kill(target, 15)
    time.sleep(1.0)
    survivors = owned_pids(profile)
    clear_state()
    if profile:
        with contextlib.suppress(OSError):
            shutil.rmtree(profile, ignore_errors=True)
    if survivors:
        print(f"closed the debug browser we started (pids {pids}); the debug port is closed")
        print(f"WARNING: these browser processes are still alive (orphaned): {survivors}. "
              "Close them manually if they keep running.")
    else:
        print(f"closed the debug browser we started (pids {pids}); the debug port is now closed")
    return 0


def status() -> int:
    state = read_state()
    port = int(state.get("port") or 9222)
    listening = endpoint_answers(port, timeout=1.0)
    print(f"debug port {port}: {'OPEN' if listening else 'closed'}")
    if listening:
        for address in port_listeners(port):
            print(f"  listening on {address}")
        print("  NOTE: the DevTools port is unauthenticated - any local process can drive it")
    if state.get("pid"):
        alive = "running" if _pid_alive(int(state["pid"])) else "not running"
        print(f"  browser started by Body-MCP: pid {state['pid']} ({alive})")
    return 0


def cleanup_profiles(keep_last: int = 0) -> dict:
    """Delete the disposable browser profiles Body-MCP created (each is ~150 MB).

    Only paths under <config>/cdp-profile are touched - never a personal profile.
    """
    base = os.path.join(os.path.dirname(state_path()), "cdp-profile")
    removed = []
    freed = 0
    if not os.path.isdir(base):
        return {"ok": True, "removed": [], "freed_mb": 0,
                "note": "no disposable profiles found"}
    entries = sorted((os.path.join(base, name) for name in os.listdir(base)),
                     key=lambda path: os.path.getmtime(path) if os.path.exists(path) else 0)
    if keep_last:
        entries = entries[:-keep_last]
    for path in entries:
        try:
            size = sum(os.path.getsize(os.path.join(root, name))
                        for root, _dirs, names in os.walk(path) for name in names)
            shutil.rmtree(path, ignore_errors=True)
            removed.append(path)
            freed += size
        except OSError:
            continue
    return {"ok": True, "removed": removed, "freed_mb": round(freed / 1024 / 1024, 1),
            "note": "only disposable Body-MCP profiles were removed - your own browser "
                    "profiles were not touched"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--browser", choices=list(CANDIDATES), default="chrome")
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--user-data-dir", default=None,
                        help="the profile directory to use (default: a DISPOSABLE profile "
                             "inside the Body-MCP config dir - this is a SEPARATE browser, "
                             "not your everyday one)")
    parser.add_argument("--own-profile", action="store_true",
                        help="use YOUR everyday browser profile (Windows/macOS only). "
                             "Chromium 136+ refuses the debug port with the default "
                             "profile, so this normally fails with a clear explanation")
    parser.add_argument("--stop", action="store_true",
                        help="close the debug browser Body-MCP started (never your own)")
    parser.add_argument("--status", action="store_true",
                        help="show whether a debug port is open and who listens on it")
    parser.add_argument("--cleanup", action="store_true",
                        help="delete the disposable browser profiles Body-MCP created")
    parser.add_argument("--headed", action="store_true",
                        help="show the browser window (default: headless)")
    args = parser.parse_args()

    if args.status:
        return status()
    if args.stop:
        return stop_owned_browser()
    if args.cleanup:
        result = cleanup_profiles()
        print(f"removed {len(result['removed'])} disposable profile(s), "
              f"freed {result['freed_mb']} MB")
        for path in result["removed"]:
            print(f"  - {path}")
        return 0

    if not (1024 <= args.port <= 65535):
        print(f"error: port {args.port} out of range (1024-65535)")
        return 2

    if endpoint_answers(args.port):
        print(f"port {args.port} already answers http://{LOOPBACK}:{args.port}/json/version")
        print("a debuggable browser is already running - attach with attach_browser()")
        print("or close it first: python -m body_mcp.cdp_launch --stop")
        return 0

    exe = next((c for c in CANDIDATES[args.browser] if os.path.isfile(c)), None)
    if exe is None:
        print(f"error: could not find {args.browser} - checked standard install locations")
        return 3

    if args.user_data_dir:
        profile = args.user_data_dir
        personal = True
    elif args.own_profile:
        profile = own_profile_dir(args.browser)
        personal = True
        if not profile:
            print(f"error: could not find the {args.browser} profile directory")
            return 3
    else:
        profile = default_profile_dir(args.port)
        personal = False

    argv = [exe, f"--remote-debugging-port={args.port}",
            f"--remote-debugging-address={LOOPBACK}",
            f"--user-data-dir={profile}",
            "--no-first-run", "--no-default-browser-check"]
    if not args.headed:
        argv.append("--headless=new")

    print(f"launching: {exe}")
    print(f"  debug endpoint: http://{LOOPBACK}:{args.port} (loopback only)")
    if personal:
        print(f"  profile: YOUR OWN profile at {profile}")
    else:
        print(f"  profile: DISPOSABLE at {profile}")
        print("  NOTE: this is a SEPARATE browser window with its own empty profile -")
        print("        it is NOT your everyday browser. Use --own-profile to try yours.")
    if personal:
        print("  WARNING: your everyday profile, cookies and history are now exposed to any")
        print("           local process while the debug port is open. Close it afterwards:")
        print("           python -m body_mcp.cdp_launch --stop")
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    write_state({"pid": proc.pid, "port": args.port, "profile": profile,
                 "personal_profile": personal, "started_at": time.time(),
                 "exe": exe})
    for _ in range(80):
        if endpoint_answers(args.port, timeout=0.5):
            for address in port_listeners(args.port):
                print(f"  listening on {address}")
            print(f"cdp ready on {LOOPBACK}:{args.port} - attach with attach_browser()")
            print("remember: python -m body_mcp.cdp_launch --stop closes it again")
            return 0
        time.sleep(0.25)
    print("browser launched but the CDP endpoint never answered.")
    if personal:
        print("")
        print("This is the expected result on Chromium/Edge 136+ when the DEFAULT profile")
        print("is used: the browser deliberately ignores --remote-debugging-port for the")
        print("default profile (a security change). Your everyday browser cannot be driven")
        print("over a debug port. The ways forward:")
        print("  1) let Body-MCP start a SEPARATE browser with its own profile")
        print("     (default: python -m body_mcp.cdp_launch --browser edge)")
        print("  2) install the Body-MCP browser extension and connect your real browser")
        print("     through it (explicit 'Allow' click, no open debug port)")
        print("  3) body-dev can still READ your open windows read-only (body_windows())")
    else:
        print("check the browser window; if it reused a running process without the flag,")
        print("close all browser windows and retry")
    return 1


if __name__ == "__main__":
    sys.exit(main())
