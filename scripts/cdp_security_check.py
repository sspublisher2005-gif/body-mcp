"""CDP security checks: disposable profile, loopback-only binding, owned-process cleanup.

These run against a REAL Chrome started by the real launcher.
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from body_mcp import cdp_launch  # noqa: E402

RESULTS = []


def record(name, ok, actual):
    RESULTS.append((name, "PASS_REAL" if ok else "FAIL", actual))
    print(f"[{'PASS_REAL' if ok else 'FAIL':<10}] {name}: {actual}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    port = free_port()
    argv = [sys.executable, "-m", "body_mcp.cdp_launch", "--browser", "chrome",
            "--port", str(port)]
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=dict(os.environ, PYTHONPATH=os.path.abspath("src")))
    output = proc.stdout + proc.stderr
    record("CDP-SEC-01", "DISPOSABLE" in output and "cdp-profile" in output,
           "the launcher uses a disposable profile by default "
           f"({'disposable' in output.lower()})")

    ready = False
    for _ in range(80):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as r:
                ready = r.status == 200
                break
        except Exception:
            time.sleep(0.25)
    record("CDP-SEC-02", ready, f"debug endpoint answering on 127.0.0.1:{port}={ready}")

    listeners = cdp_launch.port_listeners(port)
    loopback_only = bool(listeners) and all(
        addr.startswith("127.0.0.1:") or addr.startswith("[::1]:") for addr in listeners)
    record("CDP-SEC-03", loopback_only, f"listening addresses: {listeners}")

    state = cdp_launch.read_state()
    profile = state.get("profile", "")
    record("CDP-SEC-04", bool(profile) and "cdp-profile" in profile,
           f"profile in use: {profile}")

    # the port is unauthenticated - document that, do not pretend otherwise
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
            unauth_ok = r.status == 200
    except Exception:
        unauth_ok = False
    record("CDP-SEC-05", unauth_ok,
           "the DevTools endpoint answers without credentials (documented trust boundary)")

    status = subprocess.run([sys.executable, "-m", "body_mcp.cdp_launch", "--status"],
                            capture_output=True, text=True, timeout=60,
                            env=dict(os.environ, PYTHONPATH=os.path.abspath("src")))
    record("CDP-SEC-06", "OPEN" in status.stdout and "unauthenticated" in status.stdout,
           "--status reports the open port and the trust boundary")

    stop = subprocess.run([sys.executable, "-m", "body_mcp.cdp_launch", "--stop"],
                          capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, PYTHONPATH=os.path.abspath("src")))
    time.sleep(2)
    still_open = cdp_launch.endpoint_answers(port, timeout=1.0)
    record("CDP-SEC-07", not still_open,
           f"after --stop the port is closed={not still_open} ({stop.stdout.strip()[:70]!r})")

    failures = [r for r in RESULTS if r[1] == "FAIL"]
    print(f"\n{len(RESULTS)} checks, {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
