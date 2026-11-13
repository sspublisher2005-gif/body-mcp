"""Build the hand-off ZIP for Claude Code (a terminal agent: it reads PATHS).

The archive contains the whole project with `CLAUDE.md` at the root - Claude
Code reads that file automatically when it starts in the directory, so no
attachment and no paste is needed.

    python scripts/build_handoff.py
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROJECT = "body-mcp"

EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
                 "dist", "build", "backups", ".mypy_cache", "node_modules", ".idea"}
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".log", ".zip", ".whl")

START_HERE = """\
BODY-MCP - HAND-OFF FOR CLAUDE CODE
===================================

Claude Code is a TERMINAL agent: it has no attachment feature. It reads files
from disk. So there is nothing to attach - you unpack this and point it at the
folder.

THREE COMMANDS
--------------
    unzip body-mcp-claude-code-<date>.zip
    cd body-mcp
    claude

That is all. Claude Code reads CLAUDE.md from the project root automatically,
and CLAUDE.md states the mission, the non-negotiables and the verification
commands.

IF YOU PREFER TO GIVE IT A ONE-LINE PROMPT INSTEAD
--------------------------------------------------
    claude "Read CLAUDE.md in this directory and do what it says. Start with
    PROJECT_REPORT.md and docs/BACKLOG.md, then produce the four deliverables:
    the definition, the product brief, the honest gap analysis, and the master
    prompt for a coding agent. If you are fixing instead: work docs/BACKLOG.md
    top to bottom and verify every item."

WHAT IS IN THE ARCHIVE
----------------------
    body-mcp/CLAUDE.md           the instructions Claude Code reads on start
    body-mcp/PROJECT_REPORT.md   what we build, why, for whom, what is real vs mocked
    body-mcp/docs/BACKLOG.md     THE WORK ORDERS: every open item, ranked, with the
                                 verification that closes it - read this one
    body-mcp/docs/DECISIONS.md   the 16 design decisions and the reasons behind them
    body-mcp/AGENTS.md           the operating rules for any agent in this repo
    body-mcp/README.md           the user-facing documentation
    body-mcp/CHANGELOG.md        what changed and why
    body-mcp/src/body_mcp/*.py   the implementation (78 MCP tools live in server.py)
    body-mcp/tests/*.py          287 tests - the executable specification
    body-mcp/docs/*.md           architecture, safety, perception, privacy-mode, ...
    body-mcp/scripts/*.py        diagnostics, acceptance runs, the release builders
    body-mcp/extension/          the MV3 bridge for driving your own browser
    body-mcp/examples/           usage examples
    body-mcp/reports/qa-campaign/ the QA campaign (test matrix, defects, reports)
    body-mcp/.github/workflows/  the CI pipeline
    body-mcp/GIT_HISTORY.txt     the commit log, readable
    ENVIRONMENT.txt              what is installed on the machine that built this,
                                 and the exact commands for what is missing

VERIFY IT YOURSELF (optional, needs Python 3.11+)
---------------------------------------------------
    python -m pytest -q
    python -m body_mcp.doctor

NOTHING IS PUSHED: this archive is the only copy outside the original machine.
"""


def environment_report() -> str:
    """What the machine that built this has, and what is missing."""
    import json
    import subprocess
    import sys

    lines = ["BODY-MCP - ENVIRONMENT OF THE BUILDING MACHINE", "=" * 60, ""]
    try:
        out = subprocess.run([sys.executable, "-m", "body_mcp.doctor", "--json"],
                             cwd=ROOT, capture_output=True, text=True, timeout=300).stdout
        report = json.loads(out)
        lines.append("DOCTOR REPORT (read-only, changes nothing)")
        lines.append("-" * 60)
        for finding in report.get("findings", []):
            lines.append(f"[{finding.get('status'):<5}] {finding.get('check'):<18} "
                         f"{finding.get('detail')}")
            if finding.get("impact"):
                lines.append(f"        impact: {finding['impact']}")
            if finding.get("fix"):
                lines.append(f"        fix:    {finding['fix']}")
        steps = report.get("next_steps") or []
        if steps:
            lines.append("")
            lines.append("NEXT STEPS (optional, free, one at a time)")
            lines.append("-" * 60)
            lines.extend(f"  {step}" for step in steps)
        lines.append("")
        lines.append("NOTE: this is one Windows machine. What is proven here is not")
        lines.append("automatically proven on another one - re-run the doctor there.")
    except Exception as exc:
        lines.append(f"could not run the doctor: {type(exc).__name__}: {exc}")
    return "\n".join(lines) + "\n"


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True,
                              text=True, timeout=60).stdout
    except Exception:
        return ""


def files() -> list[str]:
    listed = _git("ls-files", "--cached", "--others", "--exclude-standard")
    out = []
    for line in listed.splitlines():
        path = line.strip()
        if not path:
            continue
        parts = path.replace("\\", "/").split("/")
        if any(part in EXCLUDED_DIRS for part in parts):
            continue
        if path.lower().endswith(EXCLUDED_SUFFIXES):
            continue
        if os.path.isfile(os.path.join(ROOT, path)):
            out.append(path)
    return sorted(set(out))


def main() -> int:
    stamp = datetime.date.today().strftime("%Y%m%d")
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, f"{PROJECT}-claude-code-{stamp}.zip")

    items = files()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("START-HERE.txt", START_HERE)
        archive.writestr("ENVIRONMENT.txt", environment_report())
        for path in items:
            archive.write(os.path.join(ROOT, path), f"{PROJECT}/{path}")
        archive.writestr(f"{PROJECT}/GIT_HISTORY.txt",
                         _git("log", "--date=short", "--pretty=format:%h %ad %s"))

    print(f"archive : {target}")
    print(f"files   : {len(items) + 3}")
    print(f"size    : {os.path.getsize(target) / 1024 / 1024:.2f} MB")
    print("\nuse it like this:")
    print(f"  unzip {os.path.basename(target)}")
    print(f"  cd {PROJECT}")
    print("  claude")
    return 0


if __name__ == "__main__":
    sys.exit(main())
