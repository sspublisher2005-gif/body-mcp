"""Legs: move between destinations — open applications (permission-gated).

Implemented: launching allowlisted installed applications.
  - User-defined allowlist in permissions.json ("allowed_applications") — empty by default.
  - Plain app names only (no paths, no quotes) — cannot launch arbitrary binaries.
  - Launched via Start-Process with stdin detached from the MCP channel.

Website navigation is hands_open. Window switching and VPN control are NOT implemented.
"""
import re
import subprocess

from . import permissions

APP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-() ]{0,80}$")


async def open_app(application: str) -> dict:
    target = (application or "").strip()
    if not APP_NAME_RE.match(target) or "/" in target or "\\" in target or "'" in target:
        return {"success": False,
                "message": "refusing application name — expected a plain app name or command (e.g. 'notepad')",
                "data": {"application": None, "reason": "invalid name"}}

    profile = permissions.load_profile()
    allowlist = {a.lower() for a in profile["allowed_applications"]}
    if target.lower() not in allowlist:
        permissions.record_audit("legs_open_app", "app_launch", "deny", target)
        return {"success": False,
                "message": (f"application {target!r} is not in your allowlist. "
                            f"Add it to allowed_applications in {permissions._config_dir()}\\permissions.json "
                            "(USER edit, not agent), then ask again."),
                "data": {"application": target, "permission": "not_in_allowlist"}}

    decision = await permissions.authorize(
        "app_launch", tool="legs_open_app", target=target,
        risk="high", action=f"launch application {target!r}",
        url=None, task_id=None)
    if not decision.allowed:
        permissions.record_audit("legs_open_app", "app_launch", decision.decision, target)
        spec = permissions.required_action_spec("legs_open_app", "app_launch", target, None, None)
        return {"success": False, "message": decision.message,
                "data": {"application": target, "permission": decision.decision,
                         "required_action": spec}}

    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", f"Start-Process '{target}'"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        return {"success": False, "message": f"launch failed: {type(exc).__name__}: {exc}",
                "data": {"application": target}}
    permissions.record_audit("legs_open_app", "app_launch", "allow", target)
    return {"success": True, "message": f"launched {target}",
            "data": {"application": target, "how": "Start-Process"}}
