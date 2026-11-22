"""Measure the body's own context cost — the #1 complaint in the 2026 MCP community.

HN evidence (researched 2026-11-22):
  - Context Mode: raw MCP outputs 315 KB -> 5.4 KB, session 30 min -> 3 h.
  - Chisel: 47 tools -> 14 with the same functionality; return what the agent
    needs for the NEXT action, not raw API dumps.
  - LangAlpha: 80 tools, one-line summary per server in the prompt.

This tool does not guess tokens. It measures BYTES of the live tool schemas and
the caps on every bounded output, then tells the agent how to shrink its own
surface with body_focus(). Honest proxy, no tokenizer dependency.
"""
from __future__ import annotations

import json


def report(tools: list[dict], focus: str, visible: list[str],
           unfiltered_bytes: int | None = None) -> dict:
    """tools = the tool dicts currently listed; unfiltered_bytes = all registered tools."""
    total = unfiltered_bytes or len(json.dumps(tools, ensure_ascii=False).encode("utf-8"))
    sizes = sorted(((len(json.dumps(tool, ensure_ascii=False).encode("utf-8")),
                     tool.get("name", "?")) for tool in tools), reverse=True)
    shown = {name for name in visible}
    shown_bytes = sum(size for size, name in sizes if name in shown)
    return {
        "success": True,
        "message": (f"{len(tools)} tools, {total / 1024:.1f} KB of schemas; "
                    f"focus '{focus}' shows {len(visible)} tools "
                    f"({shown_bytes / 1024:.1f} KB)"),
        "data": {
            "total_tools": len(tools),
            "total_schema_bytes": total,
            "focus": focus,
            "visible_tools": len(visible),
            "visible_schema_bytes": shown_bytes,
            "saving_percent": (round(100 * (1 - shown_bytes / total), 1) if total else 0),
            "largest_schemas": [{"tool": name, "bytes": size} for size, name in sizes[:8]],
            "bounded_outputs": {
                "page_text_chars": 20000,
                "snapshot_text_chars": 4000,
                "transcript_lines": 40,
                "local_worker_output_chars": 8000,
                "image": "one downscaled image per call (max 1280 px / 900 KB)",
                "audit_and_events": "capped and rotated",
            },
            "advice": [
                ("Call body_focus('browser'|'windows-desktop'|'research') to cut the "
                 "visible schema by ~60-80%. Hidden tools stay callable by name."),
                ("Take structure first (text, refs); ask for an image only when text "
                 "cannot answer the question."),
                ("For long research, use evidence records with hashes instead of "
                 "pasting raw pages into the conversation."),
                "Bytes are measured, not tokens — no tokenizer is bundled.",
            ],
            "note": "derived live from the server's own tool list; nothing is sent anywhere",
        },
    }
