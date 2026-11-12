"""Permission layer tests: enforcement on code paths, fail-closed behavior, audit."""
import json

import pytest

from body_mcp import permissions


@pytest.fixture
def fresh_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BODY_MCP_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_defaults_keep_public_research_open(fresh_config_dir):
    assert permissions.check("public_web", tool="t", target="https://example.com", risk="low",
                             action="research").allowed
    assert permissions.check("vpn_control", tool="t", target="vpn", risk="low",
                             action="toggle VPN").decision == "deny"
    assert permissions.check("unknown_thing", tool="t", target="x", risk="low",
                             action="anything").decision == "deny"


def test_high_risk_action_blocked_without_consent(fresh_config_dir):
    d = permissions.check("consequential", tool="t", target="x", risk="high", action="delete")
    assert d.allowed is False
    assert d.decision == "needs_consent"


def test_consent_then_approval_required(fresh_config_dir):
    import asyncio

    from body_mcp.approvals import approvals

    permissions.acknowledge_consent()
    d = permissions.check("consequential", tool="t", target="delete everything", risk="high",
                          action="consequential click")
    assert d.allowed is False and d.decision == "ask"

    async def flow():
        await approvals.clear()
        denied = await permissions.authorize(
            "consequential", tool="t", target="delete everything", risk="high",
            action="consequential click")
        assert denied.allowed is False and denied.decision == "ask"

        spec = permissions.required_action_spec("t", "consequential", "delete everything")
        await approvals.issue(spec)
        ok = await permissions.authorize(
            "consequential", tool="t", target="delete everything", risk="high",
            action="consequential click")
        assert ok.allowed is True

        # single use: replaying the same authorization is refused
        replay = await permissions.authorize(
            "consequential", tool="t", target="delete everything", risk="high",
            action="consequential click")
        assert replay.allowed is False
        await approvals.clear()

    asyncio.run(flow())


def test_deny_beats_fresh_approval(fresh_config_dir):
    import asyncio

    from body_mcp.approvals import approvals

    (fresh_config_dir / "permissions.json").write_text(json.dumps(
        {"version": 1, "capabilities": {"consequential": "deny"},
         "allowed_applications": []}), encoding="utf-8")
    permissions.acknowledge_consent()

    async def flow():
        await approvals.clear()
        await approvals.issue(permissions.required_action_spec(
            "t", "consequential", "buy"))
        d = await permissions.authorize("consequential", tool="t", target="buy",
                                        risk="high", action="purchase")
        assert d.allowed is False and d.decision == "deny"
        await approvals.clear()

    asyncio.run(flow())


def test_profile_change_takes_effect_immediately(fresh_config_dir):
    assert permissions.check("public_web", tool="t", target="x", risk="low",
                             action="x").allowed
    (fresh_config_dir / "permissions.json").write_text(json.dumps(
        {"version": 1, "capabilities": {"public_web": "deny"},
         "allowed_applications": []}), encoding="utf-8")
    assert permissions.check("public_web", tool="t", target="x", risk="low",
                             action="x").allowed is False


def test_redact_target_strips_secrets():
    assert "token=abc123" not in permissions.redact_target("https://x.test/p?token=abc123&q=y")
    assert permissions.redact_target("https://u:p@x.test/a?secret=s") == "https://<credentials>@x.test/a"
    assert "123456" not in permissions.redact_target("call 555123456 now")
    assert len(permissions.redact_target("z" * 500)) <= 200


def test_audit_logs_decision_without_secrets(fresh_config_dir):
    permissions.check("public_web", tool="hands_open",
                      target="https://x.test/?token=topsecret", risk="low", action="research")
    permissions.record_audit("hands_open", "public_web", "allow",
                             "https://x.test/?token=topsecret")
    log = (fresh_config_dir / "audit.log").read_text(encoding="utf-8")
    assert "topsecret" not in log
    assert "hands_open" in log


def test_app_launch_requires_allowlist(fresh_config_dir, monkeypatch):
    import asyncio

    from body_mcp import legs

    permissions.acknowledge_consent()  # creates profile with empty allowlist
    result = asyncio.run(legs.open_app("notepad"))
    assert result["success"] is False
    assert "allowlist" in result["message"]

    (fresh_config_dir / "permissions.json").write_text(json.dumps(
        {"version": 1, "capabilities": {"app_launch": "allow"},
         "allowed_applications": ["notepad"]}), encoding="utf-8")
    launched = {}

    class FakeProc:
        def __init__(self, *a, **k):
            launched["cmd"] = a[0]

    monkeypatch.setattr(legs.subprocess, "Popen", FakeProc)
    result = asyncio.run(legs.open_app("notepad"))
    assert result["success"] is True
    assert launched["cmd"][0] == "powershell"
    # and launching something NOT in the allowlist is still refused
    result = asyncio.run(legs.open_app("calc"))
    assert result["success"] is False


def test_app_launch_rejects_path_injection(fresh_config_dir):
    import asyncio

    from body_mcp import legs

    permissions.acknowledge_consent()
    (fresh_config_dir / "permissions.json").write_text(json.dumps(
        {"version": 1, "capabilities": {"app_launch": "allow"},
         "allowed_applications": ["notepad"]}), encoding="utf-8")
    for bad in ("../../windows/system32/cmd.exe", "C:\\evil.exe", "notepad' & calc"):
        result = asyncio.run(legs.open_app(bad))
        assert result["success"] is False


def test_vpn_control_always_denied(fresh_config_dir):
    permissions.acknowledge_consent()
    d = permissions.check("vpn_control", tool="vpn", target="my-vpn", risk="high",
                          action="change VPN connection")
    assert d.allowed is False
