"""The first-install grant and the user-decides rule at a login wall."""
import json
import os

from body_mcp import human_choice, setup, user_browser


def test_setup_steps_are_one_time_and_never_install():
    text = " ".join(setup.steps()).lower()
    assert "one-time grant" in text
    assert "disconnect & forget" in text
    assert "never logs in" in text
    for forbidden in ("winget", "pip install", "ollama pull", "remote-debugging-port"):
        assert forbidden not in text


def test_setup_record_persists_the_grant(monkeypatch, tmp_path):
    monkeypatch.setenv("BODY_MCP_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(setup.bridge, "allow_extension_id", lambda i: {"ok": True})
    result = setup.record("abcdef123456")
    assert result["ok"] is True
    with open(os.path.join(tmp_path, "setup.json"), encoding="utf-8") as handle:
        saved = json.load(handle)
    assert saved["browser_connected"] is True
    assert saved["extension_id"] == "abcdef123456"
    assert setup.status()["permanent_grant"] is True


def test_login_wall_is_the_users_decision():
    d = human_choice.decision("auth_expired", area="research", evidence="Sign in",
                              domain="reddit.com")
    assert d["status"] == "needs_user"
    assert "log in yourself" in d["options"]["user_continues"].lower()
    assert "different safe option" in d["options"]["user_declines"]
    assert "never choose" in d["rule"].lower()
    assert "bypass" in d["agent_must_not"]


def test_all_restriction_kinds_have_a_human_option():
    for kind in ("auth_expired", "captcha", "paywall", "rate_limit", "access_denied"):
        d = human_choice.decision(kind, area="browser")
        assert d["options"]["user_continues"]
        assert d["options"]["user_declines"]


def test_no_browser_refusal_is_actionable_and_safe():
    r = user_browser.refusal()
    assert r["status"] == "needs_user"
    assert "python -m body_mcp.bridge" in " ".join(r["data"]["steps"])
    assert "never logs in" in r["data"]["note"]
