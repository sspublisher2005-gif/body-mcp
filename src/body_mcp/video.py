"""Video evidence: the official captions + the page metadata, no model download.

For a public video (the user's own, or a permitted source) this collects:
  - title, channel, views, publication date, duration, description, chapters,
  - the **official caption track** (YouTube's own timedtext JSON3) as a timestamped
    transcript - this is how the audio is "heard" without downloading a speech model.

Rules:
  - only public pages, read-only, in an isolated context (no cookies of yours),
  - captions are the OFFICIAL track; if a video has none, the tool says so instead of
    inventing a transcript,
  - nothing is stored here: the caller decides what to keep (e.g. in memory),
  - local audio transcription is a separate, explicit opt-in (it needs a model).
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.request

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")
MAX_HTML = 6_000_000
MAX_TRANSCRIPT_CHARS = 120_000


def _fetch(url: str, timeout: float = 25.0) -> str:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/json",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(MAX_HTML)
    return raw.decode("utf-8", "replace")


def _meta(html_text: str, name: str) -> str:
    for pattern in (rf'<meta[^>]+(?:property|name)="{re.escape(name)}"[^>]+content="([^"]*)"',
                    rf'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="{re.escape(name)}"'):
        match = re.search(pattern, html_text, re.I)
        if match:
            return html.unescape(match.group(1)).strip()
    return ""


def _player_response(html_text: str) -> dict:
    """The page's ytInitialPlayerResponse (where the caption tracks live)."""
    for marker in ("var ytInitialPlayerResponse = ", "ytInitialPlayerResponse = ",
                   'ytInitialPlayerResponse = {"'):
        index = html_text.find(marker)
        if index < 0:
            continue
        start = html_text.find("{", index)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for position in range(start, min(len(html_text), start + 4_000_000)):
            character = html_text[position]
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
                        return json.loads(html_text[start:position + 1])
                    except Exception:
                        return {}
        return {}
    return {}


def _caption_tracks(player: dict) -> list[dict]:
    captions = (((player.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {})
                .get("captionTracks") or [])
    tracks = []
    for track in captions:
        if not track.get("baseUrl"):
            continue
        tracks.append({"language": track.get("languageCode", ""),
                       "name": (track.get("name") or {}).get("simpleText")
                       or ((track.get("name") or {}).get("runs") or [{}])[0].get("text", ""),
                       "url": track["baseUrl"]})
    return tracks


def _caption_url(base: str) -> str:
    """The caption URL in the JSON3 format (any existing fmt= is replaced)."""
    cleaned = re.sub(r"[?&]fmt=[^&]*", "", base)
    return cleaned + ("&" if "?" in cleaned else "?") + "fmt=json3"


def _parse_xml_captions(text: str) -> list[str]:
    """Fallback: the XML caption format (<text start="...">line</text>)."""
    lines = []
    for match in re.finditer(r'<text[^>]*start="([\d.]+)"[^>]*>(.*?)</text>', text, re.S):
        start = float(match.group(1))
        content = html.unescape(re.sub(r"<[^>]+>", "", match.group(2))).replace("\n", " ").strip()
        if content:
            lines.append(f"{int(start // 60):02d}:{int(start % 60):02d} {content}")
    return lines


def _transcript(track: dict) -> dict:
    """Fetch the caption track (JSON3) and turn it into timestamped lines."""
    url = _caption_url(track["url"])
    try:
        text = _fetch(url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "error": f"caption fetch failed: {exc}", "lines": []}
    payload = None
    try:
        payload = json.loads(text)
    except ValueError:
        payload = None
    if payload is None:
        lines = _parse_xml_captions(text)
        if lines:
            joined = "\n".join(lines)
            return {"ok": True, "lines": lines, "text": joined[:MAX_TRANSCRIPT_CHARS],
                    "truncated": len(joined) > MAX_TRANSCRIPT_CHARS,
                    "language": track.get("language"), "track_name": track.get("name")}
        return {"ok": False, "lines": [], "error": "the caption track was not in a readable format",
                "raw_head": text[:200]}
    lines = []
    for event in payload.get("events", []) or []:
        start = event.get("tStartMs", 0) / 1000.0
        segments = event.get("segs") or []
        content = "".join(segment.get("utf8", "") for segment in segments)
        content = content.replace("\n", " ").strip()
        if not content:
            continue
        stamp = f"{int(start // 60):02d}:{int(start % 60):02d}"
        lines.append(f"{stamp} {content}")
    text = "\n".join(lines)
    return {"ok": True, "lines": lines, "text": text[:MAX_TRANSCRIPT_CHARS],
            "truncated": len(text) > MAX_TRANSCRIPT_CHARS,
            "language": track.get("language"), "track_name": track.get("name")}


def collect_video(url: str) -> dict:
    """Collect the evidence record for one public video."""
    record = {
        "url": url, "title": "", "channel": "", "views": "", "published": "",
        "duration_s": None, "description": "", "chapters": [],
        "captions_available": False, "transcript": "", "transcript_lines": [],
        "transcript_language": None, "verification": "UNCONFIRMED", "status": "COLLECTED",
        "limitation": None, "retrieval_method": "public page (official caption track)",
    }
    try:
        page = _fetch(url)
    except Exception as exc:
        record.update(status="FAILED", verification="FAILED",
                      limitation=f"could not fetch the page: {type(exc).__name__}: {exc}")
        return record

    record["title"] = _meta(page, "og:title") or _meta(page, "title")
    record["channel"] = _meta(page, "author") or _meta(page, "og:video:tag")
    record["published"] = _meta(page, "uploadDate") or _meta(page, "datePublished")
    record["description"] = _meta(page, "description")
    length = re.search(r'"lengthSeconds":"(\d+)"', page)
    if length:
        record["duration_s"] = int(length.group(1))
    views = re.search(r'"viewCount":"?(\d+)', page)
    if views:
        record["views"] = views.group(1)

    player = _player_response(page)
    if not player:
        record["limitation"] = ("the page did not expose its player data (a consent or "
                                "bot-check page, or the video is private)")
        record["status"] = "BLOCKED"
        record["verification"] = "FAILED"
        return record

    tracks = _caption_tracks(player)
    record["captions_available"] = bool(tracks)
    if tracks:
        english = next((t for t in tracks if t["language"].lower().startswith("en")), tracks[0])
        result = _transcript(english)
        if result.get("ok"):
            record["transcript"] = result["text"]
            record["transcript_lines"] = result["lines"]
            record["transcript_language"] = result["language"]
            record["verification"] = "CONFIRMED"
        else:
            record["limitation"] = result.get("error")
            record["verification"] = "UNCONFIRMED"
    else:
        record["limitation"] = ("this video has no caption track - the audio cannot be read "
                                "without a local speech model (opt-in)")
        record["verification"] = "UNCONFIRMED"

    details = player.get("videoDetails") or {}
    record["title"] = record["title"] or details.get("title", "")
    record["channel"] = record["channel"] or details.get("author", "")
    record["description"] = record["description"] or (details.get("shortDescription") or "")[:4000]
    if details.get("viewCount"):
        record["views"] = record["views"] or details["viewCount"]
    chapters = []
    for part in (player.get("engagementPanels") or []):
        content = part.get("engagementPanelSectionListRenderer") or {}
        for section in (content.get("sectionListRenderer") or {}).get("contents", []):
            for chapter in (section.get("chapterRenderer") or {}).get("contents", []):
                title = ((chapter.get("title") or {}).get("simpleText")
                         or ((chapter.get("title") or {}).get("runs") or [{}])[0].get("text", ""))
                start = ((chapter.get("timeRangeStartMillis") or 0) / 1000.0)
                chapters.append({"title": title, "start_s": round(start, 1)})
    if chapters:
        record["chapters"] = chapters
    return record


def summarize(record: dict, max_lines: int = 40) -> dict:
    """A compact, agent-ready view of the evidence record."""
    lines = record.get("transcript_lines") or []
    return {
        "url": record.get("url"),
        "title": record.get("title"),
        "channel": record.get("channel"),
        "views": record.get("views"),
        "published": record.get("published"),
        "duration_s": record.get("duration_s"),
        "chapters": record.get("chapters"),
        "verification": record.get("verification"),
        "limitation": record.get("limitation"),
        "transcript_lines_total": len(lines),
        "transcript_head": lines[:max_lines],
        "transcript_tail": lines[-max_lines:] if len(lines) > max_lines else [],
    }
