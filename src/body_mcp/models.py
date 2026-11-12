"""The local-model catalogue: what every user can pick, measured and honest.

Two runtimes, one catalogue:

  - **Ollama** - one command, no compiler: ``ollama pull qwen3:0.6b``
  - **llama.cpp** - the same models as GGUF files you download yourself

The sizes and SHA-256 below were read from the Hugging Face API (exact file bytes
plus the LFS SHA-256) and from the Ollama registry manifests (exact blob bytes
plus the content digest), so a download can be verified before it is used.

The recommendation is per machine: it uses the *measured* free RAM, not a guess,
and it never suggests a model that would not fit.

Roles
-----
`worker`    a private local helper: extraction, classification, dedup keys, PII
            scrubbing, short summaries. Small, fast, offline.
`reasoner`  the agent's own thinking model, run locally instead of remotely.

Every model here works on Windows, macOS and Linux - through Ollama or through
the same GGUF under llama.cpp.
"""
from __future__ import annotations

import hashlib
import os

HF = "https://huggingface.co"

# exact sizes and SHA-256 as published by the Hugging Face API (blobs=true)
# and by the Ollama registry manifests
MODELS = [
    {
        "id": "qwen3-0.6b-q4",
        "name": "Qwen3-0.6B (Q4_0)",
        "runtime": "llama.cpp",
        "repo": "ggml-org/Qwen3-0.6B-GGUF",
        "file": "Qwen3-0.6B-Q4_0.gguf",
        "bytes": 428_970_080,
        "sha256": "da2572f16c06133561ce56accaa822216f2391ef4d37fba427801cd6736417d4",
        "licence": "Apache-2.0",
        "params": "0.6B",
        "ctx": 40960,
        "ram_mb": 900,
        "tools": True,
        "vision": False,
        "multilingual": True,
        "uncensored": False,
        "roles": ["worker"],
        "tier": 1,
        "note": "the default worker: fits a 500 MB budget, tool-calling, multilingual",
    },
    {
        "id": "gemma3-270m-q8",
        "name": "Gemma-3-270m-it (Q8_0)",
        "runtime": "llama.cpp",
        "repo": "ggml-org/gemma-3-270m-it-GGUF",
        "file": "gemma-3-270m-it-Q8_0.gguf",
        "bytes": 291_545_600,
        "sha256": "0ef57d2c838458a1952664260dcba38e5bdda37494f3af732f06e4add24068e3",
        "licence": "Gemma terms (free, with a use policy)",
        "params": "0.27B",
        "ctx": 32768,
        "ram_mb": 700,
        "tools": False,
        "vision": True,
        "multilingual": True,
        "uncensored": False,
        "roles": ["worker"],
        "tier": 1,
        "note": "the smallest: good for classification, weaker at structured output",
    },
    {
        "id": "qwen3-1.7b-q4",
        "name": "Qwen3-1.7B (Q4_K_M)",
        "runtime": "llama.cpp",
        "repo": "ggml-org/Qwen3-1.7B-GGUF",
        "file": "Qwen3-1.7B-Q4_K_M.gguf",
        "bytes": 1_282_439_264,
        "sha256": "d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5",
        "licence": "Apache-2.0",
        "params": "1.7B",
        "ctx": 40960,
        "ram_mb": 2000,
        "tools": True,
        "vision": False,
        "multilingual": True,
        "uncensored": False,
        "roles": ["worker"],
        "tier": 2,
        "note": "clearly stronger than the 0.6B; needs ~2 GB free RAM",
    },
    {
        "id": "qwen3-vl-2b-q8",
        "name": "Qwen3-VL-2B-Instruct (Q8_0 + projector)",
        "runtime": "llama.cpp",
        "repo": "ggml-org/Qwen3-VL-2B-Instruct-GGUF",
        "file": "Qwen3-VL-2B-Instruct-Q8_0.gguf",
        "bytes": 1_834_427_296,
        "sha256": "b7802e29f71a9e5b5e3f83f613df898a2204342dcea71a231ea501d481813c39",
        "extra_files": [{
            "file": "mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf",
            "bytes": 445_053_056,
            "sha256": "69066c8f279ec85ff48ab4059f6ebba0d2932ca57667f2bbdac7d9805bca9e7b",
            "note": "the vision projector - required to see images or video frames",
        }],
        "licence": "Apache-2.0",
        "params": "2B",
        "ctx": 262144,
        "ram_mb": 3200,
        "tools": True,
        "vision": True,
        "multilingual": True,
        "uncensored": False,
        "roles": ["worker", "reasoner"],
        "tier": 2,
        "note": "the one-model pick: eyes + tool calls (so it can drive websearch) + thinking",
    },
    {
        "id": "dolphin2.9-8b-q2k",
        "name": "Dolphin 2.9 Llama-3-8B (Q2_K)",
        "runtime": "llama.cpp",
        "repo": "bartowski/dolphin-2.9-llama3-8b-GGUF",
        "file": "dolphin-2.9-llama3-8b-Q2_K.gguf",
        "bytes": 3_179_141_824,
        "sha256": "72a1461f5be05f668d330b94b6e011bafe69a25605f88aba7f01056c6c37639a",
        "licence": "Llama-3 Community Licence (the base weights; the repo says 'other')",
        "params": "8B",
        "ctx": 8192,
        "ram_mb": 4400,
        "tools": False,
        "vision": False,
        "multilingual": False,
        "uncensored": True,
        "roles": ["reasoner"],
        "tier": 3,
        "note": "the smallest genuinely uncensored option; needs ~4.5 GB free RAM",
    },
    {
        "id": "dolphin2.9-8b-q3km",
        "name": "Dolphin 2.9 Llama-3-8B (Q3_K_M)",
        "runtime": "llama.cpp",
        "repo": "bartowski/dolphin-2.9-llama3-8b-GGUF",
        "file": "dolphin-2.9-llama3-8b-Q3_K_M.gguf",
        "bytes": 4_018_929_152,
        "sha256": "0f9e5d9e1fadbe6e8dcac550aae56e9488910e374f735cd70f6522254e4fb61b",
        "licence": "Llama-3 Community Licence (the base weights; the repo says 'other')",
        "params": "8B",
        "ctx": 8192,
        "ram_mb": 5400,
        "tools": False,
        "vision": False,
        "multilingual": False,
        "uncensored": True,
        "roles": ["reasoner"],
        "tier": 3,
        "note": "better quality than Q2_K, still uncensored; ~5.5 GB free RAM",
    },
    {
        "id": "ollama-qwen3-0.6b",
        "name": "qwen3:0.6b (Ollama)",
        "runtime": "ollama",
        "tag": "qwen3:0.6b",
        "bytes": 522_640_096,
        "sha256": "7f4030143c1c477224c5434f8272c662a8b042079a0a584f0a27a1684fe2e1fa",
        "licence": "Apache-2.0",
        "params": "0.6B",
        "ctx": 40960,
        "ram_mb": 950,
        "tools": True,
        "vision": False,
        "multilingual": True,
        "uncensored": False,
        "roles": ["worker"],
        "tier": 1,
        "note": "the easiest worker: one command, no compiler, no build step",
    },
    {
        "id": "ollama-qwen3-0.6b-q8",
        "name": "qwen3:0.6b-q8_0 (Ollama)",
        "runtime": "ollama",
        "tag": "qwen3:0.6b-q8_0",
        "bytes": 832_278_240,
        "sha256": "31db9797248620627b127c47c75caa76ec2ce9b7de9dc0f2faca02ba59615818",
        "licence": "Apache-2.0",
        "params": "0.6B",
        "ctx": 40960,
        "ram_mb": 1250,
        "tools": True,
        "vision": False,
        "multilingual": True,
        "uncensored": False,
        "roles": ["worker"],
        "tier": 1,
        "note": "the same worker in Q8 - better quality, still under 1 GB",
    },
    {
        "id": "ollama-gemma3-270m",
        "name": "gemma3:270m (Ollama)",
        "runtime": "ollama",
        "tag": "gemma3:270m",
        "bytes": 291_545_472,
        "sha256": "735af2139dc652bf01112746474883d79a52fa1c19038265d363e3d42556f7a2",
        "licence": "Gemma terms (free, with a use policy)",
        "params": "0.27B",
        "ctx": 32768,
        "ram_mb": 700,
        "tools": False,
        "vision": True,
        "multilingual": True,
        "uncensored": False,
        "roles": ["worker"],
        "tier": 1,
        "note": "the smallest eyes: 278 MB, reads an image, no tool calls",
    },
    {
        "id": "ollama-qwen3-vl-2b",
        "name": "qwen3-vl:2b (Ollama)",
        "runtime": "ollama",
        "tag": "qwen3-vl:2b",
        "bytes": 1_889_496_384,
        "sha256": "ebabfa59b71a5b96e0281ec2994977e785284e0939807a99fc340dec3c6f10de",
        "licence": "Apache-2.0",
        "params": "2B",
        "ctx": 262144,
        "ram_mb": 3000,
        "tools": True,
        "vision": True,
        "multilingual": True,
        "uncensored": False,
        "roles": ["worker", "reasoner"],
        "tier": 2,
        "note": "eyes + tools + thinking in one 1.8 GB pull (the projector is bundled)",
    },
    {
        "id": "ollama-dolphin3-8b",
        "name": "dolphin3:8b (Ollama)",
        "runtime": "ollama",
        "tag": "dolphin3:8b",
        "bytes": 4_920_749_184,
        "sha256": "1eee6953530837b2b17d61a4e6f71a5aa31c9714cfcf3cb141aa5c1972b5116b",
        "licence": "Llama-3.1 Community Licence (the base weights)",
        "params": "8B",
        "ctx": 131072,
        "ram_mb": 6200,
        "tools": True,
        "vision": False,
        "multilingual": False,
        "uncensored": True,
        "roles": ["reasoner"],
        "tier": 3,
        "note": "Dolphin 3.0 (Llama 3.1 8B): steerable, no imposed alignment, 128K context",
    },
]


def files(model: dict) -> list[dict]:
    """Every file the model needs (the projector counts)."""
    if model.get("runtime") == "ollama":
        return [{"file": model["tag"], "bytes": model["bytes"], "sha256": model["sha256"],
                 "note": "the Ollama blob - content addressed, `ollama pull` verifies it"}]
    out = [{"file": model["file"], "bytes": model["bytes"], "sha256": model["sha256"]}]
    out.extend(model.get("extra_files", []))
    return out


def total_bytes(model: dict) -> int:
    return sum(entry["bytes"] for entry in files(model))


def download_url(model: dict) -> str | None:
    """The direct download URL (llama.cpp rows only; Ollama rows have a command)."""
    if model.get("runtime") == "ollama":
        return None
    return f"{HF}/{model['repo']}/resolve/main/{model['file']}"


def install_command(model: dict) -> str:
    """How the user gets it - a command or a URL. Body-MCP never runs it."""
    if model.get("runtime") == "ollama":
        return f"ollama pull {model['tag']}"
    return download_url(model)


def catalogue() -> list[dict]:
    """The catalogue with the download URL/command and the human sizes."""
    out = []
    for model in MODELS:
        entry = dict(model)
        total = total_bytes(model)
        entry["download_url"] = download_url(model)
        entry["install"] = install_command(model)
        entry["total_bytes"] = total
        entry["size_mb"] = round(total / 1024 / 1024)
        entry["size_gb"] = round(total / 1024 / 1024 / 1024, 2)
        entry["files"] = files(model)
        out.append(entry)
    return out


def find(model_id: str) -> dict | None:
    return next((model for model in MODELS if model["id"] == model_id), None)


def installed_models() -> list[str]:
    """The models this machine already has (Ollama tags + a configured GGUF)."""
    from . import local_worker

    names = [model["name"] for model in local_worker.ollama_models()]
    gguf = os.environ.get("BODY_MCP_LOCAL_MODEL") or ""
    if gguf and os.path.isfile(gguf):
        names.append(gguf)
    return names


def recommend(free_ram_mb: int | None = None, role: str = "worker",
               uncensored: bool = False, multilingual: bool = False) -> list[dict]:
    """Rank the catalogue for this machine (measured RAM) and this preference."""
    have = [name.lower() for name in installed_models()]
    ranked = []
    for model in MODELS:
        if role not in model["roles"]:
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
        if model["vision"]:
            reasons.append("sees images and video frames")
            score += 3
        if model["multilingual"]:
            reasons.append("multilingual (incl. Telugu)")
            score += 2
        if model["uncensored"]:
            reasons.append("uncensored weights")
            score += 2
        if model["runtime"] == "ollama":
            reasons.append("one command to install, no compiler")
            score += 2
        score += max(0, 6 - model["tier"])
        tag = model.get("tag", "")
        present = any(tag and tag.lower() == name for name in have)
        if present:
            reasons.append("already installed on this machine")
            score += 20
        ranked.append({"id": model["id"], "name": model["name"], "score": score,
                       "fits": fits, "installed": present,
                       "runtime": model["runtime"],
                       "size_mb": round(total_bytes(model) / 1024 / 1024),
                       "ram_mb": model["ram_mb"], "licence": model["licence"],
                       "tools": model["tools"], "vision": model["vision"],
                       "uncensored": model["uncensored"], "roles": model["roles"],
                       "reasons": reasons, "note": model["note"],
                       "install": install_command(model)})
    # models that fit this machine come first; a model that does not fit is never
    # recommended as "the one to use" while something else fits
    ranked.sort(key=lambda item: (not item["fits"], not item["installed"],
                                  -item["score"], item["size_mb"]))
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
    known = next((model for model in MODELS
                  if model.get("file") and path.endswith(model["file"])), None)
    info = {"configured": True, "path": path,
            "exists": os.path.isfile(path),
            "bytes": os.path.getsize(path) if os.path.isfile(path) else None,
            "catalogue_id": known["id"] if known else None}
    if known and info["exists"]:
        info["verified"] = verify(path, known["sha256"], known["bytes"]).get("verified", False)
    return info
