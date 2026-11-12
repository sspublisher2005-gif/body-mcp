"""Body-MCP server: eyes, ears, hands, legs, reflexes — gated by your permission profile.

The coding agent is the brain. Body-MCP is the body. Every action passes the
centralized permission layer (permissions.py); protected actions additionally
require a fresh reflex_ask() approval. Fail-closed everywhere.

Run:  python -m body_mcp.server   (stdio transport)
      python -m body_mcp.consent  (user consent + profile creation)
"""
import os
import platform

import anyio

try:
    from mcp.server.mcpserver import Context, MCPServer
except ImportError as exc:  # pragma: no cover - startup guard with a clear message
    raise SystemExit(
        "Body-MCP requires mcp>=2.0 (pip install -U 'mcp>=2,<3').\n"
        f"Original import error: {exc}"
    ) from exc

from . import (
    __version__,
    attach,
    batch,
    bridge,
    browser,
    config,
    demo,
    ears,
    events,
    eyes,
    interview,
    launch,
    lessons,
    local_worker,
    memory,
    models,
    permissions,
    privacy,
    reflex,
    registry,
    research,
    restrictions,
    roles,
    runtime,
    safety,
    skills,
    sources,
    sysprofile,
    tasks,
    tts,
    uia,
    undo,
    video,
    vision,
    watch,
    workflow,
)
from . import (
    console as console_mod,
)
from .hands import click, open_url, press, scroll, type_text
from .legs import open_app
from .parallel import run_parallel

mcp = MCPServer("Body-MCP")

TOOL_COUNT = 78


async def _registered_tool_count() -> int:
    """Ask the MCP server how many tools it actually exposes (no hardcoded drift)."""
    try:
        return len(await mcp.list_tools())
    except Exception:
        return TOOL_COUNT


async def _page_screenshot(private: bool = False) -> dict:
    """One downscaled screenshot of the current page (in memory, never stored)."""
    try:
        page = await browser.ensure_page()
        png = await page.screenshot(type="png", timeout=15000)
    except Exception as exc:
        return {"ok": False, "reason": f"screenshot failed: {type(exc).__name__}: {exc}"}
    return vision.prepare_image(png)


async def _with_page_screenshot(payload: dict, private: bool = False):
    """Attach a page screenshot to a result, keeping the structured payload."""
    prepared = await _page_screenshot(private=private)
    if not prepared.get("ok"):
        data = dict(payload.get("data") or {})
        data["image_error"] = prepared.get("reason")
        return {**payload, "data": data}
    permissions.record_audit("eyes_see_browser", "public_web", "allow",
                             "page screenshot", evidence={"bytes": prepared.get("bytes")})
    return vision.with_image(payload, prepared)


@mcp.tool()
async def eyes_see_browser(url: str | None = None, private: bool = False,
                           screenshot: bool = False) -> dict:
    """See the browser page: title, headings, visible text, links, buttons, inputs and forms.
    Interactive elements get stable refs (btn_1, input_2, link_3) usable by hands_*.
    If private=True: the URL is opened in a throwaway isolated context (fresh cookies/storage),
    read-only, refs omitted, context always closed — weaker local persistence, NOT anonymity.
    screenshot=True attaches ONE downscaled image of the page (vision mode, on request).
    Restricted pages (CAPTCHA, rate limit, paywall, access denial) are reported, never bypassed."""
    if private:
        allowed = permissions.check("private_browser", tool="eyes_see_browser",
                                    target=url or "?", risk="low",
                                    action="private read-only session")
        if not allowed.allowed:
            return {"success": False, "message": allowed.message,
                    "data": {"permission": allowed.decision}}
        verdict = browser.check_url(url or "")
        if not url or not verdict["ok"]:
            return {"success": False,
                    "message": "private mode requires an http/https/file URL you are allowed to open"
                               + (f" ({verdict.get('reason')})" if not verdict["ok"] else ""),
                    "data": {}}
        try:
            result = await browser.private_snapshot(url)
        except Exception as exc:
            return {"success": False,
                    "message": f"private snapshot failed: {type(exc).__name__}: {exc}", "data": {}}
        snap = result["snapshot"]
        hit = restrictions.classify(result["nav"]["status"], snap["text"], url,
                                    result["nav"]["retry_after"])
        permissions.record_audit("eyes_see_browser", "private_browser", "allow",
                                 permissions.redact_target(url))
        msg = "private read-only snapshot (refs omitted, session closed, nothing persisted)"
        if hit:
            msg = f"STOP — {hit['kind']}: {_restriction_summary(hit)}. Complete it manually or pick another source."
        events.emit(events.OBSERVATION, tool="eyes_see_browser", status="BLOCKED" if hit else None,
                    summary="private read-only observation",
                    evidence={"links": len(snap["links"]), "buttons": len(snap["buttons"]),
                              "inputs": len(snap["inputs"]), "private": True})
        payload = {"success": True, "message": msg,
                   "data": {**snap, "private": True, "http_status": result["nav"]["status"],
                            "restriction": hit}}
        if screenshot:
            return await _with_page_screenshot(payload, private=True)
        return payload

    if url:
        verdict = browser.check_url(url)
        if not verdict["ok"]:
            return {"success": False, "message": verdict["reason"], "data": {"url": url}}
        domain = restrictions.domain_of(url)
        remaining = await restrictions.cooldown_remaining(domain)
        if remaining > 0:
            return {"success": False,
                    "message": f"rate-limit cooldown active for {domain} (~{int(remaining)}s) — retry later",
                    "data": {"status": "retry_scheduled", "retry_after_s": int(remaining)}}
        try:
            await browser.polite_delay()
            await browser.ensure_page()
            await browser.goto_with_response(url, timeout_ms=30000)
            await browser.polite_delay()
        except Exception as exc:
            return {"success": False, "message": f"failed to open {url}: {type(exc).__name__}: {exc}",
                    "data": {"url": url}}
    else:
        # an attached user tab counts as "a page is open" — do not launch a managed
        # browser just to take a snapshot of nothing
        attached = attach.current_page()
        managed = browser._page
        has_page = ((attached is not None and not attached.is_closed())
                    or (managed is not None and not managed.is_closed()))
        if not has_page:
            return {"success": False,
                    "message": ("no browser page is open yet — call with a url (e.g. "
                                "eyes_see_browser('https://example.com')) or attach_browser() "
                                "to drive your own tab"),
                    "data": {}}
    snap = await browser.snapshot_page()
    hit = restrictions.classify(None, snap["text"], snap["url"])
    msg = "page read"
    if snap["restricted"]:
        msg = "STOP: " + browser.blocked_message()
    elif snap["sensitive_mode"]:
        msg = "sensitive page — do not read or type sensitive fields; ask the user to complete them"
    events.emit(events.OBSERVATION, tool="eyes_see_browser",
                status="BLOCKED" if snap["restricted"] else None,
                summary=f"observed {snap['title']!r}",
                evidence={"url": permissions.redact_target(snap["url"]),
                          "links": len(snap["links"]), "buttons": len(snap["buttons"]),
                          "inputs": len(snap["inputs"]),
                          "text_chars": len(snap["text"])})
    payload = {"success": True, "message": msg, "data": {**snap, "classification": hit}}
    if screenshot:
        return await _with_page_screenshot(payload)
    return payload


def _restriction_summary(hit: dict) -> str:
    return str(hit.get("evidence") or "restriction detected")


@mcp.tool()
async def eyes_see_desktop(monitor: int = 1, language: str = "eng",
                           region: list[int] | None = None, provider: str = "",
                           as_image: bool = False) -> dict:
    """See the desktop: capture a screen (or a region) and OCR its visible text.

    Screenshots are processed in memory and never written to disk. The OCR engine is
    discovered, never assumed: without one you get the exact install command instead of
    a silent failure. `region` = [left, top, width, height] in physical pixels.
    as_image=True attaches ONE downscaled image of the screen (vision mode, on request)."""
    allowed = permissions.check("desktop_capture", tool="eyes_see_desktop",
                                target=f"monitor {monitor}", risk="low",
                                action="capture and OCR the screen")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    try:
        return await anyio.to_thread.run_sync(
            lambda: eyes.see_desktop(monitor=monitor, language=language,
                                     region=tuple(region) if region else None,
                                     provider_name=provider or None, as_image=as_image))
    except Exception as exc:
        return {"success": False, "message": f"desktop capture failed: {type(exc).__name__}: {exc}",
                "data": {}}


@mcp.tool()
async def ears_listen(seconds: int = 8, stop_on_silence: bool = True) -> dict:
    """Hear the user through the microphone (push-to-talk).

    Records locally, transcribes locally, and NEVER stores or transmits raw audio.
    With stop_on_silence=True the recording ends shortly after the user stops talking
    (like a push-to-talk button); the transcript comes back with the fragments that
    were recognised with LOW confidence so you can ask the user to confirm them.
    The transcript is editable: send it, edit it, or ignore it."""
    allowed = permissions.check("mic", tool="ears_listen", target="default-microphone",
                                risk="low", action="record microphone")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = await anyio.to_thread.run_sync(
        lambda: ears.listen(seconds, stop_on_silence=stop_on_silence))
    return result


@mcp.tool()
async def hands_open(url: str) -> dict:
    """Open a URL in Chromium (http/https/file-under-CWD only; credentials-in-URL refused).
    Respects per-service rate-limit cooldowns and stops at access restrictions."""
    return await open_url(url)


@mcp.tool()
async def hands_batch(actions: list[dict], on_failure: str = "stop",
                      deadline_ms: int = 0, resume_from: str | None = None,
                      task_id: str | None = None) -> dict:
    """Execute a declared sequence of browser actions in ONE request.

    Actions: goto, click, fill, press, scroll, wait_for, verify_text, verify_url, screenshot.
    Validate-then-execute; stop on first failure (or on_failure='continue' for SAFE steps only);
    per-step and total timeouts; consequential clicks still require fresh approval per step;
    no JavaScript/Python/shell escape hatches; duplicate consequential submissions refused.

    Verification outcomes (in result): completed | failed | blocked | needs_user | retry_scheduled.
    Never reports success without verification evidence.

    resume_from=<checkpoint_id>: re-inspect the page and resume from the last verified step —
    never blindly replays; redacted steps need fresh explicit text.
    task_id=<id>: run as the SAME task (use the task_id from a previous needs_user result when
    re-running after approval — scoped approvals are bound to it).
    """
    if resume_from:
        result = await batch.resume_checkpoint(resume_from)
        _audit_batch("hands_batch", actions, result)
        return result
    deadline = deadline_ms if deadline_ms and deadline_ms > 0 else None
    page = await browser.ensure_page()
    result = await batch.execute_actions(
        page=page, actions=actions, resolver=batch.BatchResolver(page),
        allow_consequential=True, on_failure=on_failure,
        deadline_ms=deadline or config.batch_deadline_ms(),
        task_id=task_id or None)
    _audit_batch("hands_batch", actions, result)
    return result


def _audit_batch(tool: str, actions: list[dict], result: dict) -> None:
    """One audit record per batch/parallel task: what ran, how it ended, what it touched."""
    data = (result or {}).get("data", {}) or {}
    status = data.get("status") or ("completed" if (result or {}).get("success") else "failed")
    target = next((a.get("url") for a in actions or [] if a.get("type") == "goto"), "batch")
    needs_user = bool(data.get("needs_user"))
    permissions.record_audit(
        tool, "keyboard_mouse", "allow" if (result or {}).get("success") else "deny",
        target, status=status, task_id=data.get("task_id"),
        error_code=(data.get("failed_step") or {}).get("reason", "")[:80] or None,
        evidence={"steps": len(data.get("completed_steps") or []),
                  "actions_total": data.get("actions_total"),
                  "verification": (data.get("verification") or {}).get("status")},
        user_intervention=needs_user)


@mcp.tool()
async def hands_parallel(tasks: list[dict], max_concurrency: int = 0) -> dict:
    """Run INDEPENDENT browser tasks on isolated pages (default max 2 concurrent).

    tasks: [{"id"?, "actions": [<same schema as hands_batch>], "on_failure"?, "deadline_ms"?}]
    Rules: isolated contexts per task; NO snapshot refs across tasks (use unique visible
    text / label / placeholder / name); consequential actions are refused in parallel mode —
    run them via hands_batch with reflex_ask approval; per-service cooldowns are shared;
    per-task and overall deadlines; contexts always cleaned up.
    """
    result = await run_parallel(tasks, max_concurrency or None)
    for entry in (result.get("data", {}) or {}).get("results", []) or []:
        _audit_batch("hands_parallel", entry.get("actions", []) or [], entry)
    return result


@mcp.tool()
async def hands_click(target: str) -> dict:
    """Click a browser element by ref (btn_1/input_2/link_3) or unique visible text.
    Dangerous buttons require a fresh reflex_ask() approval — one approval, one click."""
    return await click(target)


@mcp.tool()
async def hands_type(field_ref: str, text: str) -> dict:
    """Clear and type into a field by ref (or unique label/placeholder/name).
    Refuses password/OTP/card fields — the user must type those."""
    return await type_text(field_ref, text)


@mcp.tool()
async def hands_press(key: str) -> dict:
    """Press a key or chord, e.g. 'Enter', 'Tab', 'Escape', 'Control+A'."""
    return await press(key)


@mcp.tool()
async def hands_scroll(direction: str, amount: int = 3) -> dict:
    """Scroll the browser page. direction: up|down. amount: 1-50."""
    return await scroll(direction, amount)


@mcp.tool()
async def attach_browser(endpoint: str, tab: str | None = None) -> dict:
    """Connect to your CURRENT Chrome/Edge tab via CDP (loopback only).

    Requires Chrome/Edge running with --remote-debugging-port (launch: python -m body_mcp.cdp_launch).
    Requires your acknowledged consent + a scoped reflex_ask approval for exactly this action.

    Without `tab`: lists your real tabs (index, title, url) and keeps the session open.
    With `tab`: attaches directly to that tab (index, or unique url/title substring).
    DevTools windows are never candidates; unselected tabs are never touched.
    The CDP port is unauthenticated-loopback: detach when done and restart the browser normally.
    """
    verdict = attach._valid_endpoint(endpoint)
    if not verdict["ok"]:
        return {"success": False, "message": verdict["reason"], "data": {}}
    return await attach.attach(endpoint, tab=tab)


@mcp.tool()
async def list_tabs() -> dict:
    """List the candidate tabs of an ALREADY-ATTACHED CDP session (index/title/url only).
    Read-only; requires nothing beyond a completed attach_browser()."""
    if not attach._attach.get("page") and not attach._attach.get("candidate_pages"):
        return {"success": True,
                "message": "not attached — attach_browser() first",
                "data": {"tabs": []}}
    if attach._attach.get("page"):
        snap = attach.attached_status()
        return {"success": True, "message": f"attached to {snap.get('title', 'tab')}", "data": snap}
    tabs = await attach._current_tabs_info()
    return {"success": True, "message": f"{len(tabs)} candidate tab(s)", "data": {"tabs": tabs}}


@mcp.tool()
async def select_tab(selector: str) -> dict:
    """Select one tab after attach_browser(). Requires its own scoped reflex_ask approval.
    selector: the index from list_tabs(), or a unique url/title substring."""
    return await attach.select_tab(selector)


@mcp.tool()
async def detach_browser() -> dict:
    """Disconnect the CDP bridge. NEVER closes your browser or tabs.
    Restart the browser normally afterwards to drop the debug port."""
    return await attach.detach()


@mcp.tool()
async def memory_search(query: str = "", scope: str = "", project: str = "",
                        limit: int = 20, include_unverified: bool = True) -> dict:
    """Search persistent local memory (project notes, verified fixes, limitations, preferences).

    Memory is a local SQLite file - nothing leaves this machine. Unverified entries are
    proposals, not facts; pass include_unverified=False to get only verified ones."""
    allowed = permissions.check("memory", tool="memory_search", target=scope or query[:80],
                                risk="low", action="search memory")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    items = memory.search(query=query, scope=scope or None, project=project,
                           limit=limit, include_unverified=include_unverified)
    return {"success": True, "message": f"{len(items)} memory entr(y/ies)",
            "data": {"items": items, "count": len(items), "stats": memory.stats()}}


@mcp.tool()
async def memory_write(title: str, content: str, scope: str = "project",
                       type: str = "note", tags: list[str] | None = None,
                       source: str = "", confidence: float = 0.5, verified: bool = False,
                       project: str = "") -> dict:
    """Store one durable memory.

    Scopes: project | workflow | capability | user | knowledge | research.
    Credentials are refused - store the fact, never the secret. Use verified=True only
    when you actually verified the claim."""
    capability = "user_preferences" if scope == "user" else "memory"
    allowed = permissions.check(capability, tool="memory_write", target=title[:80],
                                risk="low", action=f"write memory ({scope})")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = memory.add(title=title, content=content, scope=scope, project=project,
                        tags=tags or [], type=type, source=source,
                        confidence=confidence, verified=verified)
    permissions.record_audit("memory_write", capability, "allow" if result["success"] else "deny",
                             title)
    return result


@mcp.tool()
async def memory_list(scope: str = "", project: str = "", limit: int = 50) -> dict:
    """List stored memories, newest first, optionally filtered by scope/project."""
    allowed = permissions.check("memory", tool="memory_list", target=scope or "all",
                                risk="low", action="list memory")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    items = memory.list_scope(scope=scope or None, project=project, limit=limit)
    return {"success": True, "message": f"{len(items)} memory entr(y/ies)",
            "data": {"items": items, "count": len(items)}}


@mcp.tool()
async def memory_delete(memory_id: str = "", scope: str = "") -> dict:
    """Delete one memory by id, or every memory in a scope (destructive)."""
    allowed = permissions.check("memory", tool="memory_delete", target=memory_id or scope,
                                risk="low", action="delete memory")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    if memory_id:
        removed = memory.delete(memory_id)
        permissions.record_audit("memory_delete", "memory", "allow" if removed else "deny", memory_id)
        return {"success": removed, "message": "memory deleted" if removed else "no such memory",
                "data": {"id": memory_id}}
    if scope:
        count = memory.clear(scope)
        permissions.record_audit("memory_delete", "memory", "allow", f"scope:{scope}")
        return {"success": True, "message": f"cleared {count} memory entr(y/ies) in scope {scope!r}",
                "data": {"scope": scope, "removed": count}}
    return {"success": False, "message": "give memory_id or scope (clearing everything needs a scope)",
            "data": {}}


@mcp.tool()
async def memory_export(scope: str = "", project: str = "") -> dict:
    """Export memories as JSON and Markdown (readable, portable, local)."""
    allowed = permissions.check("memory", tool="memory_export", target=scope or "all",
                                risk="low", action="export memory")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return {"success": True, "message": "memory exported",
            "data": memory.export(scope=scope or None, project=project)}


@mcp.tool()
async def body_privacy_preflight(show_ip: bool = False) -> dict:
    """Check the privacy posture BEFORE a private session starts.

    Reports: which browsers are installed, whether the VPN app is installed and
    open, whether a LOCAL model is configured, the free RAM, and the warnings -
    including the one about your reasoning model still being remote (a warning,
    never a block). It changes nothing and asks for no IP unless you ask for it."""
    allowed = permissions.check("private_browser", tool="body_privacy_preflight",
                                target="preflight", risk="low",
                                action="check the privacy posture")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return {"success": True, "message": "privacy preflight",
            "data": privacy.preflight(show_ip=show_ip)}


@mcp.tool()
async def privacy_session_start(label: str = "session", mode: str = "standard",
                                browser: str = "chromium", vpn: bool = False,
                                assistant: bool = False, show_ip: bool = False,
                                keep_content_local: bool = False) -> dict:
    """Start a privacy session (own throwaway browser context - nothing persisted).

    mode='standard'  isolated context (incognito-equivalent).
    mode='private'   the same isolation plus: the VPN you asked for (call
                      privacy_vpn_connect() - it opens and connects the app, with your
                      approval), Brave (or Chromium) as the engine in a private window,
                      and the AI assistant (Venice AI) opened first as the research tab
                      while the real sites stay in a second tab. Call
                      body_privacy_preflight() first: it reports what is installed, what
                      is running, and what you should switch on.

    keep_content_local=True  the page TEXT stays on this machine: it is redacted and
                      summarised by a local model and only that comes back. It needs a
                      local model (Ollama + `ollama pull qwen3:0.6b`); without one the
                      text is withheld rather than sent to your model provider.

    Nothing from this session is written to persistent memory, the audit log or the
    event stream. It reduces local persistence only - it is NOT anonymity: websites,
    network operators, device administrators and downloaded files can still observe it."""
    allowed = permissions.check("private_browser", tool="privacy_session_start",
                                target=label, risk="low", action="start a privacy session")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return privacy.start(label, mode=mode, browser=browser, vpn=vpn,
                         assistant=assistant, show_ip=show_ip,
                         keep_content_local=keep_content_local)


@mcp.tool()
async def privacy_session_open(session_id: str, url: str) -> dict:
    """Open a URL inside a privacy session. Access controls are still enforced -
    a login, CAPTCHA or paywall stops the session, it is never bypassed."""
    allowed = permissions.check("private_browser", tool="privacy_session_open",
                                target=session_id, risk="low", action="open a page in a privacy session")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return await privacy.open(session_id, url)


@mcp.tool()
async def privacy_session_snapshot(session_id: str) -> dict:
    """Read the current page of a privacy session (bounded text, no refs, not stored)."""
    allowed = permissions.check("private_browser", tool="privacy_session_snapshot",
                                target=session_id, risk="low", action="read a privacy session page")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return await privacy.snapshot(session_id)


@mcp.tool()
async def privacy_session_end(session_id: str) -> dict:
    """End a privacy session: close its context, discard its cookies/storage and
    VERIFY the cleanup. Your ordinary browser profile is never touched."""
    allowed = permissions.check("private_browser", tool="privacy_session_end",
                                target=session_id, risk="low", action="end a privacy session")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return await privacy.end(session_id)


@mcp.tool()
async def memory_note(filename: str, markdown: str) -> dict:
    """Write a human-editable Markdown note (project instructions, conventions).

    Notes live in <config>/notes/*.md, are included in memory_search, and can be
    edited directly in your editor. Credentials are refused."""
    allowed = permissions.check("memory", tool="memory_note", target=filename[:80],
                                risk="low", action="write a markdown note")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return memory.write_note(filename, markdown)


@mcp.tool()
async def desktop_watch_start(monitor: int = 1, interval: float = 3.0,
                              language: str = "eng", region: list[int] | None = None,
                              provider: str = "") -> dict:
    """Start a LIVE desktop observation session (explicit user request only).

    The screen is sampled every `interval` seconds and OCR'd only when the frame
    actually changed, so an idle screen costs almost nothing. OCR runs off the MCP
    event loop. Screen content is returned on request and NEVER written to disk,
    the audit log or memory. Poll desktop_watch_read() for the latest observation
    (MCP has no push channel) - the console shows the same events."""
    allowed = permissions.check("desktop_capture", tool="desktop_watch_start",
                                target=f"monitor {monitor}", risk="low",
                                action="start a live desktop observation session")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = watch.start(monitor=monitor, interval=interval, language=language,
                         region=region, provider=provider or None)
    if result.get("success"):
        permissions.record_audit("desktop_watch_start", "desktop_capture", "allow",
                                 f"monitor {monitor}", status="STARTED",
                                 task_id=result["data"]["task_id"])
    return result


@mcp.tool()
async def desktop_watch_read(session_id: str = "", since: float = 0,
                               as_image: bool = False) -> dict:
    """Read the latest observation of a live desktop session.

    Returns the recognised screen text (bounded), when it was observed, whether it
    changed since `since`, and how many frames were skipped as unchanged."""
    allowed = permissions.check("desktop_capture", tool="desktop_watch_read",
                                target=session_id or "session", risk="low",
                                action="read the latest desktop observation")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    payload = watch.read(session_id or None, since=since)
    if not as_image:
        return payload
    frame = watch.last_frame(session_id or None)
    if not frame:
        data = dict(payload.get("data") or {})
        data["image_error"] = "no frame captured yet"
        return {**payload, "data": data}
    prepared = vision.prepare_image(frame)
    if not prepared.get("ok"):
        data = dict(payload.get("data") or {})
        data["image_error"] = prepared.get("reason")
        return {**payload, "data": data}
    return vision.with_image(payload, prepared)


@mcp.tool()
async def desktop_watch_stop(session_id: str = "") -> dict:
    """Stop a live desktop observation session and release its resources."""
    allowed = permissions.check("desktop_capture", tool="desktop_watch_stop",
                                target=session_id or "session", risk="low",
                                action="stop a live desktop observation session")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = watch.stop(session_id or None)
    if result.get("success"):
        permissions.record_audit("desktop_watch_stop", "desktop_capture", "allow",
                                 session_id or "session", status="STOPPED")
    return result


@mcp.tool()
async def browser_bridge(action: str = "status", url: str = "") -> dict:
    """Drive the browser the USER has open, through their extension.

    action: status | connect | tabs | navigate | read | screenshot | disconnect.
    The user connects a tab in the extension (one click, with Chromium's own
    "debugging this browser" bar); Body-MCP then acts only on that tab.
    Nothing is read or navigated before the user connects it."""
    allowed = await permissions.authorize(
        "chrome_attach", tool="browser_bridge", target=action, risk="low",
        action=f"extension bridge: {action}", url=url or None, task_id=None)
    if not allowed.allowed:
        permissions.record_audit("browser_bridge", "chrome_attach", allowed.decision, action)
        spec = permissions.required_action_spec("browser_bridge", "chrome_attach", action,
                                                 url or None, None)
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision, "required_action": spec}}
    result = await bridge.action(action, url=url)
    data = dict(result)
    ok = bool(result.get("ok"))
    message = {
        "status": "the extension bridge state",
        "connect": "waiting for the user to connect a tab in the extension",
        "tabs": "the tabs the extension offers",
        "navigate": "the connected tab was asked to navigate",
        "read": "the connected tab was read",
        "screenshot": "a screenshot of the connected tab was requested",
        "disconnect": "the extension was disconnected",
    }.get(action, "bridge action finished")
    if not ok:
        message = result.get("error") or message
    return {"success": ok, "message": message, "data": data}


@mcp.tool()
async def body_open_external(url: str, browser: str = "") -> dict:
    """Open a URL in the USER'S OWN browser (a new tab), not in Body-MCP's browser.

    Use it when the task says "open it in my browser". browser: "" = the operating
    system default, or one of chrome | edge | brave | firefox to pick the browser
    explicitly. Only http/https are handed over (no shell, no command strings) and the
    browser executable comes from a fixed table. Body-MCP's own Chromium stays
    separate - it is the controlled one."""
    allowed = permissions.check("public_web", tool="body_open_external",
                                target=permissions.redact_target(url), risk="low",
                                action="open a URL in the default browser")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return launch.open_external(url, browser=browser)


@mcp.tool()
async def body_local_models(role: str = "worker", uncensored: bool = False,
                            multilingual: bool = False) -> dict:
    """The local-model catalogue and what THIS machine can run.

    Sizes and SHA-256 are the published ones, so a download can be verified before
    it is used. The ranking uses the measured free RAM - it never suggests a model
    that would not fit. Nothing is downloaded: you choose, you fetch it, you point
    BODY_MCP_LOCAL_MODEL at it."""
    allowed = permissions.check("model_selection", tool="body_local_models", target=role,
                                risk="low", action="list local model options")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    from . import sysprofile

    try:
        ram = sysprofile.summary().get("ram_available_mb")
    except Exception:
        ram = None
    ranked = models.recommend(free_ram_mb=ram, role=role, uncensored=uncensored,
                              multilingual=multilingual)
    top = ranked[0] if ranked else None
    return {"success": True,
            "message": (f"{len(models.MODELS)} models known; "
                        + (f"{top['name']} fits this machine"
                           if top and top["fits"] else
                           "none of them fits this machine right now - close a browser "
                           "or add RAM (the report says how much is short)")),
            "data": {"catalogue": models.catalogue(),
                     "recommended_for_this_machine": ranked,
                     "free_ram_mb": ram,
                     "configured": models.configured_model(),
                     "worker": local_worker.status(),
                     "runtimes": {"ollama": "one command, no compiler: `ollama pull <tag>`",
                                  "llama.cpp": "download the GGUF (URL + SHA-256 in the "
                                               "catalogue), then pip install llama-cpp-python"},
                     "note": "the model is a PRIVATE WORKER (extraction, dedup, scrubbing, "
                             "short summaries); the agent's own model stays the reasoner"}}


@mcp.tool()
async def body_local_worker(task: str = "summarise", text: str = "") -> dict:
    """Process text ON THIS MACHINE with a local model. Nothing leaves the box.

    task: summarise | extract | redact | key | classify
    text: the text to process.

    This is the private mode's content half: the page text goes to a model running
    on your machine, so only a short redacted summary ever leaves. It needs Ollama
    (`ollama pull qwen3:0.6b`) or a GGUF via BODY_MCP_LOCAL_MODEL - Body-MCP never
    downloads a model and NEVER falls back to a remote provider: with no local
    model it says so and stops."""
    allowed = permissions.check("model_selection", tool="body_local_worker", target=task,
                                risk="low", action="process text with a local model")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    if task not in local_worker.TASKS:
        return {"success": False,
                "message": f"unknown task {task!r}; use one of {list(local_worker.TASKS)}",
                "data": {}}
    if not (text or "").strip():
        return {"success": False, "message": "no text to process", "data": {}}
    import asyncio

    result = await asyncio.to_thread(local_worker.run, task, text)
    if not result.get("ok"):
        return {"success": False, "message": result.get("reason", "the local worker failed"),
                "data": {"local": False, "worker": local_worker.status()}}
    return {"success": True,
            "message": (f"processed locally with {result.get('model')} "
                        f"({result.get('runtime')}, {result.get('duration_ms')} ms) - "
                        "the text never left this machine"),
            "data": {"task": task, "local": True, "model": result.get("model"),
                     "runtime": result.get("runtime"),
                     "duration_ms": result.get("duration_ms"),
                     "output": result.get("text", "")[:8000]}}


@mcp.tool()
async def privacy_vpn_connect(app: str = "proton") -> dict:
    """Open the VPN app and ask it to connect (Proton VPN on Windows).

    The agent clicks the app's OWN connect button and then reads the window, so the
    reported state comes from the app - 'unknown' is reported instead of a guess.
    It never switches servers or rotates IPs to evade a block.

    Needs the vpn_control permission, which is 'deny' by default: add
    "vpn_control": "allow" to your permissions.json (a USER edit) to enable it."""
    allowed = permissions.check("vpn_control", tool="privacy_vpn_connect", target=app,
                                risk="high", action=f"control the {app} VPN app")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    import anyio

    result = await anyio.to_thread.run_sync(lambda: privacy.vpn_connect(app))
    permissions.record_audit("privacy_vpn_connect", "vpn_control", "allow", app,
                             status="CONNECTED" if result.get("data", {}).get("verified")
                             else "UNCONFIRMED")
    return result


@mcp.tool()
async def body_windows() -> dict:
    """See which windows are open right now (titles only - no content, no screenshots).

    This is read-only and needs no debug port, so it works even for a browser you
    started yourself. It CANNOT drive those windows: for that the browser needs a
    sanctioned connection (a debug port on a separate profile, or the extension bridge)."""
    allowed = permissions.check("desktop_capture", tool="body_windows", target="windows",
                                risk="low", action="list the visible windows")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    from . import windows as windows_module

    result = windows_module.browser_windows()
    if not result.get("ok"):
        return {"success": False, "message": result.get("reason"), "data": {}}
    return {"success": True,
            "message": f"{len(result.get('browsers', []))} browser window(s) visible",
            "data": {"browsers": result.get("browsers", []), "note": result.get("note")}}


@mcp.tool()
async def desktop_monitors() -> dict:
    """List the connected screens and which OCR engines are usable on this machine."""
    allowed = permissions.check("desktop_capture", tool="desktop_monitors", target="screens",
                                risk="low", action="list screens and OCR engines")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    from . import eyes

    return {"success": True, "message": "screens and OCR engines",
            "data": {"screens": eyes.monitors(), "ocr": eyes.ocr_status()}}


@mcp.tool()
async def body_voice_engines() -> dict:
    """Which speech-to-text and text-to-speech engines this machine can use.

    Nothing is downloaded and nothing is loaded: this only reports what is already
    installed, which model files are present, and what each engine would cost in
    memory. The default text-to-speech engine is the Windows system voice."""
    from . import voice

    stt = voice.providers()
    tts_info = tts.available()
    return {"success": True,
            "message": f"speech-to-text: {voice.select()[0] or 'none installed'}; "
                       f"text-to-speech: {tts_info.get('engine') or 'none available'}",
            "data": {"speech_to_text": stt,
                     "selected_stt": voice.select()[0],
                     "text_to_speech": tts_info,
                     "free_ram_mb": voice.available_ram_mb(),
                     "note": "no engine is downloaded automatically; install one yourself "
                             "if you want it"}}


@mcp.tool()
async def body_speak(text: str, voice: str = "") -> dict:
    """Speak text with the LOCAL system voice (Windows SAPI - no download, no network).

    Playback runs in the background and can be stopped with body_stop_speaking().
    Typed chat stays fully usable without this; the tool never sends audio anywhere."""
    allowed = permissions.check("mic", tool="body_speak", target="local tts",
                                risk="low", action="speak text locally")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return tts.speak(text, voice=voice or None)


@mcp.tool()
async def body_stop_speaking() -> dict:
    """Stop the local speech playback started by body_speak()."""
    return tts.stop()


@mcp.tool()
async def body_profile(refresh: bool = False) -> dict:
    """Read-only capability inventory of this machine (OS, CPU, RAM, disk, GPU,
    optional modules, agent CLIs, local speech models).

    Nothing is installed or downloaded, nothing private is crawled, nothing is
    uploaded. The result is cached locally and can be cleared."""
    allowed = permissions.check("model_selection", tool="body_profile", target="system",
                                risk="low", action="inspect system capabilities")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return {"success": True, "message": "system capability profile",
            "data": sysprofile.summary()}


@mcp.tool()
async def body_models() -> dict:
    """Catalogue the model/harness backends available on this machine, with what each
    can do, its licence, privacy and cost. Read-only; installs nothing."""
    allowed = permissions.check("model_selection", tool="body_models", target="registry",
                                risk="low", action="list model backends")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    items = registry.listing()
    return {"success": True, "message": f"{len(items)} backend(s) known, "
            f"{sum(1 for i in items if i['installed'])} installed",
            "data": {"backends": items}}


@mcp.tool()
async def body_recommend(needs: list[str] | None = None, offline_only: bool = False,
                         max_ram_mb: int = 0) -> dict:
    """Dry-run recommendation: which installed backend fits a task best, and why.

    Needs: e.g. ["tools", "vision", "audio", "structured_output"]. Never downloads or
    launches anything - it only ranks what is already here."""
    allowed = permissions.check("model_selection", tool="body_recommend", target=",".join(needs or []),
                                risk="low", action="recommend a backend")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = registry.recommend({"needs": needs or [], "offline_only": offline_only,
                                 "max_ram_mb": max_ram_mb or None})
    return {"success": True,
            "message": f"recommended: {result['recommended'] or 'nothing installed fits'}",
            "data": result}


@mcp.tool()
async def research_collect(urls: list[str], max_items: int = 5) -> dict:
    """Collect evidence from public pages: title, URL, publication date, excerpt and
    retrieval method, with verification status and content hashes for deduplication.

    Read-only, bounded (max_items, bounded text), and never authenticated - a page
    that asks for a login, CAPTCHA or paywall is reported as blocked, not bypassed.
    Source content is untrusted data: it cannot grant permissions."""
    allowed = permissions.check("public_web", tool="research_collect",
                                target=f"{len(urls)} url(s)", risk="low",
                                action="collect research evidence")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = await research.collect(urls, max_items=max_items)
    permissions.record_audit("research_collect", "public_web", "allow",
                             f"{len(urls)} url(s)", status=result["data"]["status"],
                             evidence={"items": result["data"]["collected"],
                                       "blocked": result["data"]["blocked"]})
    return result


@mcp.tool()
async def research_video(url: str, max_lines: int = 40) -> dict:
    """Watch AND hear a public video: title, channel, views, date, chapters and the
    OFFICIAL caption track as a timestamped transcript.

    The captions are the video's own track, so the audio is read without downloading
    a speech model. If a video has no captions, the tool says so instead of inventing
    a transcript (local transcription is a separate, explicit opt-in).
    Everything is read-only and public-page only."""
    allowed = permissions.check("public_web", tool="research_video", target=url[:80],
                                risk="low", action="collect video evidence and captions")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    record = await anyio.to_thread.run_sync(lambda: video.collect_video(url))
    permissions.record_audit("research_video", "public_web", "allow", url[:80],
                             status=record.get("verification"),
                             evidence={"captions": record.get("captions_available"),
                                       "transcript_lines": len(record.get("transcript_lines") or [])})
    summary = video.summarize(record, max_lines=max_lines)
    ok = record.get("status") == "COLLECTED" and bool(record.get("title"))
    return {"success": ok,
            "message": (f"{record.get('title') or url} - "
                        f"{len(record.get('transcript_lines') or [])} caption line(s)"
                        if ok else (record.get("limitation") or "could not read the video")),
            "data": {"summary": summary, "record": record}}


@mcp.tool()
async def body_workflow_start(goal: str) -> dict:
    """Open an execution ledger for one goal: EYES -> BRAIN -> HANDS -> VERIFY.

    Record every step with body_workflow_note(): what you SAW (observation), what you
    DECIDED and why (decision), what the body DID (action), what PROVED it worked
    (verification). The ledger is what the final report is built from - evidence
    instead of memory. The decision stays yours; the body only records it."""
    return workflow.start(goal)


@mcp.tool()
async def body_workflow_note(workflow_id: str, kind: str, text: str,
                             evidence: dict | None = None) -> dict:
    """Add one step to the workflow ledger.

    kind: observation | decision | action | verification | blocker | lesson | note | approval.
    Write the decision BEFORE the action, and the verification AFTER it - that order is
    what makes the run auditable."""
    return workflow.note(workflow_id, kind, text, evidence)


@mcp.tool()
async def body_workflow_report(workflow_id: str = "") -> dict:
    """The evidence-backed report of a workflow (empty id = the latest one).

    Shows the goal, what was observed, what was decided, what was done, what was
    verified and what blocked it - so the final answer cites evidence, not impressions."""
    return workflow.report(workflow_id)


@mcp.tool()
async def body_lessons(tool: str = "", error_code: str = "", limit: int = 10) -> dict:
    """What we already learned from failures - read it BEFORE repeating an attempt.

    Every failed action leaves a proposed lesson (root cause + likely fix). These are
    the lessons that apply to a tool or an error code, newest first."""
    items = lessons.lessons(tool=tool, error_code=error_code, limit=limit)
    return {"success": True,
            "message": f"{len(items)} lesson(s) apply",
            "data": {"lessons": items, "summary": lessons.summary(),
                     "hints": {code: hint for code, hint in lessons.HINTS.items()}}}


@mcp.tool()
async def desktop_inspect(title: str = "") -> dict:
    """Look inside a native Windows window: its controls (name, type, position, state).

    This is the desktop equivalent of eyes_see_browser - it reads the real UI tree
    through Windows UI Automation, so controls are found by their visible name.
    Reading is allowed; acting on the window needs the desktop_control permission."""
    allowed = permissions.check("desktop_capture", tool="desktop_inspect", target=title[:60],
                                risk="low", action="inspect a desktop window")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    if not title:
        return {"success": False,
                "message": "name the window (a part of its title) - Body-MCP never touches an "
                           "unnamed window",
                "data": {}}
    result = await anyio.to_thread.run_sync(lambda: uia.inspect(title))
    if not result.get("ok"):
        return {"success": False, "message": result.get("reason"), "data": {}}
    return {"success": True,
            "message": f"{result['count']} control(s) in {result['window']!r}",
            "data": {"window": result["window"], "controls": result["controls"]}}


@mcp.tool()
async def desktop_click(title: str, control: str) -> dict:
    """Click a control in a native Windows window, by its visible name.

    Uses UI Automation's Invoke pattern - not blind coordinates - so nothing is
    clicked by accident. Needs the desktop_control permission (default: ask)."""
    allowed = await permissions.authorize(
        "desktop_control", tool="desktop_click", target=f"{title[:40]}/{control[:40]}",
        risk="high", action=f"click {control!r} in the window {title!r}")
    if not allowed.allowed:
        permissions.record_audit("desktop_click", "desktop_control", allowed.decision,
                                 f"{title[:40]}/{control[:40]}")
        spec = permissions.required_action_spec("desktop_click", "desktop_control",
                                                 f"{title[:40]}/{control[:40]}")
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision, "required_action": spec}}
    result = await anyio.to_thread.run_sync(lambda: uia.click(title, control))
    if not result.get("ok"):
        return {"success": False, "message": result.get("reason"), "data": {}}
    return {"success": True, "message": f"clicked {result.get('clicked')!r} in "
                                        f"{result.get('window')!r}",
            "data": result}


@mcp.tool()
async def desktop_type(title: str, control: str, text: str) -> dict:
    """Type into a field of a native Windows window, by its visible name.

    Password-like fields are refused - the user types those. Needs the
    desktop_control permission (default: ask)."""
    allowed = await permissions.authorize(
        "desktop_control", tool="desktop_type", target=f"{title[:40]}/{control[:40]}",
        risk="high", action=f"type into {control!r} in the window {title!r}")
    if not allowed.allowed:
        permissions.record_audit("desktop_type", "desktop_control", allowed.decision,
                                 f"{title[:40]}/{control[:40]}")
        spec = permissions.required_action_spec("desktop_type", "desktop_control",
                                                 f"{title[:40]}/{control[:40]}")
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision, "required_action": spec}}
    result = await anyio.to_thread.run_sync(lambda: uia.type_text(title, control, text))
    if not result.get("ok"):
        return {"success": False, "message": result.get("reason"), "data": {}}
    return {"success": True,
            "message": f"typed {result.get('typed')} characters into {result.get('into')!r}",
            "data": result}


@mcp.tool()
async def desktop_read_value(title: str, control: str) -> dict:
    """Read the current value of a field in a native window (the verification step)."""
    allowed = permissions.check("desktop_capture", tool="desktop_read_value",
                                target=f"{title[:40]}/{control[:40]}", risk="low",
                                action="read a field of a desktop window")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = await anyio.to_thread.run_sync(lambda: uia.read_value(title, control))
    if not result.get("ok"):
        return {"success": False, "message": result.get("reason"), "data": {}}
    return {"success": True, "message": f"value: {result.get('value')!r}", "data": result}


@mcp.tool()
async def research_youtube_search(query: str, limit: int = 8) -> dict:
    """Find reference videos: search YouTube and return title, channel, views, age and
    whether an official caption track exists.

    Use it to learn how something is done (a style, a workflow, a talk) before you
    act - the body fetches the evidence, the agent decides what to copy and what to
    ignore. Read-only; nothing is played or downloaded."""
    allowed = permissions.check("public_web", tool="research_youtube_search",
                                target=query[:80], risk="low",
                                action="search YouTube for reference material")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = await anyio.to_thread.run_sync(
        lambda: video.youtube_search(query, limit=limit))
    return {"success": True,
            "message": f"{result['count']} result(s) for {query!r}",
            "data": {"results": result["results"], "note": result["note"]}}


@mcp.tool()
async def research_sources() -> dict:
    """Which platforms the body can actually research, and which are blocked.

    Every readable source is a public, documented, key-free endpoint (read-only,
    rate-limited, no login). Blocked ones say why - no silent substitution."""
    return {"success": True, "message": "the research source matrix",
            "data": {"sources": sources.matrix(),
                     "note": "read-only evidence; the agent decides what it means"}}


@mcp.tool()
async def research_source(source: str, query: str, limit: int = 8) -> dict:
    """Search ONE research source and get evidence records.

    source: hackernews | reddit | github_issues | stackoverflow | wikipedia | youtube.
    Each record: title, url, author, date, score/comments, excerpt, retrieval method
    and the limitation that applies. A blocked source returns the reason, never a
    substitute."""
    allowed = permissions.check("public_web", tool="research_source",
                                target=f"{source}:{query[:60]}", risk="low",
                                action=f"search {source} for {query[:60]!r}")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = await anyio.to_thread.run_sync(
        lambda: sources.search(source, query, limit=limit))
    permissions.record_audit("research_source", "public_web",
                             "allow" if result.get("success") else "deny",
                             f"{source}:{query[:60]}",
                             status="COLLECTED" if result.get("success") else "BLOCKED",
                             evidence={"items": result.get("count", 0),
                                       "reason": (result.get("reason") or "")[:120]})
    return {"success": bool(result.get("success")),
            "message": (f"{result.get('count', 0)} record(s) from {source}"
                        if result.get("success") else
                        (result.get("reason") or f"{source} returned nothing")),
            "data": result}


@mcp.tool()
async def reflex_interview(questions: list[str] | None = None, ctx: Context = None,
                           title: str = "") -> dict:
    """Ask the user several questions at once and get the answers back.

    Use it before building anything: budget, category, what went wrong with the
    tools you already tried, light vs heavy, must-haves, must-nevers. With no
    questions given, the standard Body-MCP set is used."""
    allowed = permissions.check("public_web", tool="reflex_interview", target="interview",
                                risk="low", action="interview the user")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return await interview.interview(questions or interview.question_set(), ctx=ctx, title=title)


@mcp.tool()
async def body_task_start(actions: list[dict]) -> dict:
    """Start a LONG batch in the background and get a task id straight away.

    The agent keeps working while the body carries on (own isolated context, never
    the page you are using). Poll body_task_status(task_id) for progress, or
    body_task_cancel(task_id) to stop it. Small jobs should just use hands_batch -
    this is for the slow ones."""
    allowed = permissions.check("keyboard_mouse", tool="body_task_start",
                                target=f"{len(actions or [])} action(s)", risk="low",
                                action="start a background batch")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = tasks.start(actions or [])
    if result.get("success"):
        permissions.record_audit("body_task_start", "keyboard_mouse", "allow",
                                 f"{len(actions or [])} action(s)", status="STARTED",
                                 task_id=result["data"]["task_id"])
    return result


@mcp.tool()
async def body_task_status(task_id: str = "") -> dict:
    """Progress of a background task: steps done, percent, elapsed, last evidence."""
    if task_id:
        return tasks.status(task_id)
    listing = tasks.list_tasks()
    if not listing:
        return {"success": True, "message": "no background tasks", "data": {"tasks": []}}
    return {"success": True, "message": f"{len(listing)} background task(s)",
            "data": {"tasks": listing}}


@mcp.tool()
async def body_task_cancel(task_id: str) -> dict:
    """Cancel a background task (it stops at the next step boundary)."""
    return tasks.cancel(task_id)


@mcp.tool()
async def body_undo() -> dict:
    """Undo the most recent reversible change (a typed value, a navigation).

    Irreversible steps are NOT undone - the journal says so instead of pretending."""
    return await undo.undo_last()


@mcp.tool()
async def body_undo_list(limit: int = 10) -> dict:
    """What the body changed and whether it can be undone."""
    items = undo.entries(limit=limit)
    return {"success": True, "message": f"{len(items)} journal entr(y/ies)",
            "data": {"journal": items,
                     "undoable": sum(1 for item in items if item.get("undoable"))}}


@mcp.tool()
async def body_skill_save(name: str, goal: str, steps: list[dict], why: str = "",
                          verified: bool = False, tags: list[str] | None = None) -> dict:
    """Save a procedure you learned from your own work, so it can be replayed.

    steps: the same action schema hands_batch uses (click/type/fill/goto/verify...).
    why: what you learned and why it works - this is the part that makes it a skill
    and not a script. verified: only true if the result was actually checked.
    An unverified skill stays a proposal and is never replayed blindly."""
    allowed = permissions.check("memory", tool="body_skill_save", target=name[:80],
                                risk="low", action="save a skill")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = skills.save(name=name, goal=goal, steps=steps, why=why, verified=verified,
                         tags=tags)
    if result.get("success"):
        permissions.record_audit("body_skill_save", "memory", "allow", name[:80],
                                 status="SAVED", task_id=result["data"].get("id"))
    return result


@mcp.tool()
async def body_skill_list(limit: int = 20) -> dict:
    """The skills we know: name, goal, why, steps and whether they were verified."""
    items = skills.list_skills(limit=limit)
    return {"success": True, "message": f"{len(items)} skill(s)",
            "data": {"skills": items, "summary": skills.summary()}}


@mcp.tool()
async def body_skill_replay(skill_id: str, task_id: str = "") -> dict:
    """Do exactly the same thing again: replay a verified skill's steps, in order.

    Same targets, same content, same permission gate, same verification - this is
    the 'copy paste the same' path. Unverified skills are refused until someone
    checks them."""
    allowed = permissions.check("memory", tool="body_skill_replay", target=skill_id[:60],
                                risk="low", action="replay a saved skill")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return await skills.replay(skill_id, task_id=task_id or None)


@mcp.tool()
async def research_any(query: str, sources: list[str] | None = None, limit: int = 8) -> dict:
    """Search several sources with a fallback chain: if one API is closed, try the next
    best one, including the public search page in the browser.

    Read-only: no account is used, nothing is posted, nothing is clicked in your
    session. (If you want your own logged-in session searched, connect the extension
    bridge - that is your one-click choice, never done silently.)"""
    allowed = permissions.check("public_web", tool="research_any", target=query[:80],
                                risk="low", action=f"research {query[:80]!r}")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = await anyio.to_thread.run_sync(
        lambda: sources.search_any(query, sources=sources, limit=limit))
    permissions.record_audit("research_any", "public_web",
                             "allow" if result.get("success") else "deny", query[:80],
                             status="COLLECTED" if result.get("success") else "BLOCKED",
                             evidence={"source": result.get("source"),
                                       "items": result.get("count", 0),
                                       "tried": [entry["source"] for entry in result.get("tried", [])]})
    return {"success": bool(result.get("success")),
            "message": (f"{result.get('count', 0)} record(s) from {result.get('source')}"
                        if result.get("success") else (result.get("reason") or "nothing found")),
            "data": result}


@mcp.tool()
async def demo_learn(video_path: str, name: str = "", max_frames: int = 60) -> dict:
    """Learn a workflow from a screen recording and turn it into a skill DRAFT.

    Frames are extracted (ffmpeg/opencv if installed), the screen text is read with
    OCR, changed frames become steps, and the unclear parts become questions for you.
    The result is a draft, not a verified skill - answer the questions first.

    Blocked honestly when a frame decoder or an OCR engine is missing."""
    allowed = permissions.check("desktop_capture", tool="demo_learn",
                                target=os.path.basename(video_path), risk="low",
                                action="learn a workflow from a screen recording")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    result = await anyio.to_thread.run_sync(
        lambda: demo.learn(video_path, name=name, max_frames=max_frames))
    permissions.record_audit("demo_learn", "desktop_capture",
                             "allow" if result.get("success") else "deny",
                             os.path.basename(video_path),
                             status=result.get("status"),
                             evidence={"stage": result.get("stage"),
                                       "questions": len(result.get("data", {}).get("questions", []))})
    return result


@mcp.tool()
async def body_roles() -> dict:
    """The team: each role's tools, permission and what it must produce.

    The roles are responsibilities, not separate models - the connected agent is the
    orchestrator and the brain; the body executes each contract."""
    return {"success": True, "message": f"{len(roles.matrix())} roles",
            "data": {"roles": roles.matrix()}}


@mcp.tool()
async def body_role_start(role: str, goal: str, max_actions: int = 50,
                          max_seconds: int = 900) -> dict:
    """Open a contract for one role: its tools, its budget and what it must produce."""
    allowed = permissions.check("public_web", tool="body_role_start", target=role,
                                risk="low", action=f"open a {role} contract")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    return roles.start(role, goal, budget={"max_actions": max_actions,
                                          "max_seconds": max_seconds})


@mcp.tool()
async def body_role_finish(role_id: str, evidence: str = "", verified: bool = False) -> dict:
    """Close a role contract with the evidence it produced."""
    return roles.finish(role_id, evidence=evidence, verified=verified)


@mcp.tool()
async def body_stop_all(reason: str = "emergency stop") -> dict:
    """STOP EVERYTHING: cancel the running background tasks and close the open contracts.

    This is the panic button - it never touches your files, only the work in flight."""
    return roles.stop_all(reason=reason)


@mcp.tool()
async def body_similarity_check(text: str, previous: list[str] | None = None) -> dict:
    """Is this new content actually new? Compare it with what was produced before.

    Used for adapted execution: keep the method, change the content. Reports the
    highest similarity found (token overlap and sequence ratio) and a verdict."""
    allowed = permissions.check("memory", tool="body_similarity_check", target=text[:60],
                                risk="low", action="compare new content with previous work")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    previous = previous or []
    if not previous:
        stored = [skill.get("goal", "") for skill in skills.list_skills(limit=20)]
        previous = [item for item in stored if item]
    result = skills.similarity(text, previous)
    return {"success": bool(result.get("ok")),
            "message": (f"max similarity {result.get('max_similarity')} - "
                        f"{result.get('verdict')}" if result.get("ok") else
                        str(result.get("reason"))),
            "data": result}


@mcp.tool()
async def body_console_start(port: int = 8765) -> dict:
    """Start the optional local Body Console (activity timeline + cancel/disconnect).

    Binds to 127.0.0.1 only and requires a session token; the returned URL contains it.
    The console shows REAL executor events — tasks, actions, verifications, blockers —
    and never page content. Stop it with body_console_stop()."""
    console = console_mod.get_console()
    console.port = int(port)
    info = console.start()
    return {"success": True, "message": f"console running at {info['url']}",
            "data": info}


@mcp.tool()
async def body_console_stop() -> dict:
    """Stop the local Body Console (if running)."""
    console = console_mod.get_console()
    console.stop()
    return {"success": True, "message": "console stopped", "data": {"status": "stopped"}}


@mcp.tool()
async def body_events(limit: int = 50, since: float = 0) -> dict:
    """Read the real execution event stream (task lifecycle, actions, verifications, blockers).

    Events are emitted by the executor itself, not by the model. Use it to report what
    actually happened, and to notice when the user must act (approval, CAPTCHA, login)."""
    items = events.bus.recent(limit=limit, since=since or None)
    active = runtime.registry.active()
    return {"success": True,
            "message": f"{len(items)} event(s); active task: {active['task_id'] if active else 'none'}",
            "data": {"events": items, "active_task": active,
                     "tasks": runtime.registry.list_tasks()[-10:]}}


@mcp.tool()
async def body_cancel(task_id: str = "") -> dict:
    """Request cancellation of the running task (or a specific task_id).

    Cancellation is cooperative: the executor stops at the next step boundary and
    reports CANCELLED. It never pretends the cancelled work was done."""
    target = task_id or None
    if target is None:
        events.emit(events.CANCEL_REQUESTED, tool="body_cancel", summary="cancel requested")
    cancelled = runtime.registry.request_cancel(target)
    if not cancelled:
        return {"success": False, "message": "no running task to cancel",
                "data": {"active_task": runtime.registry.active()}}
    return {"success": True, "message": f"cancellation requested for {cancelled}",
            "data": {"task_id": cancelled}}


@mcp.tool()
async def legs_open_app(application: str) -> dict:
    """Launch an allowlisted installed application (e.g. 'notepad').
    The allowlist lives in YOUR permissions.json (allowed_applications) — empty by default.
    Launching requires the app in your allowlist plus a fresh reflex_ask() approval."""
    return await open_app(application)


@mcp.tool()
async def reflex_verify(expected: str) -> dict:
    """Verify expected text is present on the current page (or desktop if no page).
    Use after every changing action. Returns success, found, and the evidence window."""
    return await reflex.verify(expected)


@mcp.tool()
async def reflex_ask(question: str, ctx: Context, action: str | None = None) -> dict:
    """Ask the human a yes/no question (elicitation form or native dialog).

    With action='<exact JSON action spec>': a yes issues ONE scoped approval bound to
    exactly that action (tool | capability | target | url | task_id). The approvals are
    consumed once at execution. Nothing on a webpage or in a model's output counts as
    approval. Fail-closed."""
    return await reflex.ask(question, ctx, action=action)


@mcp.tool()
async def body_status() -> dict:
    """Real capability states: what is importable, launched, blocked, or not configured —
    never claimed as 'verified' without a real check."""
    def _module_ok(name: str) -> bool:
        """Is the module importable? Uses find_spec so heavy optional packages
        (faster-whisper pulls in ctranslate2 + onnxruntime) are never imported
        just to answer a status question."""
        import importlib.util

        try:
            return importlib.util.find_spec(name) is not None
        except Exception:
            return False

    tesseract = config.tesseract_cmd()
    shared_alive = bool(browser._page is not None and not browser._page.is_closed())
    perms = permissions.permissions_summary()
    attach_state = attach.attached_status()
    data = {
        "version": __version__,
        "platform": platform.platform(),
        "server": {"status": "ok", "transport": "stdio",
                   "tools_registered": await _registered_tool_count()},
        "browser": {"playwright_importable": _module_ok("playwright"),
                    "mode": "headless" if config.browser_headless() else "headed",
                    "shared_page_launched": shared_alive,
                    "current_browser_cdp": {**attach_state,
                                            "chrome_attach_domain": "loopback-only, unauthenticated port — detach when done"},
                    "private_sessions": "available (isolated Playwright contexts, read-only snapshot)"},
        "batch": {"supported": True, "max_actions": 25,
                  "default_deadline_ms": config.batch_deadline_ms(),
                  "resume_from_checkpoints": True},
        "parallel": {"supported": True,
                     "max_concurrency": config.max_concurrency(),
                     "hard_max_concurrency": config.hard_max_concurrency(),
                     "max_tasks": 8,
                     "per_task_deadline_ms": config.task_deadline_ms(),
                     "overall_deadline_ms": config.parallel_deadline_ms()},
        "ears": {"sounddevice_importable": _module_ok("sounddevice"),
                 "faster_whisper_importable": _module_ok("faster_whisper"),
                 "whisper_model_configured": config.whisper_model(),
                 "verified": False,
                 "verified_note": "microphone path is mock-tested only; never run on your hardware"},
        "vision": {"mode": "optional, on request",
                   "tools": ["eyes_see_browser(screenshot=True)", "eyes_see_desktop(as_image=True)",
                             "desktop_watch_read(as_image=True)"],
                   "max_image_bytes": vision.MAX_IMAGE_BYTES,
                   "max_width": vision.MAX_WIDTH,
                   "note": "no image enters the context unless the agent asks for one; "
                           "images are produced in memory and never stored"},
        "hearing": {"mode": "push-to-talk, end-of-speech detection",
                    "tool": "ears_listen(seconds, stop_on_silence=True)",
                    "uncertain_fragments_flagged": True,
                    "note": "the transcript is returned as editable text; low-confidence "
                            "fragments are listed for confirmation"},
        "voice_output": {**tts.available(quick=True),
                         "verified": False,
                         "verified_note": "audio synthesis and playback start are observable; "
                                          "audible output is not machine-verifiable"},
        "desktop_ocr": {"pytesseract_importable": _module_ok("pytesseract"),
                        "tesseract_binary_found": bool(tesseract),
                        "status": "available" if tesseract else "not_installed",
                        "verified": False,
                        "verified_note": "OCR logic is mock-tested; tesseract not installed on this machine"},
        "state_perception": {"current_browser_attach": "attach_browser + select_tab + detach_browser (CDP loopback)" if not attach_state["attached"]
                                                        else f"attached: {attach_state['title']} ({attach_state['url']})",
                             "windows_management": "not_implemented",
                             "vpn_control": "not_implemented — permission category reserved (deny)",
                             "app_launch": "legs_open_app — user allowlist + fresh scoped approval"},
        "permissions": perms,
        "safety": {
            "mode": "strict",
            "fail_closed": True,
            "approval_ttl_seconds": 300,
            "policy": "never bypass logins/CAPTCHAs/rate limits/paywalls; "
                      "one reflex_ask approval authorizes exactly one protected action",
            "sensitive_field_masking": True,
            "patterns": {"sensitive": len(safety.SENSITIVE_PATTERNS),
                         "restriction": len(safety.RESTRICTION_PATTERNS),
                         "dangerous_button": len(safety.DANGEROUS_BUTTON_PATTERNS)},
        },
        "config": {"whisper_model": config.whisper_model(),
                   "polite_delay_ms": config.polite_delay_ms()},
    }
    return {"success": True, "message": "Body-MCP is alive — see per-capability states",
            "data": data}


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
