"""Hands: open URLs, click, type, press keys, scroll — in the shared Chromium page.

Rules enforced here (code, not prompts):
  - Only http/https/file URLs; credential-embedded URLs refused; file:// limited to CWD.
  - Per-service cooldown honored before navigation (rate_limit → HTTP 429 evidence).
  - Restricted pages (CAPTCHA/rate-limit/paywall/403) refuse automation.
  - Typing into sensitive fields is always refused (not profile-overridable).
  - Dangerous clicks require a fresh reflex_ask() approval; one approval = one click.
  - Permission profile (permissions.py) gates every tool before any action runs.
  - Polite, human-like pace between page actions.
"""
import re
import urllib.parse

from . import browser, events, permissions, restrictions, safety, undo
from .permissions import check, record_audit, redact_target

KEY_PATTERN = re.compile(r"^[A-Za-z0-9+._\-]{1,40}$")
NAMED_KEYS = {
    "enter", "tab", "escape", "esc", "backspace", "delete", "space", "home", "end",
    "pageup", "pagedown", "arrowleft", "arrowright", "arrowup", "arrowdown",
    "shift", "control", "ctrl", "alt", "meta", "f1", "f2", "f3", "f4", "f5",
    "f6", "f7", "f8", "f9", "f10", "f11", "f12",
}
HARD_STOP_KINDS = {"captcha", "rate_limit", "access_denied", "paywall"}


def url_verification(requested: str, observed: str) -> dict:
    """Compare the requested destination with what the browser actually shows.

    Only scheme+host+path are compared; query/fragment are dropped (no secrets in
    evidence). A redirect elsewhere is reported UNCONFIRMED, never called success.
    """
    def parts(u: str):
        try:
            p = urllib.parse.urlsplit(u)
            return (p.scheme.lower(), (p.hostname or "").lower(),
                    urllib.parse.unquote(p.path or "/"))
        except Exception:
            return None

    want, got = parts(requested), parts(observed)
    if want and got and want == got:
        return {"status": "CONFIRMED", "requested": redact_target(requested),
                "observed": redact_target(observed)}
    return {"status": "UNCONFIRMED", "requested": redact_target(requested),
            "observed": redact_target(observed),
            "note": "landed on a different URL (redirect, login wall or error page) — "
                    "inspect with eyes_see_browser() before acting"}


async def _current_guard() -> dict | None:
    """If the current page is restricted, return a refusal dict."""
    try:
        page = await browser.ensure_page()
        text = await page.locator("body").inner_text(timeout=3000)
    except Exception:
        return None
    hit = restrictions.classify(None, text, page.url or "")
    if hit and hit["kind"] in HARD_STOP_KINDS:
        return {"success": False,
                "message": browser.blocked_message(),
                "data": {"restriction": hit, "url": page.url}}
    return None


async def open_url(url: str) -> dict:
    allowed = check("public_web", tool="hands_open", target=redact_target(url), risk="low",
                    action="open website")
    if not allowed.allowed:
        record_audit("hands_open", "public_web", allowed.decision, redact_target(url))
        return {"success": False, "message": allowed.message,
                "data": {"url": redact_target(url), "permission": allowed.decision}}
    verdict = browser.check_url(url)
    if not verdict["ok"]:
        return {"success": False, "message": verdict["reason"], "data": {"url": redact_target(url)}}
    domain = restrictions.domain_of(url)
    remaining = await restrictions.cooldown_remaining(domain)
    if remaining > 0:
        return {"success": False,
                "message": f"rate-limit cooldown active for {domain} — retry after ~{int(remaining)}s. "
                           "Body-MCP does not rotate identities or hammer rate-limited services.",
                "data": {"status": "retry_scheduled", "domain": domain,
                         "retry_after_s": int(remaining)}}
    try:
        page = await browser.ensure_page()
        previous_url = page.url
        await browser.polite_delay()
        nav = await browser.goto_with_response(url, timeout_ms=30000)
        undo.record_navigation(url, previous_url)
        await browser.polite_delay()
    except Exception as exc:
        return {"success": False,
                "message": f"failed to open {redact_target(url)}: {type(exc).__name__}: {exc}",
                "data": {"url": redact_target(url),
                         "hint": "check the URL and your network; Body-MCP does not push through anti-bot walls"}}
    text = await page.locator("body").inner_text(timeout=5000)
    hit = restrictions.classify(nav["status"], text, url, nav["retry_after"])
    if hit and hit["kind"] == "rate_limit":
        retry_s = hit.get("retry_after_s") or 60
        await restrictions.set_cooldown(domain, retry_s, "hands_open hit 429")
        return {"success": False,
                "message": f"rate-limited by {domain} (HTTP 429). Backing off ~{int(retry_s)}s "
                           "and refusing further requests to this service until the cooldown expires.",
                "data": {"status": "retry_scheduled", "domain": domain,
                         "retry_after_s": retry_s, "restriction": hit}}
    if hit and hit["kind"] in ("captcha", "auth_expired"):
        return {"success": False,
                "message": browser.blocked_message() + f" (detected: {hit['kind']})",
                "data": {"restriction": hit, "url": page.url, "status": "needs_user"}}
    if hit and hit["kind"] in ("access_denied", "paywall"):
        return {"success": False,
                "message": browser.blocked_message() + f" (detected: {hit['kind']})",
                "data": {"restriction": hit, "url": page.url, "status": "blocked"}}
    scan = safety.scan_text(text)
    verification = url_verification(url, page.url)
    record_audit("hands_open", "public_web", "allow", redact_target(url),
                 status=verification["status"],
                 evidence={"http_status": nav["status"], "url_observed": page.url})
    return {"success": True,
            "message": "page opened" + (" (sensitive page — proceed carefully)"
                                        if scan["sensitive"] else ""),
            "data": {"url": page.url, "title": await page.title(),
                     "http_status": nav["status"], "safety": scan,
                     "verification": verification}}


async def click(target: str) -> dict:
    allowed = check("keyboard_mouse", tool="hands_click", target=redact_target(target), risk="low",
                    action="click element")
    if not allowed.allowed:
        record_audit("hands_click", "keyboard_mouse", allowed.decision, redact_target(target))
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    guard = await _current_guard()
    if guard:
        return guard
    page = await browser.ensure_page()
    url_before = page.url

    desc = browser.resolve_ref(target)
    if desc is None and browser.ref_is_known(target):
        return {"success": False,
                "message": (f"stale reference {target!r} — the page was re-scanned or navigated "
                            "since this ref was issued; call eyes_see_browser() again"),
                "data": {"target": target, "stale": True}}
    label = (desc.get("text") if desc else target) or ""
    if safety.is_dangerous_label(label):
        consecutive = await permissions.authorize(
            "consequential", tool="hands_click", target=label, risk="high",
            action=f"consequential click: {label!r}",
            url=page.url, task_id=None)
        if not consecutive.allowed:
            record_audit("hands_click", "consequential", consecutive.decision, redact_target(label))
            return {"success": False,
                    "message": consecutive.message,
                    "data": {"permission": consecutive.decision,
                             "required_action": permissions.required_action_spec(
                                 "hands_click", "consequential", label, page.url)}}
    await browser.polite_delay()
    if desc is not None:
        if browser.ref_is_stale(desc):
            return {"success": False,
                    "message": "stale reference — the page navigated since refs were issued; "
                               "call eyes_see_browser() again",
                    "data": {"target": target, "stale": True}}
        locator, how, error = await browser.resolve_locator(desc)
        if error:
            return {"success": False, "message": error, "data": {"target": target}}
        try:
            await locator.click()
        except Exception as exc:
            return {"success": False,
                    "message": f"click failed: {type(exc).__name__}: {exc}",
                    "data": {"target": target, "hint": "page may have changed — re-run eyes_see_browser()"}}
        clicked_how = how
    else:
        result = await browser.click_by_text(page, target)
        if not result["ok"]:
            return {"success": False, "message": result["reason"],
                    "data": {"target": target, "hint": "call eyes_see_browser() and use a ref like btn_1"}}
        clicked_how = f"text:{result.get('how')}"
    url_after = page.url
    navigated = url_after != url_before
    verification = {
        "status": "CONFIRMED" if navigated else "UNCONFIRMED",
        "evidence": {"url_before": redact_target(url_before),
                     "url_after": redact_target(url_after),
                     "navigated": navigated},
        "note": (None if navigated else
                 "the click was dispatched but its effect is unproven - "
                 "call reflex_verify('<expected text>') before treating it as done")}
    cap = "consequential" if safety.is_dangerous_label(label) else "keyboard_mouse"
    record_audit("hands_click", cap, "allow", redact_target(label),
                 status=verification["status"], evidence=verification["evidence"])
    events.emit(events.ACTION, tool="hands_click", status=verification["status"],
                summary=f"click {label!r} via {clicked_how}",
                evidence={"navigated": navigated, "target": redact_target(label)})
    return {"success": True,
            "message": (f"clicked via {clicked_how}"
                        + (" - page navigated" if navigated else "")),
            "data": {"url": url_after, "title": await page.title(),
                     "verification": verification}}


async def type_text(field_ref: str, text: str) -> dict:
    allowed = check("keyboard_mouse", tool="hands_type", target=field_ref, risk="low",
                    action="type into field")
    if not allowed.allowed:
        record_audit("hands_type", "keyboard_mouse", allowed.decision, field_ref)
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    guard = await _current_guard()
    if guard:
        return guard
    desc = browser.resolve_ref(field_ref)
    if desc is None:
        stale = browser.ref_is_known(field_ref)
        return {"success": False,
                "message": (f"stale reference {field_ref!r} — the page was re-scanned or navigated "
                            "since this ref was issued; call eyes_see_browser() again"
                            if stale else
                            f"unknown field ref: {field_ref!r}. Call eyes_see_browser() and use "
                            "the refs it returns (e.g. input_1#3)."),
                "data": {"field_ref": field_ref, "stale": stale,
                         "known_refs": list(browser.REF_MAP)[:20]}}
    if browser.ref_is_stale(desc):
        return {"success": False,
                "message": "stale reference — page navigated since refs were issued; re-scan",
                "data": {"field_ref": field_ref, "stale": True}}
    if safety.is_sensitive_field({"type": desc.get("field_type"), "name": desc.get("name_attr"),
                                  "id": desc.get("id"), "autocomplete": desc.get("autocomplete"),
                                  "placeholder": desc.get("placeholder")}):
        return {"success": False,
                "message": (f"refusing to type into sensitive field {field_ref!r} "
                            f"(type={desc.get('field_type')!r}, name={desc.get('name_attr')!r}). "
                            "Passwords/OTPs/card data must be entered by you manually."),
                "data": {"field_ref": field_ref, "sensitive": True}}
    locator, how, error = await browser.resolve_locator(desc)
    if error:
        return {"success": False, "message": error, "data": {"field_ref": field_ref}}
    await browser.polite_delay()
    try:  # remember the previous value so the change can be undone
        previous = await locator.input_value(timeout=2000)
        undo.record_typing(field_ref, previous, desc.get("page_url") or "")
    except Exception:
        pass
    try:
        await locator.fill("")
        await locator.fill(text)
    except Exception as exc:
        return {"success": False,
                "message": f"typing failed: {type(exc).__name__}: {exc}",
                "data": {"field_ref": field_ref}}
    # postcondition: read the value back. A successful fill() is not proof the field kept it.
    try:
        actual = await locator.input_value(timeout=3000)
    except Exception:
        actual = None
    if actual is None:
        record_audit("hands_type", "keyboard_mouse", "allow", field_ref, status="UNCONFIRMED")
        return {"success": True,
                "message": f"typed {len(text)} characters into {field_ref} (value not readable - unverified)",
                "data": {"field_ref": field_ref, "chars": len(text),
                         "verification": {"status": "UNCONFIRMED",
                                          "note": "field does not expose its value; verify the "
                                                  "resulting page state with reflex_verify()"}}}
    if actual != text:
        record_audit("hands_type", "keyboard_mouse", "deny", field_ref,
                     status="FAILED", error_code="POSTCONDITION_FAILED")
        return {"success": False,
                "message": (f"POSTCONDITION_FAILED: the field does not hold the intended text "
                            f"after typing ({len(actual)} chars present, expected {len(text)}). "
                            "The page may strip, mask or reformat input."),
                "data": {"field_ref": field_ref, "error_code": "POSTCONDITION_FAILED",
                         "verification": {"status": "FAILED", "observed_chars": len(actual),
                                          "expected_chars": len(text)}}}
    record_audit("hands_type", "keyboard_mouse", "allow", field_ref, status="CONFIRMED")
    events.emit(events.ACTION, tool="hands_type", status="CONFIRMED",
                summary=f"typed {len(text)} chars into {field_ref}",
                evidence={"chars": len(text)})
    return {"success": True, "message": f"typed {len(text)} characters into {field_ref}",
            "data": {"field_ref": field_ref, "chars": len(text),
                     "verification": {"status": "CONFIRMED",
                                      "evidence": "field value read back matches the input"}}}


async def press(key: str) -> dict:
    allowed = check("keyboard_mouse", tool="hands_press", target=key, risk="low",
                    action="press key")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    guard = await _current_guard()
    if guard:
        return guard
    key = key.strip()
    if not KEY_PATTERN.match(key):
        return {"success": False, "message": f"unsupported key name: {key!r}",
                "data": {"allow": "single keys/chords like Enter, Tab, Escape, Control+A"}}
    parts = key.split("+")
    if any(p.lower() not in NAMED_KEYS and not p.isalnum() for p in parts):
        return {"success": False, "message": f"unsupported key chord: {key!r}",
                "data": {"allow": "chords of named keys and single alphanumerics"}}
    page = await browser.ensure_page()
    await browser.polite_delay()
    try:
        await page.keyboard.press("+".join(parts))
    except Exception as exc:
        return {"success": False, "message": f"key press failed: {type(exc).__name__}: {exc}",
                "data": {"key": key}}
    return {"success": True, "message": f"pressed {key}", "data": {"key": key, "url": page.url}}


async def scroll(direction: str, amount: int = 3) -> dict:
    allowed = check("keyboard_mouse", tool="hands_scroll", target=direction, risk="low",
                    action="scroll page")
    if not allowed.allowed:
        return {"success": False, "message": allowed.message,
                "data": {"permission": allowed.decision}}
    guard = await _current_guard()
    if guard:
        return guard
    direction = (direction or "down").lower()
    if direction not in ("up", "down"):
        return {"success": False, "message": f"direction must be 'up' or 'down', got {direction!r}", "data": {}}
    amount = max(1, min(50, int(amount)))
    page = await browser.ensure_page()
    delta = amount * 300
    if direction == "down":
        await page.mouse.wheel(0, delta)
    else:
        await page.mouse.wheel(0, -delta)
    await browser.polite_delay()
    return {"success": True, "message": f"scrolled {direction} by {amount} units",
            "data": {"direction": direction, "amount": amount, "url": page.url}}
