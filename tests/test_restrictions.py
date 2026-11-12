"""Restriction classification, cooldowns, backoff — no network involved."""
import asyncio
import email.utils
from datetime import datetime, timezone

from body_mcp import restrictions


def test_rate_limit_by_status_and_retry_after_seconds():
    hit = restrictions.classify(429, "", "https://x.test/", "90")
    assert hit["kind"] == "rate_limit"
    assert hit["retry_after_s"] == 90.0
    assert hit["domain"] == "x.test"


def test_rate_limit_by_text():
    hit = restrictions.classify(200, "Too many requests. Please retry later.", "https://x.test/")
    assert hit["kind"] == "rate_limit"


def test_rate_limit_http_date_retry_after():
    future = datetime.now(timezone.utc).timestamp() + 45
    http_date = email.utils.formatdate(future, usegmt=True)
    hit = restrictions.classify(429, "", "https://x.test/", http_date)
    assert hit["kind"] == "rate_limit"
    assert hit["retry_after_s"] is not None and 0 < hit["retry_after_s"] <= 60


def test_access_denied_403():
    assert restrictions.classify(403, "", "https://x.test/")["kind"] == "access_denied"
    assert restrictions.classify(200, "Access denied for your account", "")["kind"] == "access_denied"


def test_captcha_and_paywall_and_normal():
    assert restrictions.classify(200, "Please verify you are a human", "")["kind"] == "captcha"
    assert restrictions.classify(200, "Subscribe to continue reading", "")["kind"] == "paywall"
    assert restrictions.classify(200, "A perfectly ordinary page", "") is None


def test_ordinary_error_not_restriction():
    assert restrictions.classify(500, "server error", "") is None


def test_backoff_is_bounded_and_jittered():
    from body_mcp import config
    for attempt in range(8):
        assert 0 <= config.backoff_delay(attempt) <= config.backoff_max_s()


def test_cooldown_lifecycle():
    async def go():
        await restrictions.set_cooldown("cooldown-test.example", 60, "test")
        assert await restrictions.cooldown_remaining("cooldown-test.example") > 0
        snap = await restrictions.cooldown_snapshot()
        assert "cooldown-test.example" in snap
        await restrictions.set_cooldown("expired-test.example", 0.001, "test")
        await asyncio.sleep(0.01)
        assert await restrictions.cooldown_remaining("expired-test.example") == 0.0

    asyncio.run(go())
