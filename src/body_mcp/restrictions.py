"""Access-restriction classification and shared per-service cooldowns.

Body-MCP never bypasses restrictions. This module *classifies* them (from HTTP
status + page text) and coordinates a shared cooldown so parallel workers stop
hammering a rate-limited or blocked service.

Restriction kinds:
  captcha         human-verification challenge is present
  rate_limit      HTTP 429 / explicit rate-limit signal (may carry Retry-After)
  access_denied   HTTP 403 / access denied
  auth_expired    login / authentication-required page (unexpected for logged-out work)
  network         temporary network failure
  paywall         subscription/paywall restriction
  ordinary_error  everything else (not an access-control issue)
"""
import asyncio
import re
import time
import urllib.parse

_cap_cooldowns: dict[str, float] = {}          # domain -> epoch when cooldown expires
_lock = asyncio.Lock()

CAPTCHA_HINTS = [
    r"captcha", r"recaptcha", r"verify (that )?you are (?:a )?human",
    r"are you (?:a )?human", r"unusual traffic", r"human verification",
    r"press (?:the )?button.*human", r"prove you are", r"robot check",
]
PAYWALL_HINTS = [
    r"paywall", r"subscribe to (?:continue|read)", r"subscribe (?:for|to) (?:full|unlimited)",
    r"members-only", r"premium content",
]
RATE_LIMIT_HINTS = [
    r"too many requests", r"rate limit", r"rate-limit", r"requests per (?:minute|second|hour)",
    r"temporarily throttled",
]
ACCESS_DENIED_HINTS = [
    r"access denied", r"permission denied", r"forbidden", r"\b403\b", r"ip (?:address )?blocked",
    r"blocked (?:your|this) (?:request|ip|account)",
]
AUTH_HINTS = [
    r"sign[- ]?in", r"log[- ]?in", r"session (?:expired|timed out)", r"authentication required",
    r"please log in", r"your session",
]


def domain_of(url: str) -> str:
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower()
    except Exception:
        return ""


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, min(3600.0, float(value)))
    except ValueError:
        import email.utils
        from datetime import datetime, timezone
        try:
            dt = email.utils.parsedate_to_datetime(value)
            if dt is None:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = (dt - datetime.now(timezone.utc)).total_seconds()
            return max(0.0, min(3600.0, delta))
        except Exception:
            return None


def _first_match(patterns: list[str], text: str) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(0)
    return None


def classify(status: int | None, text: str, url: str = "",
             retry_after: str | None = None) -> dict | None:
    """Classify an outcome. Returns None for ordinary pages."""
    text = text or ""
    retry_s = parse_retry_after(retry_after)
    if status == 429 or _first_match(RATE_LIMIT_HINTS, text):
        return {"kind": "rate_limit", "http_status": status,
                "retry_after_s": retry_s,
                "evidence": "HTTP 429" if status == 429 else _first_match(RATE_LIMIT_HINTS, text),
                "domain": domain_of(url)}
    if status == 403 or _first_match(ACCESS_DENIED_HINTS, text):
        return {"kind": "access_denied", "http_status": status,
                "retry_after_s": retry_s,
                "evidence": "HTTP 403" if status == 403 else _first_match(ACCESS_DENIED_HINTS, text),
                "domain": domain_of(url)}
    cap = _first_match(CAPTCHA_HINTS, text)
    if cap:
        return {"kind": "captcha", "http_status": status, "retry_after_s": None,
                "evidence": cap, "domain": domain_of(url)}
    pay = _first_match(PAYWALL_HINTS, text)
    if pay:
        return {"kind": "paywall", "http_status": status, "retry_after_s": None,
                "evidence": pay, "domain": domain_of(url)}
    auth = _first_match(AUTH_HINTS, text)
    if auth and (status == 401 or status == 403 or "sign" in text.lower() or "log" in text.lower()):
        return {"kind": "auth_expired", "http_status": status, "retry_after_s": None,
                "evidence": auth, "domain": domain_of(url)}
    return None


def network_failure(exc: Exception, url: str = "") -> dict:
    return {"kind": "network", "http_status": None, "retry_after_s": None,
            "evidence": f"{type(exc).__name__}: {exc}", "domain": domain_of(url)}


async def set_cooldown(domain: str, seconds: float, reason: str = "") -> None:
    if not domain or seconds <= 0:
        return
    async with _lock:
        _cap_cooldowns[domain] = max(_cap_cooldowns.get(domain, 0.0), time.time() + seconds)


async def cooldown_remaining(domain: str) -> float:
    if not domain:
        return 0.0
    async with _lock:
        until = _cap_cooldowns.get(domain, 0.0)
    return max(0.0, until - time.time())


async def cooldown_snapshot() -> dict[str, float]:
    async with _lock:
        return {d: max(0.0, t - time.time()) for d, t in _cap_cooldowns.items() if t > time.time()}


def active_restriction_for(status: int | None, text: str, url: str = "",
                           retry_after: str | None = None) -> dict | None:
    """Same as classify() but excluding ordinary_error; used as the stop-gate."""
    result = classify(status, text, url, retry_after)
    return result
