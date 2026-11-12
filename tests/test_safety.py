"""Pure safety-policy tests: detection, dangerous buttons, URL policy."""
from body_mcp import browser, safety


def test_sensitive_page_detected():
    scan = safety.scan_text("Sign in. Password required to continue. Enter your OTP.")
    assert scan["sensitive"] is True
    assert scan["restricted"] is False
    assert scan["mode"] == "sensitive"


def test_captcha_page_detected_as_restricted():
    scan = safety.scan_text("Please verify you are a human. CAPTCHA required.")
    assert scan["restricted"] is True
    assert scan["mode"] == "restricted"


def test_rate_limit_page_detected_as_restricted():
    scan = safety.scan_text("Error 429: Too Many Requests. Rate limit exceeded.")
    assert scan["restricted"] is True


def test_paywall_detected_as_restricted():
    scan = safety.scan_text("Subscribe to continue reading this article.")
    assert scan["restricted"] is True


def test_normal_public_page_is_normal():
    scan = safety.scan_text("The best open-source computer-use agents of 2026, compared.")
    assert scan["mode"] == "normal"


def test_dangerous_buttons_require_approval():
    assert safety.is_dangerous_label("Submit")
    assert safety.is_dangerous_label("Pay now")
    assert safety.is_dangerous_label("Delete account")
    assert safety.is_dangerous_label("Send message")
    assert safety.is_dangerous_label("Confirm purchase")
    assert safety.is_dangerous_label("Download installer")
    assert not safety.is_dangerous_label("Save draft settings")


def test_sensitive_fields_blocked():
    assert safety.is_sensitive_field({"type": "password"})
    assert safety.is_sensitive_field({"name": "card_number"})
    assert safety.is_sensitive_field({"autocomplete": "cc-csc"})
    assert safety.is_sensitive_field({"placeholder": "CVV"})
    assert not safety.is_sensitive_field({"name": "name", "type": "text"})


def test_url_policy_refuses_embedded_credentials():
    verdict = browser.check_url("https://user:pass@example.com/")
    assert verdict["ok"] is False


def test_url_policy_refuses_non_web_scheme():
    assert browser.check_url("javascript:alert(1)")["ok"] is False


def test_url_policy_file_scheme_limited_to_cwd():
    import os
    outside = "file:///etc/passwd" if os.sep == "/" else "file:///C:/etc/passwd"
    assert browser.check_url(outside)["ok"] is False
    inside = "file:///" + os.path.realpath(os.getcwd()).replace("\\", "/") + "/ok.txt"
    assert browser.check_url(inside)["ok"] is True


def test_url_policy_allows_https():
    assert browser.check_url("https://example.com/")["ok"] is True
