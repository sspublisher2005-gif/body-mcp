"""The 'ordinary user' proof: a clean environment, install the wheel, use it.

    python scripts/clean_install_check.py

Creates a throwaway virtual environment, installs the built wheel (no source tree
on the path), then runs the doctor and a real MCP handshake against the INSTALLED
package. Nothing in the user's environment is touched.
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RESULTS = []


def record(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL':<4}] {name}: {detail}")


def main() -> int:
    wheels = sorted(glob.glob(os.path.join(ROOT, "dist", "body_mcp-*.whl")))
    if not wheels:
        print("no wheel in dist/ - run: python -m pip wheel . --no-deps -w dist")
        return 2
    wheel = wheels[-1]
    print(f"artifact: {os.path.basename(wheel)} "
          f"({os.path.getsize(wheel) / 1024:.0f} KB)\n")

    venv = tempfile.mkdtemp(prefix="body_clean_venv_")
    # venv needs a directory that does not exist yet
    import shutil

    shutil.rmtree(venv, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    python = os.path.join(venv, "Scripts", "python.exe")
    if not os.path.isfile(python):
        python = os.path.join(venv, "bin", "python")
    record("clean venv created", os.path.isfile(python), venv)

    install = subprocess.run([python, "-m", "pip", "install", "--quiet", wheel],
                            capture_output=True, text=True, timeout=900)
    record("wheel installs", install.returncode == 0,
           (install.stderr or install.stdout or "").strip()[-160:])

    version = subprocess.run([python, "-c",
                              "import body_mcp, os;"
                              "print(body_mcp.__version__);"
                              "print(os.path.dirname(body_mcp.__file__))"],
                             capture_output=True, text=True, timeout=180)
    lines = [line for line in version.stdout.splitlines() if line]
    record("installed package imports", version.returncode == 0 and len(lines) == 2,
           f"version={lines[0] if lines else '?'} at {lines[1] if len(lines) > 1 else '?'}")
    record("it is the installed copy, not the source tree",
           bool(lines) and ROOT not in lines[1], lines[1] if len(lines) > 1 else "")

    doctor = subprocess.run([python, "-m", "body_mcp.doctor", "--json"],
                            capture_output=True, text=True, timeout=300)
    ok = doctor.returncode == 0
    try:
        findings = json.loads(doctor.stdout).get("findings", [])
        summary = ", ".join(f"{f['check']}:{f['status']}" for f in findings[:6])
    except Exception:
        summary = (doctor.stdout or doctor.stderr or "").strip()[-160:]
    record("body doctor runs on the installed package", ok, summary)

    handshake = subprocess.run([python, "-c", """
import json, subprocess, sys
proc = subprocess.Popen([sys.executable, "-m", "body_mcp.server"],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
def send(o):
    proc.stdin.write(json.dumps(o).encode() + b"\\n"); proc.stdin.flush()
send({"jsonrpc":"2.0","id":1,"method":"initialize",
      "params":{"protocolVersion":"2026-07-28","capabilities":{},
                "clientInfo":{"name":"clean-install","version":"1"}}})
init = json.loads(proc.stdout.readline().decode())
send({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
send({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}})
tools = json.loads(proc.stdout.readline().decode())["result"]["tools"]
print(json.dumps({"server": init["result"]["serverInfo"]["name"],
                  "tools": len(tools)}))
proc.stdin.close(); proc.wait(timeout=20)
"""], capture_output=True, text=True, timeout=300)
    record("MCP handshake + tool discovery from the installed package",
           handshake.returncode == 0 and '"tools"' in handshake.stdout,
           (handshake.stdout or handshake.stderr).strip()[-160:])

    print()
    failures = [r for r in RESULTS if not r[1]]
    print(f"{len(RESULTS)} checks, {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
