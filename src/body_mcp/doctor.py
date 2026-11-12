"""body doctor - read-only diagnostics for Body-MCP.

    python -m body_mcp.doctor          # full report
    python -m body_mcp.doctor --json   # machine-readable

Rules: this command NEVER changes permissions, never acknowledges consent, never
downloads a model, never touches global agent configuration, and never opens a
browser. It only reports what is true right now, with a remediation for each
finding.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

OK = "OK"
WARN = "WARN"
FAIL = "FAIL"

FINDINGS: list[dict] = []


def _add(name: str, status: str, detail: str, impact: str = "", fix: str = "") -> None:
    FINDINGS.append({"check": name, "status": status, "detail": detail,
                      "impact": impact, "fix": fix})


def _check_runtime() -> None:
    ver = platform.python_version()
    if sys.version_info >= (3, 11):
        _add("python", OK, f"{ver} ({sys.executable})")
    else:
        _add("python", FAIL, f"{ver} is below the supported minimum (3.11)",
             "the server will not start", "install Python 3.11+ and recreate the venv")
    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    _add("virtualenv", OK if in_venv else WARN,
         f"venv={'yes' if in_venv else 'no'} (prefix {sys.prefix})",
         "" if in_venv else "a global install can shadow your dependencies",
         "python -m venv .venv && .venv\\Scripts\\activate" if not in_venv else "")


def _check_package() -> None:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            dist = version("body-mcp")
        except PackageNotFoundError:
            dist = None
        from . import __version__

        if dist and dist != __version__:
            _add("package", WARN, f"installed {dist}, source tree {__version__}",
                 "the running code may not be the installed code",
                 "pip install -e . (or use the venv that has the package installed)")
        else:
            _add("package", OK, f"body-mcp {dist or __version__}")
    except Exception as exc:
        _add("package", WARN, f"version check failed: {exc}")


def _check_mcp_sdk() -> None:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            sdk = version("mcp")
        except PackageNotFoundError:
            sdk = None
        if sdk is None:
            _add("mcp-sdk", FAIL, "the mcp package is not installed",
                 "the server cannot speak MCP", "pip install -U 'mcp>=2,<3'")
            return
        try:
            from mcp.server.mcpserver import MCPServer  # noqa: F401
            api = "MCPServer (v2 API)"
        except Exception:
            try:
                from mcp.server.fastmcp import FastMCP  # noqa: F401
                api = "FastMCP (v1 API)"
            except Exception as exc:
                _add("mcp-sdk", FAIL, f"mcp {sdk} installed but no server API importable: {exc}",
                     "the server cannot start", "pip install -U 'mcp>=2,<3'")
                return
        _add("mcp-sdk", OK, f"mcp {sdk} - {api}")
    except Exception as exc:
        _add("mcp-sdk", WARN, f"SDK check failed: {exc}")


def _check_config() -> None:
    from . import permissions

    cfg_dir = Path(permissions._config_dir())
    if not cfg_dir.exists():
        _add("config-dir", WARN, f"{cfg_dir} does not exist yet",
             "it is created when you acknowledge consent",
             "python -m body_mcp.consent")
    else:
        try:
            probe = cfg_dir / ".doctor-write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            _add("config-dir", OK, str(cfg_dir))
        except Exception as exc:
            _add("config-dir", FAIL, f"{cfg_dir} is not writable: {exc}",
                 "permissions and consent cannot be stored",
                 "fix the folder permissions or set BODY_MCP_CONFIG_DIR")

    profile = cfg_dir / "permissions.json"
    if profile.exists():
        try:
            data = json.loads(profile.read_text(encoding="utf-8"))
            caps = data.get("capabilities", {})
            unknown = [c for c in caps if c not in permissions.DEFAULT_CAPABILITIES]
            if unknown:
                _add("permissions", WARN,
                     f"unknown capability names ignored (deny by default): {unknown}",
                     "those capabilities can never be used",
                     f"valid names: {sorted(permissions.DEFAULT_CAPABILITIES)}")
            else:
                _add("permissions", OK, f"{profile} (capabilities: {len(caps)})")
        except Exception as exc:
            _add("permissions", FAIL, f"{profile} is not valid JSON: {exc}",
                 "the profile cannot be read - every capability denies",
                 "fix the JSON or delete the file to regenerate defaults")
    else:
        _add("permissions", WARN, f"no permissions.json yet ({profile})",
             "defaults apply (public_web allowed, consequential/app_launch ask)",
             "run any body-mcp tool once, or copy the defaults from docs/safety.md")

    if permissions.consent_acknowledged():
        _add("consent", OK, "consent acknowledged")
    else:
        _add("consent", WARN, "consent NOT acknowledged",
             "high-risk actions are refused (fail-closed by design)",
             "python -m body_mcp.consent")

    audit = cfg_dir / "audit.log"
    if audit.exists():
        size = audit.stat().st_size
        _add("audit-log", OK, f"{audit} ({size} bytes, plaintext, local only)")


def _check_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except Exception as exc:
        _add("playwright", FAIL, f"playwright is not importable: {exc}",
             "browser control is unavailable", "pip install -U playwright && python -m playwright install chromium")
        return
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = Path(p.chromium.executable_path)
            if path.exists():
                _add("playwright-browser", OK, f"chromium binary present ({path})")
            else:
                _add("playwright-browser", FAIL, f"chromium binary missing at {path}",
                     "no browser can be launched",
                     "python -m playwright install chromium")
    except Exception as exc:
        _add("playwright-browser", FAIL, f"could not resolve the chromium binary: {exc}",
             "no browser can be launched", "python -m playwright install chromium")


def _check_current_browser() -> None:

    from . import attach

    status = attach.attached_status()
    if status.get("attached"):
        _add("current-browser", OK, f"attached to {status.get('title')} ({status.get('url')})")
        return
    listening = False
    for port in (9222,):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as r:
                listening = r.status == 200
        except Exception:
            listening = False
    if listening:
        _add("current-browser", WARN,
             "a CDP debug port answers on 127.0.0.1:9222 but Body-MCP is not attached",
             "that port is unauthenticated - any local process can drive that browser",
             "attach_browser('http://127.0.0.1:9222') when you want it, "
             "otherwise restart the browser without --remote-debugging-port")
    else:
        _add("current-browser", OK,
             "not attached (managed browser mode) - no CDP port is open")


def _check_ocr() -> None:
    from .config import tesseract_cmd

    cmd = tesseract_cmd()
    if not cmd:
        _add("ocr", WARN, "Tesseract OCR not found",
             "desktop OCR is unavailable (browser eyes still work)",
             r"winget install -e --id UB-Mannheim.TesseractOCR")
        return
    try:
        out = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=10)
        ver = (out.stdout or out.stderr or "").strip().splitlines()[0]
        _add("ocr", OK, f"{cmd} - {ver}")
    except Exception as exc:
        _add("ocr", WARN, f"{cmd} exists but did not run: {exc}",
             "desktop OCR may fail", "run 'tesseract --version' manually")


def _check_audio() -> None:
    try:
        import sounddevice as sd  # noqa: F401
    except Exception as exc:
        _add("microphone", WARN, f"sounddevice not installed: {exc}",
             "ears_listen is unavailable (browser tools unaffected)",
             "pip install sounddevice")
        return
    try:
        import sounddevice as sd

        devices = sd.query_devices()
        inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
        if inputs:
            _add("microphone", OK, f"{len(inputs)} input device(s) visible",
                 "", "")
        else:
            _add("microphone", WARN, "no input device visible",
                 "ears_listen cannot capture audio",
                 "connect a microphone and grant Windows privacy access")
    except Exception as exc:
        _add("microphone", WARN, f"audio device query failed: {exc}",
             "ears_listen may fail", "check Windows microphone privacy settings")

    from .config import whisper_model

    model = whisper_model()
    cache = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface"))
    has_model = cache.exists() and any(cache.rglob("model.bin"))
    _add("speech-to-text", OK if has_model else WARN,
         f"faster-whisper model {model!r} "
         + ("present in the local HF cache" if has_model else "not downloaded yet"),
         "" if has_model else "the first ears_listen call would download it (needs network + disk)",
         "" if has_model else "download it explicitly, or pick a smaller model: BODY_MCP_WHISPER_MODEL=tiny.en")


def _check_agents() -> None:
    hints = {
        "opencode": "opencode mcp add body-dev -- python -m body_mcp.server",
        "claude": "claude mcp add body-dev -- python -m body_mcp.server",
        "codex": "codex mcp add body-dev -- python -m body_mcp.server",
    }
    found = []
    for name, cmd in hints.items():
        exe = shutil.which(name)
        if exe:
            found.append(f"{name} ({exe}) -> {cmd}")
    if found:
        _add("mcp-clients", OK, "detected: " + "; ".join(found))
    else:
        _add("mcp-clients", WARN, "no known MCP client CLI found on PATH",
             "you still need one MCP-capable agent to use Body-MCP",
             "install opencode / claude / codex, then add the server with the commands above")


def _check_tts() -> None:
    """Local speech output — report what is actually available."""
    from . import tts

    info = tts.available()
    if info.get("available"):
        _add("text-to-speech", OK,
             f"{info.get('engine')} available ({len(info.get('voices') or [])} voice(s)), local, no download")
    else:
        _add("text-to-speech", WARN, f"not available: {info.get('reason')}",
             "no read-aloud capability", "install a system voice or add an optional TTS engine")


def run_checks() -> list[dict]:
    FINDINGS.clear()
    for fn in (_check_runtime, _check_package, _check_mcp_sdk, _check_config,
               _check_playwright, _check_current_browser, _check_ocr, _check_audio,
               _check_agents, _check_tts):
        try:
            fn()
        except Exception as exc:  # a broken check must not abort the report
            _add(fn.__name__.replace("_check_", ""), WARN, f"check crashed: {exc}")
    return list(FINDINGS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Body-MCP diagnostics (read-only)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    with contextlib.suppress(Exception):  # windows consoles default to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    findings = run_checks()
    if args.json:
        print(json.dumps({"platform": platform.platform(), "findings": findings}, indent=2))
    else:
        print(f"Body-MCP doctor - {platform.platform()}\n")
        width = max(len(f["check"]) for f in findings)
        for f in findings:
            mark = {OK: "ok  ", WARN: "warn", FAIL: "FAIL"}[f["status"]]
            print(f"[{mark}] {f['check']:<{width}}  {f['detail']}")
            if f["impact"]:
                print(f"       impact: {f['impact']}")
            if f["fix"]:
                print(f"       fix:    {f['fix']}")
        counts = {s: sum(1 for f in findings if f["status"] == s) for s in (OK, WARN, FAIL)}
        print(f"\n{counts[OK]} ok, {counts[WARN]} warnings, {counts[FAIL]} failures "
              f"- nothing was changed by this command")
    return 1 if any(f["status"] == FAIL for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
