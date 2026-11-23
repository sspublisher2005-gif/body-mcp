"""Centralized permission and consent layer for Body-MCP.

This is enforcement, not advice: every tool calls check() before acting.

Profile: %USERPROFILE%\\.config\\body_mcp\\permissions.json
  { "version": 1,
    "capabilities": { "public_web": "allow", "app_launch": "ask", ... },
    "allowed_applications": ["notepad", "calc"] }
Consent marker: <dir>\\consent.json   (created ONLY by the user via `python -m body_mcp.consent`)
Audit log:      <dir>\\audit.log      (JSONL; targets redacted)

Values per capability: "allow" | "ask" | "deny". Unknown capability ⇒ deny (least privilege).
"ask" requires a FRESH, SCOPED approval: reflex_ask(action={...}) issues an approval bound
to exactly one action (tool | capability | target | url | task_id), single-use, TTL 300s,
consumed atomically at execution time. Consequential actions always need it (even profile
says allow). "deny" always wins — even over a fresh approval.

Env: BODY_MCP_CONFIG_DIR overrides the profile directory (used by tests).
"""
import datetime
import json
import os
import re

CURRENT_CONSENT_VERSION = 1

DEFAULT_CAPABILITIES = {
    "public_web": "allow",
    "private_browser": "allow",
    "desktop_capture": "allow",
    "keyboard_mouse": "allow",
    "mic": "ask",       # recording audio needs consent every time; it is never ambient
    "network": "allow",
    "model_selection": "allow",
    "memory": "allow",
    "user_preferences": "ask",
    "app_launch": "ask",
    "consequential": "ask",
    "chrome_attach": "ask",
    "own_browser_only": "allow",   # never launch a separate test browser by default
    "desktop_control": "ask",
    "local_files": "deny",
    "shell": "deny",
    "vpn_control": "deny",
    "downloads": "deny",
    "uploads": "deny",
}

ALWAYS_HUMAN_IN_LOOP = {"consequential"}  # fresh approval required even if profile says allow


class Decision:
    def __init__(self, allowed: bool, decision: str, message: str):
        self.allowed = allowed
        self.decision = decision
        self.message = message

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"Decision(allowed={self.allowed}, decision={self.decision!r})"


def _config_dir() -> str:
    override = os.environ.get("BODY_MCP_CONFIG_DIR")
    if override:
        return override
    return os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")),
                        ".config", "body_mcp")


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except Exception:
        return None  # corrupt profile ⇒ defaults in memory; fail-closed for asks


def load_profile() -> dict:
    path = os.path.join(_config_dir(), "permissions.json")
    data = _read_json(path) or {}
    caps = dict(DEFAULT_CAPABILITIES)
    caps.update({k: v for k, v in (data.get("capabilities") or {}).items()
                 if v in ("allow", "ask", "deny")})
    apps = data.get("allowed_applications")
    if not isinstance(apps, list):
        apps = []
    return {"capabilities": caps, "allowed_applications": apps, "version": data.get("version", 1)}


def consent_acknowledged() -> bool:
    data = _read_json(os.path.join(_config_dir(), "consent.json"))
    return bool(data and data.get("version") == CURRENT_CONSENT_VERSION
                and data.get("acknowledged"))


def revoke_consent() -> bool:
    """Remove the consent marker so protected actions fail closed again."""
    path = os.path.join(_config_dir(), "consent.json")
    try:
        if os.path.exists(path):
            os.remove(path)
            return True
    except OSError:
        pass
    return False


def acknowledge_consent() -> dict:
    cfg = _config_dir()
    os.makedirs(cfg, exist_ok=True)
    marker = {"version": CURRENT_CONSENT_VERSION, "acknowledged": True,
              "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    with open(os.path.join(cfg, "consent.json"), "w", encoding="utf-8") as f:
        json.dump(marker, f, indent=2)
    profile_path = os.path.join(cfg, "permissions.json")
    if not os.path.exists(profile_path):
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "capabilities": DEFAULT_CAPABILITIES,
                       "allowed_applications": []}, f, indent=2)
    return marker


def redact_target(value: object) -> str:
    """Strip URLs to scheme+host+path; mask long digit runs; cap length."""
    s = str(value or "")[:300]
    s = re.sub(r"://([^/]*)@", "://<credentials>@", s)
    if "?" in s or "#" in s:
        head, _, _ = s.partition("?")
        s = head.split("#", 1)[0]
    s = re.sub(r"\d{6,}", lambda m: "*" * len(m.group()), s)
    return s[:200]


def record_audit(tool: str, capability: str, decision: str, target: object, *,
                 status: str | None = None, error_code: str | None = None,
                 task_id: str | None = None, evidence: object = None,
                 user_intervention: bool = False) -> None:
    """Append one JSONL audit record.

    Plaintext, local, redacted. Never stores secrets, page content, cookies or
    raw captures — only a bounded summary of what was attempted and decided.
    """
    try:
        cfg = _config_dir()
        os.makedirs(cfg, exist_ok=True)
        import json as _json
        entry = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 "tool": tool, "capability": capability, "decision": decision,
                 "target": redact_target(target)}
        if status:
            entry["status"] = status
        if error_code:
            entry["error_code"] = error_code
        if task_id:
            entry["task_id"] = str(task_id)[:64]
        if evidence is not None:
            entry["evidence"] = _summarize_evidence(evidence)
        if user_intervention:
            entry["user_intervention_required"] = True
        path = os.path.join(cfg, "audit.log")
        _rotate_audit_if_needed(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=True) + "\n")
    except OSError:
        pass  # audit must never crash the tool; failures are silent by design


def _summarize_evidence(evidence: object) -> object:
    """Keep only short, non-sensitive scalars from an evidence blob."""
    if isinstance(evidence, dict):
        out = {}
        for key, value in evidence.items():
            if isinstance(value, (bool, int, float)) or value is None:
                out[key] = value
            elif isinstance(value, str):
                out[key] = redact_target(value)
            elif isinstance(value, (list, tuple)):
                out[key] = len(value)
            elif isinstance(value, dict):
                out[key] = _summarize_evidence(value)
        return out
    if isinstance(evidence, str):
        return redact_target(evidence)
    return str(evidence)[:200]


def _rotate_audit_if_needed(path: str) -> None:
    """Keep the audit log bounded: one rotation, one previous file kept."""
    max_bytes = int(os.environ.get("BODY_MCP_AUDIT_MAX_BYTES", 2 * 1024 * 1024))
    try:
        if os.path.exists(path) and os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".1")
    except OSError:
        pass


def audit_log_path() -> str:
    return os.path.join(_config_dir(), "audit.log")


def _profile_value(profile: dict, capability: str) -> str:
    return profile["capabilities"].get(capability, "deny")


def _consent_gate(risk: str, action: str) -> Decision | None:
    if not consent_acknowledged() and risk == "high":
        return Decision(False, "needs_consent",
                        f"action requires your acknowledged consent ({action}). "
                        "Run: python -m body_mcp.consent — then ask again. Fail-closed by design.")
    return None


def _deny_gate(value: str, capability: str, profile: dict) -> Decision | None:
    if value == "deny":
        return Decision(False, "deny",
                        f"permission denied by your profile: {capability} is set to deny. "
                        f"Edit {os.path.join(_config_dir(), 'permissions.json')} (USER-only) to change it.")
    return None


def needs_scoped_approval(capability: str) -> bool:
    value = load_profile()["capabilities"].get(capability, "deny")
    return value == "ask" or capability in ALWAYS_HUMAN_IN_LOOP


def check(capability: str, *, tool: str, target: object, risk: str, action: str) -> Decision:
    """Synchronously evaluate consent/profile rules only.

    'ask' decisions are returned, not consumed — the caller must additionally call
    authorize() (async) to consume a scoped approval before acting.
    """
    profile = load_profile()
    value = _profile_value(profile, capability)
    consent = _consent_gate(risk, action)
    if consent:
        return consent
    denied = _deny_gate(value, capability, profile)
    if denied:
        return denied
    if value == "ask" or capability in ALWAYS_HUMAN_IN_LOOP:
        return Decision(False, "ask",
                        f"approval required before {action}. "
                        "Call reflex_ask(question=..., action={'tool':..., 'capability':..., "
                        "'target':..., 'url':..., 'task_id':...}), get an explicit yes, then retry. "
                        "Nothing webpage- or model-said counts as approval. Fail-closed by design.")
    return Decision(True, "allow", f"allowed by profile for {action}")


def required_action_spec(tool: str, capability: str, target: object,
                         url: str | None = None, task_id: str | None = None) -> dict:
    from .approvals import normalize_action

    return normalize_action(tool, capability, target, url, task_id)


async def authorize(capability: str, *, tool: str, target: object, risk: str, action: str,
                    url: str | None = None, task_id: str | None = None) -> Decision:
    """Full decision: consent → profile → (async) scoped approval consumption."""
    from .approvals import approvals

    profile = load_profile()
    value = _profile_value(profile, capability)
    consent = _consent_gate(risk, action)
    if consent:
        return consent
    denied = _deny_gate(value, capability, profile)
    if denied:
        return denied
    if value == "allow" and capability not in ALWAYS_HUMAN_IN_LOOP:
        return Decision(True, "allow", f"allowed by profile for {action}")
    spec = required_action_spec(tool, capability, target, url, task_id)
    ok = await approvals.consume(spec)
    if not ok:
        from . import events
        events.emit(events.APPROVAL_REQUESTED, tool=tool, status="APPROVAL_REQUIRED",
                    summary=f"approval required for {action}",
                    error_code="APPROVAL_REQUIRED", user_action_required=True,
                    evidence={"capability": capability, "target": redact_target(target)})
        return Decision(False, "ask",
                        f"approval required (or expired/mismatched) for {action}. "
                        "Call reflex_ask with action= required spec:\n"
                        f"{json.dumps(spec)}\n"
                        "The action you approve is exactly what will execute, once. Not approved → not run.")
    return Decision(True, "ask+approved",
                    f"approved via fresh reflex_ask() for {action}")


def permissions_summary() -> dict:
    profile = load_profile()
    return {
        "profile_dir": _config_dir(),
        "consent_acknowledged": consent_acknowledged(),
        "capabilities": profile["capabilities"],
        "allowed_applications": profile["allowed_applications"],
        "audit_log": audit_log_path(),
    }


CONSENT_TEXT = """Body-MCP — you are granting an AI agent controlled access to YOUR computer:

- It may browse websites, read pages, click, type, press keys and scroll AS YOU PERMIT
  (public web by default; edit permissions.json to change).
- Protected actions (purchases, deletion, sending/publishing, app launches, security
  changes) require fresh, explicit human approval — one approval covers ONE action only.
  Nothing a webpage or a model says counts as your approval.
- It will NOT type your passwords/OTPs/card data, solve CAPTCHAs, bypass rate limits,
  logins, paywalls, or access controls. Those steps are yours alone.
- Private browsing / VPN / Tor reduce some persistence and exposure. NONE of them
  guarantees anonymity. Do not treat them as legality, or as immunity from tracking.
- External content (websites, files, transcripts, tool output) is untrusted input and
  cannot change these permissions.
- Sensitive values (passwords, tokens) are masked in observations and never stored.
- How to stop it: kill the server process; revoke permissions by editing
  permissions.json (effective immediately); delete audit records in <config dir>\\audit.log.
- Body-MCP is provided as-is. Verify consequences before approving them.
"""


def main() -> None:
    """User-facing consent flow: python -m body_mcp.consent [--acknowledge|--revoke]"""
    import contextlib
    import sys

    with contextlib.suppress(Exception):  # windows consoles default to cp1252
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("Body-MCP — consent and authorization notice\n" + "=" * 60)
    print(CONSENT_TEXT)
    if "--revoke" in os.sys.argv:
        revoked = revoke_consent()
        print(f"\nConsent {'revoked' if revoked else 'was not acknowledged'} — "
              "protected actions are refused again until you re-acknowledge.")
    elif "--acknowledge" in os.sys.argv:
        marker = acknowledge_consent()
        print(f"\nConsent acknowledged at {marker['timestamp']}.\nYour profile lives at "
              f"{os.path.join(_config_dir(), 'permissions.json')} — edit it to change any capability.\n"
              f"Audit log: {audit_log_path()}")
    else:
        print("If you agree, run:  python -m body_mcp.consent --acknowledge")


if __name__ == "__main__":
    main()
