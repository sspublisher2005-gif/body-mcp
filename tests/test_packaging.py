"""Packaging: what a released artifact must contain and declare."""
import json
import os
import tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def _pyproject() -> dict:
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as handle:
        return tomllib.load(handle)


def test_project_metadata_is_complete():
    data = _pyproject()
    project = data["project"]
    assert project["name"] == "body-mcp"
    assert project["version"] == "0.4.0"
    assert project["requires-python"] == ">=3.11"
    assert project["license"] == "MIT"
    assert project["description"]
    assert project["scripts"]["body-mcp"] == "body_mcp.server:main"
    assert project["scripts"]["body-doctor"] == "body_mcp.doctor:main"
    assert "urls" in project and project["urls"]["Homepage"]


def test_the_core_install_stays_small():
    data = _pyproject()
    assert data["project"]["dependencies"] == ["mcp>=2,<3", "playwright>=1.65"]
    extras = data["project"]["optional-dependencies"]
    assert {"desktop", "voice", "all", "dev"} <= set(extras)
    # the optional engines are NOT required to install the package
    assert "pynput" not in json.dumps(data["project"])


def test_licences_and_notices_ship_with_the_project():
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "README.md"):
        path = os.path.join(ROOT, name)
        assert os.path.isfile(path), name
        assert os.path.getsize(path) > 100, name


def test_the_built_wheel_exists_when_a_build_was_made():
    import glob

    wheels = glob.glob(os.path.join(ROOT, "dist", "body_mcp-*.whl"))
    if not wheels:
        return  # not built in this checkout - the CI job builds it first
    newest = max(wheels, key=os.path.getmtime)
    assert os.path.getsize(newest) < 5 * 1024 * 1024, "the wheel should stay small"
