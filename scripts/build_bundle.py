"""Build single-file bundles that a chat model can read without unzipping.

Why: an attachment count is the hard limit (Claude.ai allows 20). A project
folder is 161 files - attaching it one by one is impossible. So: one .md file,
one attachment.

    python scripts/build_bundle.py

Outputs (in dist/):
  body-mcp-lite-<date>.md   ~200 KB - the report, the handoff prompt, the tool
                            catalogue, the core modules and the test index.
                            Fits in a context window: this is the one to attach.
  body-mcp-full-<date>.md   ~1.1 MB - every text file of the project verbatim.
"""
from __future__ import annotations

import datetime
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
PROJECT = "body-mcp"

EXCLUDED_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
                 "dist", "build", "backups", ".mypy_cache", "node_modules", ".idea"}
TEXT_SUFFIXES = (".py", ".md", ".toml", ".txt", ".json", ".js", ".html", ".yml", ".yaml",
                 ".csv", ".example", ".cfg", ".ini")

# The modules that carry the design decisions. A reader who has these plus the
# report and the tool catalogue understands the whole system.
CORE_MODULES = [
    "src/body_mcp/permissions.py",
    "src/body_mcp/approvals.py",
    "src/body_mcp/restrictions.py",
    "src/body_mcp/safety.py",
    "src/body_mcp/privacy.py",
    "src/body_mcp/local_worker.py",
    "src/body_mcp/models.py",
    "src/body_mcp/eyes.py",
    "src/body_mcp/watch.py",
    "src/body_mcp/vision.py",
    "src/body_mcp/demo.py",
    "src/body_mcp/doctor.py",
]

TOP_FILES = ["README.md", "AGENTS.md", "CHANGELOG.md", "PROJECT_REPORT.md",
             "CLAUDE_HANDOFF_PROMPT.md", "THIRD_PARTY_NOTICES.md", "LICENSE",
             "pyproject.toml"]


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", ROOT, *args], capture_output=True,
                              text=True, timeout=60).stdout
    except Exception:
        return ""


def all_files() -> list[str]:
    listed = _git("ls-files", "--cached", "--others", "--exclude-standard")
    out = []
    for line in listed.splitlines():
        path = line.strip()
        if not path:
            continue
        parts = path.replace("\\", "/").split("/")
        if any(part in EXCLUDED_DIRS for part in parts):
            continue
        if os.path.isfile(os.path.join(ROOT, path)):
            out.append(path)
    return sorted(set(out))


def read(path: str) -> str:
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def file_index(files: list[str]) -> str:
    rows = ["| file | lines | what it is |", "|---|---:|---|"]
    for path in files:
        text = read(path)
        lines = text.count("\n") + 1
        first = next((line.strip() for line in text.splitlines()
                      if line.strip() and not line.strip().startswith(("#", '"""', "'''"))),
                     "")
        rows.append(f"| `{path}` | {lines} | {first[:90]} |")
    return "\n".join(rows)


def tool_catalogue() -> str:
    """Every tool with its docstring - the public surface of the body."""
    source = read("src/body_mcp/server.py")
    tools = re.findall(r'@mcp\.tool\(\)\s*\nasync def (\w+)\(([^)]*)\)\s*->\s*dict:\s*'
                        r'"""(.*?)"""', source, re.S)
    out = [f"{len(tools)} MCP tools.\n",
           "| tool | parameters | what it does |", "|---|---|---|"]
    for name, params, doc in tools:
        summary = " ".join(doc.strip().split())
        out.append(f"| `{name}` | `{params.strip()}` | {summary[:220]} |")
    return "\n".join(out)


def test_index(files: list[str]) -> str:
    """The test names - the executable specification of the behaviour."""
    out = []
    for path in [f for f in files if f.startswith("tests/") and f.endswith(".py")]:
        text = read(path)
        doc = next((line.strip() for line in text.splitlines()
                    if line.strip().startswith('"""')), "")
        out.append(f"\n### `{path}`\n\n{doc[:300]}")
        for match in re.finditer(r"^def (test_\w+)\(([^)]*)\):", text, re.M):
            name = match.group(1)
            body = text[match.end():match.end() + 700]
            docstring = re.search(r'"""(.*?)"""', body, re.S)
            summary = " ".join(docstring.group(1).split()) if docstring else ""
            out.append(f"- `{name}` — {summary[:160]}")
    return "\n".join(out)


def bundle(files: list[str], lite: bool) -> str:
    chunks: list[str] = [
        f"# {PROJECT} — {'LITE' if lite else 'FULL'} BUNDLE\n",
        ("A single self-contained file. Every path below is relative to the "
         "repository root.\n\n"),
        f"- generated: {datetime.date.today().isoformat()}\n",
        f"- files in the project: {len(files)}\n",
        ("- how to read it: §1 is the report (read it first), §2 is the prompt to "
         "use, §3 is the git history, §4 is the tool catalogue, §5 is the core "
         "design modules, §6 is the test index, §7 is the file index.\n"),
        "\n---\n\n# §1 — THE REPORT\n",
        read("PROJECT_REPORT.md"),
        "\n---\n\n# §2 — THE HANDOFF PROMPT (paste next to this file)\n",
        read("CLAUDE_HANDOFF_PROMPT.md"),
        "\n---\n\n# §3 — GIT HISTORY\n",
        _git("log", "--date=short", "--pretty=format:%h %ad %s"),
        "\n\n---\n\n# §4 — THE TOOL CATALOGUE (the public surface)\n",
        tool_catalogue(),
    ]
    if lite:
        chunks.append("\n\n---\n\n# §5 — CORE DESIGN MODULES (verbatim)\n")
        for path in CORE_MODULES:
            chunks.append(f"\n\n## `{path}`\n\n```python\n{read(path)}\n```\n")
        chunks.append("\n\n---\n\n# §6 — THE TEST INDEX (the executable specification)\n")
        chunks.append(test_index(files))
        chunks.append("\n\n---\n\n# §7 — FILE INDEX\n")
        chunks.append(file_index(files))
    else:
        chunks.append("\n\n---\n\n# §5 — EVERY SOURCE FILE (verbatim)\n")
        for path in files:
            if path.endswith(TEXT_SUFFIXES) or "." not in os.path.basename(path):
                body = read(path)
                if not body.strip():
                    continue
                language = {"py": "python", "js": "javascript", "md": "markdown",
                            "toml": "toml", "json": "json", "yml": "yaml",
                            "yaml": "yaml", "html": "html", "csv": "csv"}.get(
                                path.rsplit(".", 1)[-1], "")
                chunks.append(f"\n\n## `{path}`\n\n```{language}\n{body}\n```\n")
    return "".join(chunks)


def main() -> int:
    files = all_files()
    stamp = datetime.date.today().strftime("%Y%m%d")
    out_dir = os.path.join(ROOT, "dist")
    os.makedirs(out_dir, exist_ok=True)
    for name, lite in ((f"{PROJECT}-lite-{stamp}.md", True),
                       (f"{PROJECT}-full-{stamp}.md", False)):
        path = os.path.join(out_dir, name)
        text = bundle(files, lite)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        size = os.path.getsize(path) / 1024
        print(f"{path}\n   {size:.0f} KB  (~{size * 1024 / 4 / 1000:.0f}k tokens)")
    print("\nattach ONE of these per message - never the folder, never 20+ files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
