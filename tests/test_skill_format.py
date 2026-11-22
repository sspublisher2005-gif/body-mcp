"""Our installable Agent Skill must follow agentskills.io spec (researched 2026-11-22)."""
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SKILL = os.path.join(ROOT, "skills", "body-mcp-loop", "SKILL.md")


def test_skill_folder_matches_name_and_has_valid_frontmatter():
    with open(SKILL, encoding="utf-8") as handle:
        text = handle.read()
    assert text.startswith("---\n")
    front = text.split("---", 2)[1]
    name = re.search(r"^name:\s*(\S+)$", front, re.M).group(1)
    description = re.search(r"^description:\s*(.+)$", front, re.M).group(1)
    assert name == "body-mcp-loop"
    assert name == os.path.basename(os.path.dirname(SKILL))  # spec: must match folder
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
    assert 1 <= len(description) <= 1024
    body = text.split("---", 2)[2]
    assert len(body.splitlines()) < 500  # spec recommendation


def test_skill_contains_the_loop_and_the_failure_rule():
    with open(SKILL, encoding="utf-8") as handle:
        text = handle.read()
    for phrase in ("body_capabilities()", "body_failure_context", "reflex_verify",
                   "webfetch", "needs_user"):
        assert phrase in text, phrase
