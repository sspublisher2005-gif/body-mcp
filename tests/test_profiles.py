"""The two default profiles: small, safe, and reversible."""
import json

import pytest

from body_mcp import permissions, profiles


def test_both_profiles_load_from_the_package():
    for name in profiles.NAMES:
        data = profiles.load(name)
        assert data["version"] == 1
        assert data["name"] == name
        assert data["description"]
        assert "capabilities" in data


def test_browser_profile_cannot_drive_native_apps():
    caps = profiles.load("browser")["capabilities"]
    assert caps["desktop_control"] == "deny"
    assert caps["desktop_capture"] == "deny"
    assert caps["app_launch"] == "deny"
    assert caps["public_web"] == "allow"
    assert caps["chrome_attach"] == "ask"


def test_windows_desktop_profile_gates_control_but_allows_capture():
    caps = profiles.load("windows-desktop")["capabilities"]
    assert caps["desktop_capture"] == "allow"
    assert caps["desktop_control"] == "ask"
    assert caps["consequential"] == "ask"
    assert caps["local_files"] == "deny"
    assert caps["shell"] == "deny"


def test_profiles_only_use_known_capabilities():
    known = set(permissions.DEFAULT_CAPABILITIES)
    for name in profiles.NAMES:
        caps = set(profiles.load(name)["capabilities"])
        assert caps <= known, (name, caps - known)


def test_unknown_profile_is_refused():
    with pytest.raises(ValueError):
        profiles.load("admin")


def test_apply_keeps_a_backup(tmp_path, monkeypatch):
    monkeypatch.setenv("BODY_MCP_CONFIG_DIR", str(tmp_path))
    original = tmp_path / "permissions.json"
    original.write_text(json.dumps({"version": 1, "capabilities": {"shell": "allow"}}))
    result = profiles.apply("browser")
    assert result["backup"] == str(original) + ".bak"
    backup = json.loads((tmp_path / "permissions.json.bak").read_text())
    assert backup["capabilities"]["shell"] == "allow", "the old file must be recoverable"
    applied = json.loads(original.read_text())
    assert applied["capabilities"]["desktop_control"] == "deny"
    assert applied["capabilities"]["shell"] == "deny"


def test_apply_with_no_previous_file(tmp_path, monkeypatch):
    monkeypatch.setenv("BODY_MCP_CONFIG_DIR", str(tmp_path))
    result = profiles.apply("windows-desktop")
    assert result["backup"] is None
    assert (tmp_path / "permissions.json").is_file()


def test_cli_lists_and_shows(capsys):
    assert profiles.main([]) == 0
    out = capsys.readouterr().out
    assert "browser" in out and "windows-desktop" in out
    assert profiles.main(["browser", "--show"]) == 0
    assert '"capabilities"' in capsys.readouterr().out
