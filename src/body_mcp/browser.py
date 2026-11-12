"""Browser session for Body-MCP: Playwright Chromium, one shared page + isolated contexts.

Reliability choices (verified against Playwright 1.65 docs):
  - navigate with goto(...) (waits for `load`), readiness with locator waits —
    never `networkidle`, never fixed sleeps for readiness.
  - Polite delay between actions is human-like pacing, NOT a readiness strategy.
  - Refs (btn_N/input_N/link_N) resolve with this priority:
      1) unique accessible role + name
      2) associated label (form fields)
      3) test id / id / name attribute
      4) unique visible text
      5) positional XPath — validated against the element's kind/role/text before acting
    Ambiguous candidates are refused, never auto-picked.
  - Refs are invalidated by navigation (monotonic epoch) or snapshot rebuild —
    a stale ref fails closed with a "re-scan" instruction instead of clicking the wrong node.
  - Restricted pages (CAPTCHA / 429 / 403 / paywall) stop automation; see restrictions.py.
"""
import asyncio
import contextlib
import os
import random
import re
import urllib.parse

from . import safety
from .config import browser_headless, polite_delay_ms

_playwright = None
_browser = None
_page = None
_page_loop = None  # event loop the page/browser were created on
_browser_loop = None  # event loop the managed browser was created on

# ref -> candidate descriptor from the last snapshot; invalidated on navigation
REF_MAP: dict[str, dict] = {}
_nav_epoch = 0  # bumped on every navigation; REF_MAP entries carry the epoch
REF_RE = re.compile(r"^(btn|input|link)_\d+(#\d+)?$")

# approvals now live in body_mcp.approvals (scoped, single-use); no global token anymore


async def polite_delay() -> None:
    base = polite_delay_ms()
    if base > 0:
        await asyncio.sleep((base / 1000.0) * random.uniform(0.7, 1.3))


def _bump_navigation() -> None:
    """Call after any navigation: refs issued earlier are now stale."""
    global _nav_epoch
    _nav_epoch += 1
    REF_MAP.clear()


def _wire_navigation_listener(page) -> None:
    def _on_nav(frame):
        try:
            main = page.main_frame
        except Exception:
            main = None
        if main is None or frame == main:
            _bump_navigation()

    page.on("framenavigated", _on_nav)


async def _launch_managed_browser():
    """Start (or restart) our own Playwright Chromium. Never touches a CDP-attached browser."""
    global _playwright, _browser, _page, _page_loop, _browser_loop
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    try:
        if _browser is not None:
            await _browser.close()
    except Exception:
        pass
    try:
        if _playwright is not None:
            await _playwright.stop()
    except Exception:
        pass
    _playwright = _browser = _page = None
    _page_loop = loop
    _browser_loop = loop
    from playwright.async_api import async_playwright

    _playwright = await async_playwright().start()
    _browser = await _playwright.chromium.launch(headless=browser_headless())
    return _browser


async def ensure_page():
    """Return the current page: the CDP-attached user tab when set, else the shared page.

    Reusing Playwright objects created on an earlier, now-closed event loop fails
    with TargetClosedError — so reuse only applies to the loop that made them.
    Attached tabs (connect_over_cdp) are never launched or closed by this function.
    """
    from .attach import current_page as _attached_page

    attached = _attached_page()
    if attached is not None and not attached.is_closed():
        return attached

    global _browser, _page
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if (_page is not None and loop is _page_loop and not _page.is_closed()
            and _browser is not None and _browser.is_connected()):
        return _page

    await _launch_managed_browser()
    context = await _browser.new_context()
    _page = await context.new_page()
    _wire_navigation_listener(_page)
    return _page


async def launch_isolated_browser(headless: bool | None = None):
    """A browser instance owned by the caller (background tasks).

    It is NOT the shared managed browser: a background task must never hijack the
    page the agent is using, and it must not touch Playwright objects that belong
    to another event loop.
    """
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    instance = await playwright.chromium.launch(
        headless=browser_headless() if headless is None else headless)
    return playwright, instance


async def close_isolated_browser(playwright, instance) -> None:
    """Close an instance created by launch_isolated_browser()."""
    with contextlib.suppress(Exception):
        await instance.close()
    with contextlib.suppress(Exception):
        await playwright.stop()


async def new_isolated_context():
    """Create an isolated context+page for a parallel task (clean session).

    Works in CDP-attach mode too: it launches the managed browser if no managed
    browser exists, so isolated tasks never borrow the user's attached tab.
    A browser created on an earlier event loop is relaunched rather than reused.
    """
    global _browser
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if (_browser is None or not _browser.is_connected() or _browser_loop is not loop):
        await _launch_managed_browser()
    context = await _browser.new_context()
    page = await context.new_page()
    return context, page


async def shutdown_browser() -> None:
    global _playwright, _browser, _page, _page_loop, _browser_loop
    try:
        if _browser is not None:
            await _browser.close()
    except Exception:
        pass
    try:
        if _playwright is not None:
            await _playwright.stop()
    except Exception:
        pass
    _playwright = _browser = _page = None
    _page_loop = None
    _browser_loop = None
    REF_MAP.clear()


async def goto_with_response(url: str, timeout_ms: int = 30000, page=None) -> dict:
    """Navigate and return status/headers for restriction classification.
    With page=None, navigates the shared page; otherwise the given page."""
    if page is None:
        page = await ensure_page()
    response = await page.goto(url, wait_until="load", timeout=timeout_ms)
    status = response.status if response else None
    retry_after = None
    if response:
        try:
            retry_after = response.headers.get("retry-after")
        except Exception:
            retry_after = None
    return {"status": status, "retry_after": retry_after}


def check_url(url: str) -> dict:
    """Validate a URL before opening. Refuses credential-embedded and non-web schemes.
    file:// is limited to paths under the current working directory."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return {"ok": False, "reason": "unparseable URL"}
    scheme = (parsed.scheme or "").lower()
    if scheme == "file":
        raw = parsed.path or ""
        path = raw[1:] if raw.startswith("/") and len(raw) > 2 and raw[2] == ":" else raw
        resolved = os.path.realpath(os.path.normpath(path))
        cwd = os.path.realpath(os.getcwd())
        try:
            common = os.path.commonpath([resolved, cwd])
        except ValueError:
            common = ""
        if common != cwd:
            return {"ok": False,
                    "reason": "file:// is limited to the current working directory"}
        return {"ok": True}
    if scheme not in ("http", "https"):
        return {"ok": False, "reason": f"refusing scheme {scheme!r} (only http/https/file)"}
    if parsed.username or parsed.password:
        return {"ok": False, "reason": "refusing URL with embedded credentials (user:pass@host)"}
    return {"ok": True}


def _css_escape(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"')


async def snapshot_page(page=None, build_refs: bool = True) -> dict:
    """Extract title, headings, text, links, buttons, inputs and forms.

    With build_refs=False (private sessions), returns the same payload without
    interactive refs and leaves REF_MAP untouched.
    """
    if page is None:
        page = await ensure_page()
    title = await page.title()
    url = page.url
    headings = await page.evaluate(
        "() => [...document.querySelectorAll('h1, h2, h3, h4, h5, h6')]"
        ".slice(0, 50).map(e => ({ level: Number(e.tagName[1]), text: (e.innerText || '').trim() }))"
    )
    body_text = ""
    try:
        body_text = await page.locator("body").inner_text(timeout=5000)
    except Exception:
        body_text = ""
    full_text = body_text
    truncated = len(full_text) > 20000
    if truncated:
        full_text = full_text[:20000]

    elements = await page.evaluate(
        """() => {
            const out = [];
            const forms = [];
            for (const f of document.querySelectorAll('form')) {
                forms.push({ action: f.getAttribute('action') || '',
                             method: (f.method || 'get').toLowerCase(),
                             fields: [...f.querySelectorAll('input, textarea, select')]
                                         .map(e => e.name || e.id || '').filter(Boolean).slice(0, 50) });
            }
            const sel = 'a[href], button, input, textarea, select, [role="button"]';
            const all = document.querySelectorAll(sel);
            let n = 0;
            for (const el of all) {
                if (n++ > 400) break;
                const tag = el.tagName.toLowerCase();
                const visible = !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
                const base = {
                    id: el.id || '',
                    name_attr: el.getAttribute('name') || '',
                    testid: el.getAttribute('data-testid') || '',
                    visible,
                };
                let payload;
                if (tag === 'a') {
                    payload = { ...base, kind: 'link',
                                text: (el.innerText || el.textContent || '').trim().slice(0, 200),
                                href: el.href || '' };
                } else if (tag === 'button' || el.getAttribute('role') === 'button'
                           || (tag === 'input' && ['submit', 'button', 'image'].includes(el.type))) {
                    payload = { ...base, kind: 'button',
                                text: (el.innerText || el.value || el.textContent || '').trim().slice(0, 200),
                                type: el.type || 'submit' };
                } else {
                    payload = { ...base, kind: 'input', field_type: el.type || tag,
                                name: el.name || '',
                                autocomplete: el.getAttribute('autocomplete') || '',
                                placeholder: el.placeholder || el.getAttribute('placeholder') || '',
                                label: (el.labels && el.labels[0] ? el.labels[0].innerText : '').trim().slice(0, 200) };
                }
                // unique positional path (fallback only; verified before use)
                let path = '';
                let node = el;
                while (node && node.nodeType === 1) {
                    let index = 1;
                    let sib = node.previousElementSibling;
                    while (sib) { if (sib.tagName === node.tagName) index++; sib = sib.previousElementSibling; }
                    path = '/' + node.tagName.toLowerCase() + '[' + index + ']' + path;
                    if (path.split('/').length > 200) break;
                    node = node.parentElement;
                }
                payload.xpath = path;
                out.push(payload);
            }
            return { elements: out, forms };
        }"""
    )
    form_info = elements.get("forms", [])
    elements = elements.get("elements", [])

    if build_refs:
        # a rebuilt snapshot invalidates every ref issued before it: same-page DOM
        # changes can re-order elements, so old refs must not silently retarget
        _bump_navigation()
    links, buttons, inputs = [], [], []
    counters = {"link": 0, "button": 0, "input": 0}
    epoch = _nav_epoch
    for el in elements:
        kind = el.get("kind")
        counters[kind] = counters.get(kind, 0) + 1
        # the epoch is part of the ref: a ref from an older snapshot can never be
        # silently reused for a different element that happens to sit at the same index
        ref = (f"{'btn' if kind == 'button' else ('input' if kind == 'input' else 'link')}"
               f"_{counters[kind]}#{epoch}")
        if build_refs:
            REF_MAP[ref] = {"ref": ref, "epoch": epoch, **el}
        entry_ref = ref if build_refs else None
        if kind == "link":
            links.append({k: v for k, v in (("ref", entry_ref), ("text", el.get("text", "")),
                                            ("href", el.get("href", ""))) if v is not None})
        elif kind == "button":
            text = el.get("text", "")
            button_entry = {"text": text, "dangerous": safety.is_dangerous_label(text)}
            if build_refs:
                button_entry["ref"] = ref
            buttons.append(button_entry)
        else:
            sensitive = safety.is_sensitive_field(
                {"type": el.get("field_type"), "name": el.get("name_attr"), "id": el.get("id"),
                 "autocomplete": el.get("autocomplete"), "placeholder": el.get("placeholder")})
            input_entry = {"type": el.get("field_type"),
                           "name": el.get("name_attr"), "id": el.get("id"),
                           "label": el.get("label"), "placeholder": el.get("placeholder"),
                           "sensitive": sensitive,
                           "value": "***" if sensitive else None}
            if build_refs:
                input_entry["ref"] = ref
            inputs.append(input_entry)
    scan = safety.scan_text(full_text)
    return {
        "title": title,
        "url": url,
        "headings": headings,
        "text": full_text,
        "text_truncated": truncated,
        "links": links,
        "buttons": buttons,
        "inputs": inputs,
        "forms": form_info,
        "safety": scan,
        "sensitive_mode": scan["sensitive"],
        "restricted": scan["restricted"],
        "epoch": _nav_epoch,
    }


def resolve_ref(target: str):
    """Look up a ref. Unknown refs (including refs from an older snapshot) are None."""
    return REF_MAP.get(target)


def ref_is_stale(desc: dict) -> bool:
    return desc.get("epoch") != _nav_epoch


def ref_is_known(target: str) -> bool:
    """True when the token looks like a ref but no longer exists (stale snapshot)."""
    return bool(REF_RE.match(target)) and target not in REF_MAP


async def _element_kind_ok(locator, kind: str) -> bool:
    try:
        tag = (await locator.evaluate("e => e.tagName")).lower()
        if kind == "link":
            return tag == "a"
        if kind == "button":
            role = await locator.evaluate("e => e.getAttribute('role') || ''")
            if tag == "button" or role == "button":
                return True
            if tag == "input":
                itype = (await locator.evaluate("e => e.type || ''")).lower()
                return itype in ("submit", "button", "image")
            return False
        # input-like
        return tag in ("input", "textarea", "select")
    except Exception:
        return False


async def _strict_locator(page, locator, kind: str):
    """Return (locator, error). Refuses ambiguity; validates element kind."""
    try:
        count = await locator.count()
    except Exception as exc:
        return None, f"locator failed: {type(exc).__name__}: {exc}"
    if count == 0:
        return None, None
    if count > 1:
        return None, f"ambiguous: {count} elements match"
    if not await _element_kind_ok(locator, kind):
        return None, "element no longer matches the expected kind"
    return locator, None


async def resolve_locator(desc: dict):
    """Resolve a REF_MAP entry to a unique, actionable locator.

    Priority: role+name → label → testid/id/name → visible text → validated XPath.
    Returns (locator, how, error). Exactly one of the outputs is meaningful.
    """
    page = await ensure_page()
    if ref_is_stale(desc):
        return None, None, ("stale reference: the page navigated or changed since these refs "
                            "were issued; call eyes_see_browser() again")
    kind = desc.get("kind") or "input"
    text = (desc.get("text") or "").strip()
    label = (desc.get("label") or "").strip()

    candidates: list[tuple[str, object]] = []
    if kind == "link" and text:
        candidates.append(("role:link", page.get_by_role("link", name=text, exact=True)))
    elif kind == "button" and text:
        candidates.append(("role:button", page.get_by_role("button", name=text, exact=True)))
    elif kind == "input" and label:
        candidates.append(("label", page.get_by_label(label, exact=True)))
    if desc.get("testid"):
        candidates.append(("testid", page.locator(f'[data-testid="{_css_escape(desc["testid"])}"]')))
    if desc.get("id"):
        candidates.append(("id", page.locator(f'#{_css_escape(desc["id"])}')))
    if desc.get("name_attr"):
        candidates.append(("name", page.locator(f'[name="{_css_escape(desc["name_attr"])}"]')))
    if text:
        candidates.append(("text", page.get_by_text(text, exact=True)))
    if desc.get("xpath"):
        candidates.append(("xpath(validated)", page.locator(f"xpath={desc['xpath']}")))

    first_ambiguity: str | None = None
    for how, loc in candidates:
        locator, error = await _strict_locator(page, loc, kind)
        if locator is not None:
            return locator, how, None
        if error and "ambiguous" in error:
            first_ambiguity = f"{how}: {error}"
            continue
    if first_ambiguity:
        return None, None, (f"ambiguous reference ({first_ambiguity}); refusing to guess — "
                            "use a more specific ref or call eyes_see_browser()")
    return None, None, ("element not found — it may have been removed or the page changed; "
                        "call eyes_see_browser() again")


async def click_by_text(page, text: str):
    """Text-targeted click for non-ref targets. Refuses ambiguity."""
    for role in ("button", "link"):
        loc = page.get_by_role(role, name=text, exact=True)
        count = await loc.count()
        if count == 1:
            await loc.click()
            return {"ok": True, "how": f"role={role}"}
        if count > 1:
            loc2 = page.get_by_role(role, name=text, exact=False)
            if await loc2.count() > 1:
                return {"ok": False, "reason": f"ambiguous {role} target {text!r}: {count} matches"}
    loc = page.get_by_text(text, exact=False)
    count = await loc.count()
    if count == 1:
        await loc.click()
        return {"ok": True, "how": "text"}
    if count > 1:
        return {"ok": False, "reason": f"ambiguous text target {text!r}: {count} matches"}
    return {"ok": False, "reason": f"no visible element matches text: {text!r}"}


async def private_snapshot(url: str, timeout_ms: int = 30000) -> dict:
    """Mode A — throwaway isolated context: fresh cookies/storage, read-only snapshot,
    refs omitted, context ALWAYS closed (nothing persisted)."""
    context, page = await new_isolated_context()
    try:
        await polite_delay()
        nav = await goto_with_response(url, timeout_ms=timeout_ms, page=page)
        await polite_delay()
        snap = await snapshot_page(page=page, build_refs=False)
        return {"snapshot": snap, "nav": nav, "private": True}
    finally:
        import contextlib
        with contextlib.suppress(Exception):
            await context.close()


_BLOCKED_REASON = (
    "This page appears to show a login/CAPTCHA/bot-check/rate-limit/paywall/access restriction. "
    "Body-MCP does not bypass access controls. Complete the step manually in the browser, "
    "then call eyes_see_browser() again."
)


def blocked_message() -> str:
    return _BLOCKED_REASON
