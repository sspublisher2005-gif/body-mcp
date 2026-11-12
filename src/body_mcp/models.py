"""The local-model catalogue: what every user can pick, measured and honest.

Body-MCP does not download a model - the user does, and the catalogue tells them
what to get and how to verify it. Sizes, checksums and licences below were read
from the Hugging Face API (exact file bytes + SHA-256), so a download can be
verified before it is used.

The recommendation is per machine: it uses the *measured* free RAM, not a guess,
and it never suggests a model that would not fit.

Roles
-----
`worker`  a private local helper: extraction, classification, dedup keys, PII
           scrubbing, short summaries. Small, fast, offline.
`reasoner` the agent's own thinking model, run locally instead of remotely.

Every model here works on Windows, macOS and Linux through llama.cpp - the same
GGUF, the same runtime.
"""
from __future__ import annotations

import hashlib
import os

HF = "https://huggingface.co"

# exact sizes and SHA-256 as published by the Hugging Face API (blobs=true)
MODELS = [
    {
        "id": "qwen3-0.6b-q4",
        "name": "Qwen3-0.6B (Q4_0)",
        "repo": "ggml-org/Qwen3-0.6B-GGUF",
        "file": "Qwen3-0.6B-Q4_0.gguf",
        "bytes": 428_970_080,
        "sha256": "da2572f16c06133561ce56accaa822216f2391ef4d37fba427801cd6736417d4",
        "licence": "Apache-2.0",
        "params": "0.6B",
        "ctx": 40960,
        "ram_mb": 900,
        "tools": True,
        "multilingual": True,
        "uncensored": False,
        "role": "worker",
        "tier": 1,
        "note": "the default worker: fits a 500 MB budget, tool-calling, multilingual",
    },
    {
        "id": "gemma3-270m-q8",
        "name": "Gemma-3-270m-it (Q8_0)",
        "repo": "ggml-org/gemma-3-270m-it-GGUF",
        "file": "gemma-3-270m-it-Q8_0.gguf",
        "bytes": 291_545_600,
        "sha256": "0ef57d2c838458a1952664260dcba38e5bdda37494f3af732f06e4add24068e3",
        "licence": "Gemma terms (free, with a use policy)",
        "params": "0.27B",
        "ctx": 32768,
        "ram_mb": 700,
        "tools": False,
        "multilingual": True,
        "uncensored": False,
        "role": "worker",
        "tier": 1,
        "note": "the smallest: good for classification, weaker at structured output",
    },
    {
        "id": "qwen3-1.7b-q4",
        "name": "Qwen3-1.7B (Q4_K_M)",
        "repo": "ggml-org/Qwen3-1.7B-GGUF",
        "file": "Qwen3-1.7B-Q4_K_M.gguf",
        "bytes": 1_282_439_264,
        "sha256": "d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5",
        "licence": "Apache-2.0",
        "params": "1.7B",
        "ctx": 40960,
        "ram_mb": 2000,
        "tools": True,
        "multilingual": True,
        "uncensored": False,
        "role": "worker",
        "tier": 2,
        "note": "clearly stronger than the 0.6B; needs ~2 GB free RAM",
    },
    {
        "id": "dolphin2.9-8b-q2k",
        "name": "Dolphin 2.9 Llama-3-8B (Q2_K)",
        "repo": "bartowski/dolphin-2.9-llama3-8b-GGUF",
        "file": "dolphin-2.9-llama3-8b-Q2_K.gguf",
        "bytes": 3_179_141_824,
        "sha256": "72a1461f5be05f668d330b94b6e011bafe69a25605f88aba7f01056c6c37639a",
        "licence": "Apache-2.0 weights (Llama-3 base)",
        "params": "8B",
        "ctx": 8192,
        "ram_mb": 4400,
        "tools": False,
        "multilingual": False,
        "uncensored": True,
        "role": "reasoner",
        "tier": 3,
        "note": "the smallest genuinely uncensored option; needs ~4.5 GB free RAM",
    },
    {
        "id": "dolphin2.9-8b-q3km",
        "name": "Dolphin 2.9 Llama-3-8B (Q3_K_M)",
        "repo": "bartowski/dolphin-2.9-llama3-8b-GGUF",
        "file": "dolphin-2.9-llama3-8b-Q3_K_M.gguf",
        "bytes": 4_018_929_152,
        "sha256": "0f9e5d9e1fadbe6e8dcac550aae56e9488910e374f735cd70f6522254e4fb61b",
        "licence": "Apache-2.0 weights (Llama-3 base)",
        "params": "8B",
        "ctx": 8192,
        "ram_mb": 5400,
        "tools": False,
        "multilingual": False,
        "uncensored": True,
        "role": "reasoner",
        "tier": 3,
        "note": "better quality than Q2_K, still uncensored; ~5.5 GB free RAM",
    },
]


def download_url(model: dict) -> str:
    return f"{HF}/{model['repo']}/resolve/main/{model['file']}"


def catalogue() -> list[dict]:
    """The catalogue with the download URL and the human sizes."""
    out = []
    for model in MODELS:
        entry = dict(model)
        entry["download_url"] = download_url(model)
        entry["size_mb"] = round(model["bytes"] / 1024 / 1024)
        entry["size_gb"] = round(model["bytes"] / 1024 / 1024 / 1024, 2)
        out.append(entry)
    return out


def find(model_id: str) -> dict | None:
    return next((model for model in MODELS if model["id"] == model_id), None)


def recommend(free_ram_mb: int | None = None, role: str = "worker",
               uncensored: bool = False, multilingual: bool = False) -> list[dict]:
    """Rank the catalogue for this machine (measured RAM) and this preference."""
    ranked = []
    for model in MODELS:
        if model["role"] != role:
            continue
        if uncensored and not model["uncensored"]:
            continue
        if multilingual and not model["multilingual"]:
            continue
        reasons = []
        score = 0
        fits = True
        if free_ram_mb:
            headroom = free_ram_mb - model["ram_mb"]
            if headroom < 0:
                fits = False
                reasons.append(f"needs ~{model['ram_mb']} MB RAM - {abs(headroom)} MB short "
                               f"of the {free_ram_mb} MB free")
                score -= 100
            else:
                reasons.append(f"fits: ~{model['ram_mb']} MB RAM needed, {headroom} MB spare")
                score += 10
        if model["tools"]:
            reasons.append("can return structured JSON (tool calling)")
            score += 4
        if model["multilingual"]:
            reasons.append("multilingual (incl. Telugu)")
            score += 2
        if model["uncensored"]:
            reasons.append("uncensored weights")
            score += 2
        score += max(0, 6 - model["tier"])
        ranked.append({"id": model["id"], "name": model["name"], "score": score,
                       "fits": fits,
                       "size_mb": round(model["bytes"] / 1024 / 1024),
                       "ram_mb": model["ram_mb"], "licence": model["licence"],
                       "reasons": reasons, "note": model["note"],
                       "download_url": download_url(model)})
    # models that fit this machine come first; a model that does not fit is never
    # recommended as "the one to use" while something else fits
    ranked.sort(key=lambda item: (not item["fits"], -item["score"], item["size_mb"]))
    return ranked


def verify(path: str, sha256: str | None = None, expected_bytes: int | None = None) -> dict:
    """Check a downloaded model file against the catalogue (size first, then SHA-256)."""
    if not path or not os.path.isfile(path):
        return {"ok": False, "reason": f"no such file: {path}"}
    size = os.path.getsize(path)
    result = {"path": path, "bytes": size, "size_mb": round(size / 1024 / 1024)}
    if expected_bytes and size != expected_bytes:
        result.update(ok=False, reason=f"size mismatch: {size} bytes, expected {expected_bytes}")
        return result
    if sha256:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        result["sha256"] = digest.hexdigest()
        if digest.hexdigest() != sha256:
            result.update(ok=False, reason="SHA-256 mismatch - the file is not the "
                                         "catalogue build")
            return result
    result.update(ok=True, verified=True)
    return result


def configured_model() -> dict:
    """The local model the user configured (BODY_MCP_LOCAL_MODEL), if any."""
    path = os.environ.get("BODY_MCP_LOCAL_MODEL") or ""
    if not path:
        return {"configured": False, "path": ""}
    known = next((model for model in MODELS if path.endswith(model["file"])), None)
    info = {"configured": True, "path": path,
            "exists": os.path.isfile(path),
            "bytes": os.path.getsize(path) if os.path.isfile(path) else None,
            "catalogue_id": known["id"] if known else None}
    if known and info["exists"]:
        info["verified"] = verify(path, known["sha256"], known["bytes"]).get("verified", False)
    return info
