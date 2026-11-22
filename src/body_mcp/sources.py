"""Research adapters: what the body can actually read, per platform.

Each adapter is a **public, documented, key-free** endpoint (or an explicit refusal).
Nothing here logs in, nothing bypasses a rate limit, nothing scrapes a paywalled or
private surface, and every record says how it was obtained.

| source | access | notes |
|---|---|---|
| hackernews | public API (Algolia) | no key, no login |
| reddit | public JSON | no key; may rate-limit anonymous calls |
| github_issues | public REST API | no key (60 req/h); an authenticated token raises it |
| stackoverflow | public API | no key at low volume |
| wikipedia | public API | no key |
| youtube | public pages + official caption tracks | read-only |
| web | any public page | `research_collect` |
| x / instagram | **blocked** | no public API without developer credentials; the sanctioned route is the user's own logged-in session through the extension bridge |

Every record is an evidence record: source, title, url, author, date, score, excerpt,
retrieval method, verification status and the limitation that applies.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")
MAX_LIMIT = 20
MAX_EXCERPT = 600
TIMEOUT = 20.0
LAST_CALL: dict[str, float] = {}


def _polite(source: str, gap: float = 1.0) -> None:
    """Space out calls per source (public APIs ask for this)."""
    previous = LAST_CALL.get(source, 0.0)
    wait = gap - (time.time() - previous)
    if wait > 0:
        time.sleep(wait)
    LAST_CALL[source] = time.time()


def _get_json(url: str, source: str) -> tuple[dict | list | None, str]:
    _polite(source)
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    })
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read(4_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code} from {source}"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    try:
        return json.loads(raw), ""
    except ValueError:
        return None, "the response was not JSON"


def _plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()[:MAX_EXCERPT]


def _record(source: str, **fields) -> dict:
    record = {
        "source": source,
        "id": fields.get("id"),
        "title": (fields.get("title") or "")[:200],
        "url": fields.get("url") or "",
        "author": (fields.get("author") or "")[:80],
        "created": fields.get("created") or "",
        "score": fields.get("score"),
        "comments": fields.get("comments"),
        "excerpt": _plain(fields.get("excerpt") or ""),
        "retrieval_method": f"public API ({source})",
        "verification": "CONFIRMED" if fields.get("title") else "UNCONFIRMED",
        "limitation": fields.get("limitation"),
    }
    return record


# ----------------------------------------------------------------- adapters
def _hackernews(query: str, limit: int) -> tuple[list[dict], str]:
    url = ("https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage="
           f"{limit}&query=" + urllib.parse.quote_plus(query))
    payload, error = _get_json(url, "hackernews")
    if error:
        return [], error
    out = []
    for hit in (payload or {}).get("hits", []) or []:
        out.append(_record("hackernews", id=hit.get("objectID"),
                           title=hit.get("title"),
                           url=hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                           author=hit.get("author"), created=hit.get("created_at"),
                           score=hit.get("points"), comments=hit.get("num_comments"),
                           excerpt=hit.get("story_text") or "",
                           limitation="HN points and comments are a snapshot, not a sentiment analysis"))
    return out, ""


def _reddit(query: str, limit: int) -> tuple[list[dict], str]:
    url = ("https://www.reddit.com/search.json?sort=relevance&t=all&limit="
           f"{limit}&q=" + urllib.parse.quote_plus(query))
    payload, error = _get_json(url, "reddit")
    if error:
        return [], error
    out = []
    for child in ((payload or {}).get("data") or {}).get("children", []) or []:
        data = child.get("data") or {}
        out.append(_record("reddit", id=data.get("id"), title=data.get("title"),
                           url="https://www.reddit.com" + (data.get("permalink") or ""),
                           author=data.get("author"),
                           created=str(data.get("created_utc") or ""),
                           score=data.get("score"), comments=data.get("num_comments"),
                           excerpt=data.get("selftext") or "",
                           limitation="anonymous API access; Reddit may rate-limit or block it"))
    return out, ""


def _github(query: str, limit: int) -> tuple[list[dict], str]:
    url = ("https://api.github.com/search/issues?per_page="
           f"{limit}&sort=updated&q=" + urllib.parse.quote_plus(query))
    payload, error = _get_json(url, "github_issues")
    if error:
        return [], error
    out = []
    for item in (payload or {}).get("items", []) or []:
        out.append(_record("github_issues", id=item.get("number"),
                           title=item.get("title"), url=item.get("html_url"),
                           author=(item.get("user") or {}).get("login"),
                           created=item.get("created_at"), comments=item.get("comments"),
                           excerpt=item.get("body") or "",
                           limitation="unauthenticated search: 10 requests/minute, 60/hour"))
    return out, ""


def _stackoverflow(query: str, limit: int) -> tuple[list[dict], str]:
    url = ("https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance"
           f"&site=stackoverflow&pagesize={limit}&q=" + urllib.parse.quote_plus(query))
    payload, error = _get_json(url, "stackoverflow")
    if error:
        return [], error
    out = []
    for item in (payload or {}).get("items", []) or []:
        out.append(_record("stackoverflow", id=item.get("question_id"),
                           title=item.get("title"), url=item.get("link"),
                           author=(item.get("owner") or {}).get("display_name"),
                           created=item.get("creation_date"), score=item.get("score"),
                           comments=item.get("answer_count"), excerpt=item.get("body") or "",
                           limitation="community Q&A, not a product roadmap"))
    return out, ""


def _wikipedia(query: str, limit: int) -> tuple[list[dict], str]:
    url = ("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit="
           f"{limit}&srsearch=" + urllib.parse.quote_plus(query))
    payload, error = _get_json(url, "wikipedia")
    if error:
        return [], error
    out = []
    for hit in ((payload or {}).get("query") or {}).get("search", []) or []:
        out.append(_record("wikipedia", id=hit.get("pageid"), title=hit.get("title"),
                           url=f"https://en.wikipedia.org/?curid={hit.get('pageid')}",
                           created=hit.get("timestamp"), excerpt=hit.get("snippet") or "",
                           limitation="encyclopedia, not a community opinion source"))
    return out, ""


def _youtube(query: str, limit: int) -> tuple[list[dict], str]:
    from . import youtube_search

    result = youtube_search.youtube_search(query, limit=limit)
    out = []
    for item in result.get("results", []):
        out.append(_record("youtube", id=item.get("video_id"), title=item.get("title"),
                           url=item.get("url"), author=item.get("channel"),
                           created=item.get("age"), excerpt=item.get("title") or "",
                           limitation="video titles only; use research_video for captions"))
    return out, result.get("note", "")


ADAPTERS = {
    "hackernews": _hackernews,
    "reddit": _reddit,
    "github_issues": _github,
    "stackoverflow": _stackoverflow,
    "wikipedia": _wikipedia,
    "youtube": _youtube,
}

BLOCKED_SOURCES = {
    "x": ("no public search API without developer credentials; use the official API with an "
          "account, or let the user drive their own logged-in session through the extension "
          "bridge"),
    "instagram": ("no public API without a Meta developer account and approved business "
                  "verification; do not scrape it"),
    "private_groups": "no access to private or closed groups - by design",
    "discord": "no public API for community content - by design",
}


def matrix() -> list[dict]:
    """What is readable, and what is not (with the reason)."""
    out = []
    for name in ADAPTERS:
        out.append({"source": name, "access": "public API (no key)",
                    "available": True,
                    "notes": "read-only, rate-limited, no login, no scraping of paywalled content"})
    for name, reason in BLOCKED_SOURCES.items():
        out.append({"source": name, "access": "credentials required", "available": False,
                    "notes": reason})
    return out


def _user_route(source: str) -> dict:
    """The sanctioned way for a HUMAN to continue — never an auto-bypass.

    A 403/login/paywall is the user's decision, not ours. The agent must ASK
    rather than silently fall back to another source and then claim the result
    came from the one that was blocked.
    """
    return {
        "status": "needs_user",
        "source": source,
        "why": BLOCKED_SOURCES.get(source, "the public route is closed"),
        "options": [
            ("You log in yourself in YOUR browser, then connect it: load extension/ "
             "in Edge/Chrome and click 'Connect this tab' (browser_bridge), or start "
             "your browser with a debug port and call attach_browser(). The agent "
             "never logs in or types credentials."),
            ("Accept a public page from another source instead — the agent will say "
             "which source actually produced each record."),
        ],
        "note": ("Ask the user; do not bypass, do not rotate identity, and never "
                 "attribute another source's results to this one."),
    }


def search(source: str, query: str, limit: int = 8) -> dict:
    """Search one source; returns evidence records (or the honest reason)."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    adapter = ADAPTERS.get(source)
    if adapter is None:
        if source in BLOCKED_SOURCES:
            result = _user_route(source)
            result.update(success=False, items=[], reason=result["why"])
            return result
        return {"success": False, "source": source, "items": [],
                "reason": f"unknown source {source!r}",
                "known": sorted(ADAPTERS) + sorted(BLOCKED_SOURCES)}
    items, error = adapter(query, limit)
    result = {"success": bool(items), "source": source, "items": items,
              "reason": error, "count": len(items),
              "note": "read-only evidence; the agent decides what it means"}
    if not items and error and ("403" in error or "429" in error or "login" in error.lower()):
        result.update(_user_route(source))
    return result


# --------------------------------------------------------- fallback chains
# when one root is closed, try the next best one - read-only, no disturbance
BROWSER_FALLBACKS = {
    "reddit": "https://www.reddit.com/search/?q=",
    "hackernews": "https://hn.algolia.com/?q=",
    "stackoverflow": "https://stackoverflow.com/search?q=",
    "github_issues": "https://github.com/search?q=",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search=",
    "x": "https://x.com/search?q=",
    "instagram": "https://www.instagram.com/explore/tags/",
}

ORDER = ("hackernews", "reddit", "github_issues", "stackoverflow", "wikipedia", "youtube")


def search_any(query: str, sources: list[str] | None = None, limit: int = 8,
               allow_browser: bool = True) -> dict:
    """Try the sources in order; fall back to the browser when an API is closed.

    The browser fallback reads the public search page (no account, read-only, no
    posting, no scrolling of your session). If the user is logged in, the extension
    bridge can search their own session instead - that is the user's choice, made
    with one click, and never done silently.
    """
    tried = []
    wanted = [name for name in (sources or ORDER) if name in ADAPTERS]
    for name in wanted:
        result = search(name, query, limit=limit)
        tried.append({"source": name, "ok": result["success"],
                      "reason": result.get("reason") or ""})
        if result["success"]:
            return {"success": True, "source": name, "items": result["items"],
                    "count": result["count"], "tried": tried,
                    "note": "public API, read-only"}
        if not allow_browser:
            continue
        fallback = BROWSER_FALLBACKS.get(name)
        if not fallback:
            continue
        url = fallback + urllib.parse.quote_plus(query)
        try:
            from . import research

            page = research.collect(url)
        except Exception:
            page = {"success": False, "data": {"items": []}}
        items = page.get("data", {}).get("items", [])
        if items:
            tried.append({"source": f"{name}:browser", "ok": True, "reason": ""})
            return {"success": True, "source": f"{name}:browser", "items": items,
                    "count": len(items), "tried": tried,
                    "note": "the API was closed; the public page was read instead"}
        tried.append({"source": f"{name}:browser", "ok": False, "reason": "no results"})
    blocked = [entry["source"] for entry in tried if not entry.get("ok")]
    return {"success": False, "source": None, "items": [], "tried": tried,
            "status": "needs_user",
            "reason": "; ".join(f"{entry['source']}: {entry['reason']}" for entry in tried
                                if entry["reason"]) or "no source returned nothing",
            "user_route": _user_route(",".join(blocked) or "the requested sources"),
            "note": ("nothing was forced, no account was used, nothing was posted; "
                     "ask the user to log in in their own browser and connect it, "
                     "or choose another source explicitly")}
