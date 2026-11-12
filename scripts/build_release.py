"""Build a downloadable Body-MCP release for the current platform.

    python scripts/build_release.py                # build for this machine
    python scripts/build_release.py --platform windows-x64
    python scripts/build_release.py --list         # show the release matrix

What it produces (in dist/):
    body-mcp-<version>-<platform>.zip    the source tree + the MCP entry points
    body-mcp-<version>-<platform>.sha256  the checksum
    body-mcp-<version>-<platform>.json    the manifest (files, sizes, sha256, licences)
    THIRD_PARTY_NOTICES.md                 attribution for every bundled component

The bundled OCR engine is OPTIONAL and never downloaded automatically: the build
records what is missing and where to get it (see docs/ocr.md). A release is only
marked "install-and-run" when the packaged artifact was actually built and tested on
that platform - which is recorded per platform in docs/release.md.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import zipfile
from datetime import datetime, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DIST = os.path.join(ROOT, "dist")

PLATFORMS = {
    "windows-x64": {"system": "Windows", "arch": "x64", "tested": True,
                    "ocr_bundle": "vendor/tesseract/windows-x64"},
    "macos-arm64": {"system": "Darwin", "arch": "arm64", "tested": False,
                    "ocr_bundle": "vendor/tesseract/macos-arm64"},
    "macos-x64": {"system": "Darwin", "arch": "x86_64", "tested": False,
                  "ocr_bundle": "vendor/tesseract/macos-x64"},
    "linux-x64": {"system": "Linux", "arch": "x86_64", "tested": False,
                  "ocr_bundle": "vendor/tesseract/linux-x64"},
}

INCLUDED = ["src", "docs", "examples", "scripts", "tests", "pyproject.toml", "README.md",
            "AGENTS.md", "LICENSE", "THIRD_PARTY_NOTICES.md"]


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_platform() -> str:
    system = platform.system().lower()
    machine = (platform.machine() or "").lower()
    arch = "x64" if machine in ("amd64", "x86_64") else (
        "arm64" if machine in ("arm64", "aarch64") else machine)
    if system == "windows":
        return f"windows-{arch}"
    if system == "darwin":
        return f"macos-{arch}"
    return f"linux-{arch}"


def version() -> str:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from body_mcp import __version__

    return __version__


def ocr_state() -> dict:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from body_mcp.ocr import providers

    return {entry["provider"]: entry for entry in providers()}


def build(platform_tag: str) -> int:
    if platform_tag not in PLATFORMS:
        print(f"error: unknown platform {platform_tag!r}; known: {sorted(PLATFORMS)}")
        return 2
    info = PLATFORMS[platform_tag]
    tag = version()
    os.makedirs(DIST, exist_ok=True)
    archive = os.path.join(DIST, f"body-mcp-{tag}-{platform_tag}.zip")
    files: list[dict] = []

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in INCLUDED:
            source = os.path.join(ROOT, item)
            if not os.path.exists(source):
                continue
            if os.path.isdir(source):
                for root, _dirs, names in os.walk(source):
                    if "__pycache__" in root or ".pytest_cache" in root:
                        continue
                    for name in names:
                        if name.endswith(".pyc"):
                            continue
                        full = os.path.join(root, name)
                        relative = os.path.relpath(full, ROOT)
                        zf.write(full, os.path.join(f"body-mcp-{tag}-{platform_tag}", relative))
                        files.append({"path": relative, "bytes": os.path.getsize(full)})
            else:
                zf.write(source, os.path.join(f"body-mcp-{tag}-{platform_tag}", item))
                files.append({"path": item, "bytes": os.path.getsize(source)})
        # the bundled OCR engine, only if it was placed there by the packager
        bundle = os.path.join(ROOT, info["ocr_bundle"])
        if os.path.isdir(bundle):
            for root, _dirs, names in os.walk(bundle):
                for name in names:
                    full = os.path.join(root, name)
                    relative = os.path.relpath(full, ROOT)
                    zf.write(full, os.path.join(f"body-mcp-{tag}-{platform_tag}", relative))
                    files.append({"path": relative, "bytes": os.path.getsize(full)})

    for entry in files:
        entry["sha256"] = sha256_of(os.path.join(ROOT, entry["path"]))

    checksum = sha256_of(archive)
    with open(archive + ".sha256", "w", encoding="utf-8") as handle:
        handle.write(f"{checksum}  {os.path.basename(archive)}\n")

    engines = ocr_state()
    manifest = {
        "name": "body-mcp",
        "version": tag,
        "platform": platform_tag,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "built_on": f"{platform.system()} {platform.machine()} (python {platform.python_version()})",
        "artifact": {"file": os.path.basename(archive),
                     "bytes": os.path.getsize(archive), "sha256": checksum},
        "python_requires": ">=3.11",
        "integrity": {"files": files},
        "ocr_engines": engines,
        "ocr_bundled": os.path.isdir(os.path.join(ROOT, info["ocr_bundle"])),
        "integration_tested_on_this_platform": info["tested"],
        "license": "MIT",
        "third_party_notices": "THIRD_PARTY_NOTICES.md",
        "install": [
            f"unzip {os.path.basename(archive)}",
            "python -m venv .venv",
            ".venv\\Scripts\\activate   (or: source .venv/bin/activate)",
            "pip install -e .",
            "python -m playwright install chromium",
            "python -m body_mcp.doctor",
        ],
    }
    with open(os.path.join(DIST, f"body-mcp-{tag}-{platform_tag}.json"), "w",
              encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    print(f"artifact : {archive}")
    print(f"size     : {manifest['artifact']['bytes'] / 1024:.0f} KB")
    print(f"sha256   : {checksum}")
    print(f"ocr      : bundled={manifest['ocr_bundled']} "
          f"engines={ {k: v.get('available') for k, v in engines.items()} }")
    print(f"platform : {platform_tag} "
          f"(integration tested here: {info['tested']})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a Body-MCP release")
    parser.add_argument("--platform", default=None, choices=sorted(PLATFORMS))
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list:
        print(f"{'platform':<16} {'integration tested':<20} bundled OCR dir")
        for tag, info in PLATFORMS.items():
            print(f"{tag:<16} {str(info['tested']):<20} {info['ocr_bundle']}")
        return 0
    return build(args.platform or current_platform())


if __name__ == "__main__":
    sys.exit(main())
