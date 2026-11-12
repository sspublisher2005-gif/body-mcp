"""Model & harness capability registry + a dry-run recommender.

This is a CATALOGUE, not a runtime: Body-MCP never downloads a model, never
launches a second brain, and never talks to a provider. It records what is
actually installed here, what each option can do, and what it would cost, so the
connected agent (or the user) can choose with facts instead of marketing.

`recommend()` is a dry run: it ranks installed, suitable options and explains the
trade-offs. It never installs anything.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

from . import sysprofile

# kind: harness (an agent CLI) | stt | tts | llm
RECORDS = [
    {
        "name": "opencode",
        "kind": "harness",
        "provides": ["agent", "tools", "mcp_client"],
        "capabilities": {"tools": True, "vision": "model-dependent", "audio_in": "model-dependent",
                         "structured_output": True, "offline": False},
        "runtime": "node CLI",
        "license": "open source (check the installed version)",
        "privacy": "talks to the provider you configure",
        "cost": "depends on the configured provider",
        "notes": "the reference client for Body-MCP; MCP stdio is verified",
        "tested_version": "2.2.6 (this machine)",
    },
    {
        "name": "claude",
        "kind": "harness",
        "provides": ["agent", "tools", "mcp_client"],
        "capabilities": {"tools": True, "vision": "model-dependent", "audio_in": "model-dependent",
                         "structured_output": True, "offline": False},
        "runtime": "node CLI",
        "license": "proprietary client",
        "privacy": "remote provider",
        "cost": "subscription",
        "notes": "MCP stdio is supported via `claude mcp add`",
        "tested_version": "2.1.319 (this machine)",
    },
    {
        "name": "codex",
        "kind": "harness",
        "provides": ["agent", "tools", "mcp_client"],
        "capabilities": {"tools": True, "vision": "model-dependent", "audio_in": False,
                         "structured_output": True, "offline": False},
        "runtime": "node CLI",
        "license": "open source client",
        "privacy": "remote provider",
        "cost": "depends on the configured provider",
        "notes": "MCP stdio is supported via `codex mcp add`",
        "tested_version": "0.167.0 (this machine)",
    },
    {
        "name": "faster-whisper",
        "kind": "stt",
        "provides": ["transcription"],
        "capabilities": {"tools": False, "vision": False, "audio_in": True,
                         "structured_output": True, "offline": True},
        "runtime": "local CPU (int8), optional CUDA",
        "license": "MIT (model weights have their own terms)",
        "privacy": "fully local - audio never leaves the machine",
        "cost": "free, but RAM and CPU per model size",
        "notes": "first use downloads the model into the HF cache; use a small model on low-memory machines",
    },
    {
        "name": "windows-sapi",
        "kind": "tts",
        "provides": ["speech_output"],
        "capabilities": {"tools": False, "vision": False, "audio_in": False,
                         "structured_output": False, "offline": True},
        "runtime": "built into Windows (System.Speech)",
        "license": "OS-provided",
        "privacy": "fully local",
        "cost": "free",
        "notes": "quality is basic but it needs no download and no extra dependency",
    },
    {
        "name": "ollama",
        "kind": "llm",
        "provides": ["local_llm"],
        "capabilities": {"tools": True, "vision": "model-dependent", "audio_in": False,
                         "structured_output": True, "offline": True},
        "runtime": "local server, models downloaded separately",
        "license": "MIT (models have their own licences)",
        "privacy": "local if the model is local",
        "cost": "free but RAM hungry",
        "notes": "only usable when the CLI/server is actually installed and a model is pulled",
    },
]


_version_cache: dict[str, tuple[float, str | None]] = {}
VERSION_TTL = 300.0


def _installed(name: str) -> bool:
    if name in ("faster-whisper", "windows-sapi", "ollama"):
        try:
            if name == "faster-whisper":
                __import__("faster_whisper")
                return True
            if name == "ollama":
                return bool(shutil.which("ollama"))
            return os.name == "nt"  # SAPI ships with Windows
        except Exception:
            return False
    return bool(shutil.which(name))


def _version(name: str) -> str | None:
    """Detect the installed CLI version (cached; a slow CLI must not stall a status call)."""
    if name in ("faster-whisper", "windows-sapi"):
        return None
    now = time.time()
    cached = _version_cache.get(name)
    if cached and now - cached[0] < VERSION_TTL:
        return cached[1]
    exe = shutil.which(name)
    version: str | None = None
    if exe:
        try:
            out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
            text = (out.stdout or out.stderr or "").strip().splitlines()
            version = text[0][:80] if text else None
        except Exception:
            version = None
    _version_cache[name] = (now, version)
    return version


def listing() -> list[dict]:
    """The catalogue with live availability for this machine."""
    profile = sysprofile.summary()
    items = []
    for record in RECORDS:
        entry = dict(record)
        entry["installed"] = _installed(record["name"])
        entry["version_detected"] = _version(record["name"])
        if record["name"] == "faster-whisper":
            entry["local_models"] = profile.get("whisper_models_local", [])
        if record["kind"] == "harness":
            entry["mcp_client"] = True
        items.append(entry)
    return items


def recommend(requirements: dict | None = None) -> dict:
    """Rank installed options for a task. Dry run - installs nothing."""
    requirements = requirements or {}
    needs = requirements.get("needs") or []
    offline_only = bool(requirements.get("offline_only"))
    max_ram_mb = requirements.get("max_ram_mb")
    want = set(needs)

    ranked = []
    for entry in listing():
        if not entry["installed"]:
            continue
        caps = entry["capabilities"]
        score = 0
        reasons = []
        for need in want:
            if need == "tools" and caps.get("tools"):
                score += 3
                reasons.append("supports tool calls")
            elif need == "vision" and caps.get("vision"):
                score += 2
                reasons.append("vision support (model dependent)")
            elif need == "audio" and caps.get("audio_in"):
                score += 2
                reasons.append("audio input")
            elif need == "structured_output" and caps.get("structured_output"):
                score += 1
                reasons.append("structured output")
        if offline_only:
            if caps.get("offline"):
                score += 4
                reasons.append("runs fully offline")
            else:
                score -= 3
                reasons.append("needs a remote provider")
        if entry["kind"] == "harness":
            score += 1
            reasons.append("can drive Body-MCP tools over MCP")
        if max_ram_mb:
            heavy = entry["name"] in ("ollama", "faster-whisper")
            if heavy:
                score -= 2
                reasons.append(f"needs roughly >{max_ram_mb} MB RAM")
        ranked.append({"name": entry["name"], "kind": entry["kind"], "score": score,
                       "reasons": reasons, "license": entry["license"],
                       "privacy": entry["privacy"], "cost": entry["cost"],
                       "notes": entry["notes"]})
    ranked.sort(key=lambda r: (-r["score"], r["name"]))
    return {
        "dry_run": True,
        "installed": True,
        "requirements": requirements,
        "recommended": ranked[0]["name"] if ranked else None,
        "ranked": ranked,
        "note": "dry run - nothing was downloaded, installed or launched",
    }
