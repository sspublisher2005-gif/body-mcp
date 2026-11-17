"""Two small, safe default permission profiles.

    python -m body_mcp.profiles                 # list them
    python -m body_mcp.profiles browser --show  # print one
    python -m body_mcp.profiles browser --apply # copy it to your profile dir

`--apply` never overwrites your current permissions.json without first copying
it to permissions.json.bak. It prints exactly what it did. It never changes a
secret, a consent marker or the audit log.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from importlib import resources

NAMES = ("browser", "windows-desktop")


def load(name: str) -> dict:
    """Read the named profile from the package (works from a wheel too)."""
    if name not in NAMES:
        raise ValueError(f"unknown profile {name!r}; choose from {', '.join(NAMES)}")
    path = resources.files("body_mcp").joinpath("profiles", f"{name}.json")
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("version") != 1 or not isinstance(data.get("capabilities"), dict):
        raise ValueError(f"malformed profile: {name}")
    return data


def config_dir() -> str:
    """The same directory permissions.py uses (BODY_MCP_CONFIG_DIR wins)."""
    override = os.environ.get("BODY_MCP_CONFIG_DIR")
    if override:
        return override
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")),
                        ".config", "body_mcp")


def apply(name: str) -> dict:
    """Copy the profile to permissions.json, keeping a backup of the old one."""
    profile = load(name)
    directory = config_dir()
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, "permissions.json")
    backup = target + ".bak"
    backed_up = False
    if os.path.isfile(target):
        shutil.copy2(target, backup)
        backed_up = True
    with open(target, "w", encoding="utf-8") as handle:
        json.dump({k: profile[k] for k in ("version", "capabilities",
                                           "allowed_applications")},
                  handle, indent=2)
    return {"applied": name, "target": target, "backup": backup if backed_up else None,
            "description": profile.get("description", "")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Body-MCP default permission profiles")
    parser.add_argument("name", nargs="?", choices=NAMES, help="profile to use")
    parser.add_argument("--show", action="store_true", help="print the profile as JSON")
    parser.add_argument("--apply", action="store_true", help="write it to your profile dir")
    args = parser.parse_args(argv)
    if not args.name:
        for name in NAMES:
            print(f"{name:<18} {load(name).get('description', '')}")
        print("\nUse: python -m body_mcp.profiles <name> --show|--apply")
        return 0
    profile = load(args.name)
    if args.apply:
        result = apply(args.name)
        print(f"applied {result['applied']} -> {result['target']}")
        print(f"backup : {result['backup'] or '(no previous file)'}")
        print(result["description"])
        return 0
    print(json.dumps(profile, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
