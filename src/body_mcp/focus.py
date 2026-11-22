"""Progressive disclosure: narrow tools/list to a role, keep all tools callable.

Problem: 79 tool schemas flood the agent's context and make tool selection
worse (the exact reason an agent reached for webfetch instead of the body).

Solution: BodyMCPServer.list_tools() consults this module. By default NOTHING is
hidden, so existing clients and the 79-tool tests are unaffected. An agent can
call body_focus("browser"|"windows-desktop"|"research"|"all") and the server
re-lists only that set via notifications/tools/list_changed. This mirrors the
locked-tool-snapshot trick used by jcode/Claude Code: a small stable surface.

Hidden tools are NOT deleted and remain callable by name — focus is a view.
"""
from __future__ import annotations

# The always-visible control plane: an agent needs these whatever the role.
CORE = {
    "body_capabilities", "body_status", "body_events", "body_cancel",
    "body_focus", "reflex_verify", "reflex_ask", "body_workflow_note",
    "body_workflow_report", "body_lessons", "memory_search", "memory_write",
    "body_profile", "body_privacy_preflight",
}

FOCUS = {
    "all": None,  # None = no filtering (the default)
    "browser": {
        "eyes_see_browser", "hands_open", "hands_click", "hands_type",
        "hands_press", "hands_scroll", "hands_batch", "hands_parallel",
        "attach_browser", "list_tabs", "select_tab", "detach_browser",
        "browser_bridge", "body_windows", "body_open_external",
        "desktop_watch_start", "desktop_watch_read", "desktop_watch_stop",
        "desktop_monitors", "privacy_session_start", "privacy_session_open",
        "privacy_session_snapshot", "privacy_session_end",
    },
    "windows-desktop": {
        "eyes_see_desktop", "desktop_inspect", "desktop_click", "desktop_type",
        "desktop_read_value", "desktop_monitors", "legs_open_app",
        "desktop_watch_start", "desktop_watch_read", "desktop_watch_stop",
        "demo_learn", "body_speak", "body_stop_speaking", "body_voice_engines",
        "ears_listen", "body_windows",
    },
    "research": {
        "research_sources", "research_source", "research_any", "research_collect",
        "research_video", "research_youtube_search", "reflex_interview",
        "eyes_see_browser", "memory_search", "memory_write", "memory_note",
        "body_local_worker", "body_local_models", "body_local_worker",
        "body_privacy_preflight", "privacy_session_start", "privacy_session_open",
        "privacy_session_snapshot", "privacy_session_end", "privacy_vpn_connect",
    },
}

_current = "all"


def set_focus(mode: str) -> dict:
    if mode not in FOCUS:
        return {"ok": False,
                "reason": f"unknown focus {mode!r}; choose from {', '.join(FOCUS)}"}
    global _current
    before = _current
    _current = mode
    allow = FOCUS[mode]
    visible = None if allow is None else len(CORE | allow)
    return {"ok": True, "focus": mode, "previous": before,
            "visible": visible,
            "note": ("fewer tools are listed to the client; hidden tools remain "
                     "callable by name. Use body_focus('all') to restore.")}


def current() -> str:
    return _current


def visible_tools(names) -> list:
    """Filter an iterable of tool names for the current focus."""
    allow = FOCUS[_current]
    if allow is None:
        return list(names)
    keep = CORE | allow
    return [name for name in names if name in keep]


def search_tools(tools, query: str, k: int = 5) -> list[dict]:
    """Relevance-ranked tool discovery from names + descriptions (no external API).

    Idea from Anthropic's Tool Search (proprietary beta API); reimplemented here
    with the standard library so it stays local and free. `tools` is the list of
    MCP tool objects from list_tools().
    """
    words = [w for w in query.lower().replace("_", " ").split() if len(w) > 2]
    if not words:
        return []
    scored = []
    for tool in tools:
        name = (tool.name or "").lower()
        description = (tool.description or "").lower()
        hits = sum(1 for w in words if w in name or w in description)
        if hits:
            scored.append((hits, name, (tool.description or "").strip()[:160]))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [{"tool": name, "hits": hits, "why": why} for hits, name, why in scored[:k]]
