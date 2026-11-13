"""Build the full-report ZIP: every file of the project in one archive.

What goes in:
  - every tracked file (source, docs, tests, scripts, extension, examples, CI),
  - PROJECT_REPORT.md  - what we are building, why, for whom, and what is real,
  - CLAUDE_HANDOFF_PROMPT.md - the prompt to paste next to the archive,
  - GIT_HISTORY.txt - the commit log in readable form (the .git objects are not
    included: they are binary noise for a reader).

What stays out: caches (__pycache__, .pytest_cache, .ruff_cache), .venv, dist,
backups, .git. They are reproducible or local-only.

    python scripts/build_full_report.py
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

EXTRA_FILES = ("PROJECT_REPORT.md", "CLAUDE_HANDOFF_PROMPT.md")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True,
                              text=True, timeout=60).stdout
    except Exception:
        return ""


def collect() -> list[str]:
    """Every file of the project, relative to ROOT.

    Tracked files plus untracked-but-not-ignored ones (a new script must be in
    the archive even before it is committed)."""
    listed = _git("ls-files", "--cached", "--others", "--exclude-standard")
    files = [path for path in (line.strip() for line in listed.splitlines())
             if path and not _skip(path)]
    for name in EXTRA_FILES:
        if os.path.isfile(os.path.join(ROOT, name)) and name not in files:
            files.append(name)
    return sorted(set(files))


def _skip(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    if any(part in EXCLUDED_DIRS for part in parts[:-1]):
        return True
    if any(part in EXCLUDED_DIRS for part in parts):
        return True
    return path.lower().endswith(EXCLUDED_SUFFIXES)


def main() -> int:
    stamp = datetime.date.today().strftime("%Y%m%d")
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, f"{PROJECT}-full-report-{stamp}.zip")

    files = collect()
    history = _git("log", "--date=short", "--pretty=format:%h %ad %s").strip()
    status = _git("status", "--porcelain").strip()

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            full = os.path.join(ROOT, path)
            if not os.path.isfile(full):
                continue
            archive.write(full, f"{PROJECT}/{path}")
        archive.writestr(f"{PROJECT}/GIT_HISTORY.txt",
                         "BODY-MCP - COMMIT HISTORY (readable form)\n"
                         "============================================\n\n" + history + "\n")
        archive.writestr(f"{PROJECT}/WORKING_TREE_STATUS.txt",
                         "uncommitted changes at build time (empty = clean):\n\n"
                         + (status or "(clean)") + "\n")

    size = os.path.getsize(target) / 1024 / 1024
    print(f"archive : {target}")
    print(f"files   : {len(files) + 2}")
    print(f"size    : {size:.2f} MB")
    print("read me : PROJECT_REPORT.md (start here)")
    print("prompt  : CLAUDE_HANDOFF_PROMPT.md (paste next to the archive)")
    print("single-file bundles for chat models: python scripts/build_bundle.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
