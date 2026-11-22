"""Evidence-oriented research collection.

Body-MCP does not plan or write research. It retrieves sources the user or the
agent is allowed to read and returns structured, citable evidence records:
source, URL, title, publication date, retrieval time, method, excerpt, content
hash and a verification status. The connected agent does the interpretation.

Rules:
  - bounded: at most `max_items` pages, bounded text per page, bounded total time,
  - honest: a page behind a login, CAPTCHA, paywall or rate limit is reported as
    BLOCKED with the reason - never bypassed,
  - deduplicated by URL and by content hash,
  - source content is data: it can never change permissions or approve actions.
"""
from __future__ import annotations

import hashlib
import time
import urllib.parse

from . import browser, restrictions, safety

MAX_ITEMS = 10
MAX_TEXT = 6000
MAX_EXCERPT = 500
DEFAULT_TIMEOUT_MS = 20000

DATE_META_KEYS = ("article:published_time", "og:published_time", "datePublished",
                  "date", "pubdate", "publish-date")


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()[:16]


async def _browser_for_research():
    """Prefer a browser the USER connected; an isolated managed Chromium is the fallback.

    The user's logged-in session is theirs to share: CDP attach or the extension
    bridge are the only sanctioned routes, and both need a human action. We never
    silently launch a different browser and pretend it is their session.
    """
    from . import attach as attach_mod
    from . import bridge as bridge_mod

    if attach_mod.attached_status()["attached"]:
        return None, await browser.ensure_page(), "your connected browser tab (CDP)"
    if bridge_mod.status().get("extension_connected"):
        return None, await browser.ensure_page(), "your connected browser (extension bridge)"
    context, page = await browser.new_isolated_context()
    return context, page, ("a separate managed Chromium (your browser is not connected; "
                           "connect it with attach_browser or the extension bridge to use "
                           "your own session)")


async def _collect_one(url: str) -> dict:
    """Retrieve one page, preferring the user's connected browser when available."""
    record = {
        "source_url": url,
        "source_name": urllib.parse.urlsplit(url).netloc or url,
        "title": "",
        "published": None,
        "collected_at": time.time(),
        "retrieval_method": "browser (isolated context, read-only)",
        "excerpt": "",
        "text": "",
        "text_chars": 0,
        "content_hash": "",
        "http_status": None,
        "verification": "UNCONFIRMED",
        "status": "COLLECTED",
        "limitation": None,
    }
    verdict = browser.check_url(url)
    if not verdict["ok"]:
        record.update(status="BLOCKED", verification="FAILED",
                      limitation=verdict["reason"])
        return record

    context = None
    try:
        context, page, browser_source = await _browser_for_research()
        record["browser_source"] = browser_source
        nav = await browser.goto_with_response(url, timeout_ms=DEFAULT_TIMEOUT_MS, page=page)
        record["http_status"] = nav["status"]
        text = ""
        try:
            text = await page.locator("body").inner_text(timeout=8000)
        except Exception:
            text = ""
        title = ""
        try:
            title = await page.title()
        except Exception:
            title = ""
        meta = {}
        try:
            meta = await page.evaluate(
                """() => {
                    const out = {};
                    for (const m of document.querySelectorAll('meta[property], meta[name]')) {
                        const key = (m.getAttribute('property') || m.getAttribute('name') || '').toLowerCase();
                        const val = m.getAttribute('content') || '';
                        if (key && val) out[key] = val.slice(0, 300);
                    }
                    out['__canonical'] = (document.querySelector('link[rel=canonical]') || {}).href || '';
                    return out;
                }""")
        except Exception:
            meta = {}

        hit = restrictions.classify(nav["status"], text, url, nav["retry_after"])
        if hit:
            record.update(status="BLOCKED", verification="FAILED",
                          limitation=f"{hit['kind']}: {hit.get('evidence')}",
                          title=title[:200])
            return record

        published = None
        for key in DATE_META_KEYS:
            if meta.get(key):
                published = meta[key]
                break
        excerpt = " ".join((text or "").split())[:MAX_EXCERPT]
        record.update(
            title=(title or meta.get("og:title") or "")[:200],
            published=published,
            excerpt=excerpt,
            text=(text or "")[:MAX_TEXT],
            text_chars=len(text or ""),
            content_hash=_sha(text or ""),
            verification="CONFIRMED" if (text or "").strip() else "UNCONFIRMED",
            limitation=None if (text or "").strip() else "page returned no readable text",
            source_name=(urllib.parse.urlsplit(meta.get("__canonical") or url).netloc
                         or urllib.parse.urlsplit(url).netloc or url),
        )
        scan = safety.scan_text(record["text"])
        record["sensitive_content"] = bool(scan.get("sensitive"))
        return record
    except Exception as exc:
        record.update(status="FAILED", verification="FAILED",
                      limitation=f"{type(exc).__name__}: {exc}"[:200])
        return record
    finally:
        if context is not None:
            import contextlib

            with contextlib.suppress(Exception):
                await context.close()


async def collect(urls: list[str], max_items: int = MAX_ITEMS) -> dict:
    """Collect up to `max_items` sources and return evidence records."""
    urls = [u for u in (urls or []) if isinstance(u, str) and u.strip()][:max(1, min(max_items, MAX_ITEMS))]
    records: list[dict] = []
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    blocked: list[dict] = []
    duplicates = 0

    for url in urls:
        key = url.strip().rstrip("/")
        if key in seen_urls:
            duplicates += 1
            continue
        seen_urls.add(key)
        record = await _collect_one(url.strip())
        if record["status"] != "COLLECTED":
            blocked.append({"url": record["source_url"], "status": record["status"],
                            "limitation": record["limitation"]})
            records.append(record)
            continue
        if record["content_hash"] and record["content_hash"] in seen_hashes:
            duplicates += 1
            records.append({**record, "status": "DUPLICATE",
                            "limitation": "identical content already collected"})
            continue
        seen_hashes.add(record["content_hash"])
        records.append(record)

    collected = [r for r in records if r["status"] == "COLLECTED"]
    return {
        "success": bool(collected),
        "message": (f"collected {len(collected)} source(s); {len(blocked)} blocked; "
                    f"{duplicates} duplicate(s)"),
        "data": {
            "status": "COLLECTED" if collected else "BLOCKED",
            "collected": len(collected),
            "blocked": len(blocked),
            "duplicates": duplicates,
            "items": records,
            "blocked_sources": blocked,
            "coverage_note": ("Only the listed sources were fetched. This is a sample, "
                              "not an exhaustive search of any platform."),
        },
    }
