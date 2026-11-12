"""YouTube search: find reference videos with their metadata (read-only)."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

from . import video

USER_AGENT = video.USER_AGENT
MAX_RESULTS = 12


def _youtube_search_html(query: str) -> str:
    """The search results page (public, no cookies)."""
    url = ("https://www.youtube.com/results?search_query="
           + urllib.parse.quote_plus(query))
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read(video.MAX_HTML).decode("utf-8", "replace")


def youtube_search(query: str, limit: int = 8) -> dict:
    """Search YouTube and return the top results with channel, views, age and captions."""
    limit = max(1, min(int(limit), MAX_RESULTS))
    results = []
    note = ""
    try:
        page = _youtube_search_html(query)
    except Exception as exc:
        return {"count": 0, "results": [], "note": f"search failed: {type(exc).__name__}: {exc}"}

    # ytInitialData holds the result list
    start = page.find("var ytInitialData = ")
    if start < 0:
        start = page.find("ytInitialData = ")
    payload = {}
    if start >= 0:
        brace = page.find("{", start)
        if brace >= 0:
            depth = 0
            in_string = False
            escape = False
            for position in range(brace, min(len(page), brace + 8_000_000)):
                character = page[position]
                if in_string:
                    if escape:
                        escape = False
                    elif character == "\\":
                        escape = True
                    elif character == '"':
                        in_string = False
                    continue
                if character == '"':
                    in_string = True
                elif character == "{":
                    depth += 1
                elif character == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            payload = json.loads(page[brace:position + 1])
                        except Exception:
                            payload = {}
                        break
    if not payload:
        note = ("the results page did not expose its data (a consent or bot-check page) - "
                "open it in the browser instead")

    def walk(node):
        if isinstance(node, dict):
            if "videoRenderer" in node:
                yield node["videoRenderer"]
            for value in node.values():
                yield from walk(value)
        elif isinstance(node, list):
            for item in node:
                yield from walk(item)

    seen = set()
    for renderer in walk(payload):
        video_id = renderer.get("videoId")
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        details = renderer.get("title") or {}
        title = details.get("simpleText") or "".join(
            run.get("text", "") for run in (details.get("runs") or []))
        owner = (renderer.get("ownerText") or {}).get("simpleText") or (
            (renderer.get("ownerText") or {}).get("runs") or [{}])[0].get("text", "")
        views_text = (renderer.get("viewCountText") or {}).get("simpleText") or ""
        age = (renderer.get("publishedTimeText") or {}).get("simpleText") or ""
        length = (renderer.get("lengthText") or {}).get("simpleText") or ""
        captions = bool(((renderer.get("captions") or {}).get("playerCaptionsTracklistRenderer")
                         or {}).get("captionTracks"))
        results.append({
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": title[:200],
            "channel": owner[:80],
            "views": views_text[:40],
            "age": age[:40],
            "length": length[:20],
            "captions_available": captions,
        })
        if len(results) >= limit:
            break
    return {"count": len(results), "results": results,
            "note": note or "read-only search; nothing was played or downloaded"}
