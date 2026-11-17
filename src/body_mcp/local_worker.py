"""The local worker: keep page content OFF the network.

This is the private mode's missing half. The browser part is done (no login, own
context, nothing persisted). This module is the *content* part: text is processed
by a model that runs on your machine, so only a short, redacted summary ever
leaves.

Two runtimes, both optional and both local:
  - **Ollama** (easiest): ``ollama pull qwen3:0.6b`` -> ``http://127.0.0.1:11434``
  - **llama.cpp** (GGUF on disk): ``BODY_MCP_LOCAL_MODEL`` + ``llama-cpp-python``

Rules:
  - nothing is downloaded automatically; a model must already be present,
  - the call is loopback-only and never leaves the machine,
  - if no local model is available the tool says so - it never silently falls back
    to a remote provider (that fallback would be the opposite of the point).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"
TIMEOUT = 120

TASKS = ("summarise", "extract", "redact", "key", "classify", "describe")

PROMPTS = {
    "summarise": "Summarise the text in at most 5 short bullet points. Facts only.",
    "extract": "Extract the key facts as a JSON object. Facts only, no commentary.",
    "redact": "Return the text with names, emails, phone numbers, addresses, IDs and "
               "any other personal data replaced by [REDACTED]. Keep everything else.",
    "key": "Return a short deduplication key: the topic plus the distinct detail. "
           "One line, no commentary.",
    "classify": "Classify the text into one of: news, docs, forum, product, video, "
                "other. Reply with the label only.",
    "describe": "Describe what is on this screen in at most 5 short bullet points: the "
                "application, what it shows, any visible text, any error or dialog, and "
                "what the user could do next. Facts only - say 'unclear' instead of "
                "guessing.",
}

# Model families that can actually look at an image. A text-only model handed an
# image would invent a caption - so we only pick from these, or refuse.
VISION_HINTS = ("gemma3", "gemma-3", "llava", "bakllava", "moondream", "qwen3-vl",
                "qwen2-vl", "qwen2.5-vl", "minicpm-v", "granite-vision", "llama3.2-vision",
                "llama3.1-vision", "pixtral", "internvl", "phi-3.5-vision", "moondream2")

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1", "[::1]")


def ollama_installed() -> bool:
    if os.environ.get("BODY_MCP_OLLAMA_URL"):
        return True
    import shutil

    if shutil.which("ollama"):
        return True
    default = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama",
                           "ollama.exe")
    return bool(default) and os.path.isfile(default)


def ollama_url() -> str:
    return os.environ.get("BODY_MCP_OLLAMA_URL") or OLLAMA_URL


def is_loopback(url: str) -> bool:
    """Only a loopback address is allowed - the worker must never phone home."""
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return False
    return host.lower() in LOOPBACK_HOSTS


def ollama_models() -> list[dict]:
    """The models Ollama already has (no pull, no download)."""
    if not ollama_installed():
        return []
    if not is_loopback(ollama_url()):
        return []
    try:
        request = urllib.request.Request(ollama_url() + "/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8", "replace"))
    except Exception:
        return []
    out = []
    for model in payload.get("models", []) or []:
        out.append({"name": model.get("name"), "size": model.get("size"),
                    "size_mb": round((model.get("size") or 0) / 1024 / 1024),
                    "family": model.get("details", {}).get("family")})
    return out


def _local_model() -> str | None:
    """Which local model would we use (an explicit choice wins)?"""
    explicit = os.environ.get("BODY_MCP_LOCAL_MODEL") or ""
    if explicit:
        return explicit
    models = ollama_models()
    if not models:
        return None
    preferred = os.environ.get("BODY_MCP_LOCAL_MODEL_NAME") or ""
    for model in models:
        if model["name"] == preferred:
            return model["name"]
    # the smallest installed model is the safe default for a worker
    return sorted(models, key=lambda m: m.get("size") or 0)[0]["name"]


def _vision_model() -> str | None:
    """The installed model that can actually look at an image (never a text one)."""
    explicit = os.environ.get("BODY_MCP_VISION_MODEL") or ""
    if explicit:
        return explicit
    for model in ollama_models():
        name = (model.get("name") or "").lower()
        if any(hint in name for hint in VISION_HINTS):
            return model["name"]
    return None


def _call_ollama(model: str, prompt: str, text: str, image: str | None = None) -> dict:
    payload = {
        "model": model,
        "prompt": f"{prompt}\n\n---\n{text}" if text else prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }
    if image:
        payload["images"] = [image]
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(ollama_url() + "/api/generate", data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        answer = json.loads(response.read().decode("utf-8", "replace"))
    return {"text": answer.get("response", "").strip(),
            "duration_ms": int((answer.get("total_duration") or 0) / 1_000_000),
            "model": model, "runtime": "ollama"}


def _call_ollama_chat(model: str, prompt: str, image: str) -> dict:
    """The multimodal endpoint. /api/generate returns 400 when given images."""
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [image]}],
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }).encode("utf-8")
    request = urllib.request.Request(ollama_url() + "/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        answer = json.loads(response.read().decode("utf-8", "replace"))
    return {"text": (answer.get("message") or {}).get("content", "").strip(),
            "duration_ms": int((answer.get("total_duration") or 0) / 1_000_000),
            "model": model, "runtime": "ollama"}


def _call_llama_cpp(model_path: str, prompt: str, text: str) -> dict:
    import time

    from llama_cpp import Llama  # imported lazily: it is optional

    started = time.monotonic()
    llm = Llama(model_path=model_path, n_ctx=8192, verbose=False)
    result = llm.create_chat_completion(
        messages=[{"role": "user", "content": f"{prompt}\n\n---\n{text}"}],
        temperature=0.1)
    content = result["choices"][0]["message"]["content"]
    return {"text": content.strip(), "duration_ms": int((time.monotonic() - started) * 1000),
            "model": os.path.basename(model_path), "runtime": "llama.cpp"}


def _no_model_reason() -> str:
    """Why there is no local model - the exact next step for the user."""
    if ollama_installed():
        if not is_loopback(ollama_url()):
            return (f"BODY_MCP_OLLAMA_URL points at {ollama_url()} - the worker only "
                    "talks to this machine (127.0.0.1).")
        if not ollama_models():
            return ("Ollama is installed but has no model yet: run "
                    "`ollama pull qwen3:0.6b` (498 MB). Body-MCP never downloads a model "
                    "for you and never sends this text to a remote provider.")
        return "the local runtime did not answer - start it (`ollama serve`) and retry."
    return ("no local model is available - install Ollama (https://ollama.com) and pull "
            "one (`ollama pull qwen3:0.6b`), or set BODY_MCP_LOCAL_MODEL to a GGUF file. "
            "Body-MCP never downloads a model for you and never sends this text to a "
            "remote provider.")


def run(task: str, text: str, image: str | None = None) -> dict:
    """Process text (and optionally an image) locally.

    Returns the result, or the honest reason it could not run. Never falls back
    to a remote provider.
    """
    if task not in TASKS:
        return {"ok": False, "reason": f"unknown task {task!r}; use one of {list(TASKS)}"}
    if task == "describe":
        return _describe(image)
    if not (text or "").strip():
        return {"ok": False, "reason": "no text to process"}
    prompt = PROMPTS[task]
    model = _local_model()
    if not model:
        return {"ok": False, "reason": _no_model_reason(), "local": False}
    try:
        if os.path.isfile(model):
            result = _call_llama_cpp(model, prompt, text)
        else:
            if not is_loopback(ollama_url()):
                return {"ok": False, "local": False,
                        "reason": f"the local runtime URL {ollama_url()} is not on this "
                                  "machine - refusing to send the text off the box"}
            result = _call_ollama(model, prompt, text)
    except urllib.error.URLError as exc:
        return {"ok": False, "reason": f"could not reach the local runtime: {exc}",
                "local": False}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "local": False}
    result.update(ok=True, task=task, local=True)
    return result


def _describe(image: str | None) -> dict:
    """Describe an image with a LOCAL vision model - the eyes for a text-only brain.

    The image is base64 PNG/JPEG. It is never sent to a remote provider.
    """
    if not image:
        return {"ok": False, "local": False,
                "reason": "describe needs an image (the base64 data from "
                          "eyes_see_desktop(as_image=True) or "
                          "desktop_watch_read(as_image=True))"}
    if os.path.isfile(os.environ.get("BODY_MCP_LOCAL_MODEL") or ""):
        return {"ok": False, "local": False,
                "reason": "the llama.cpp path does not take images yet - install Ollama and "
                          "pull a vision model (ollama pull gemma3:270m)"}
    model = _vision_model()
    if not model:
        installed = [m.get("name") for m in ollama_models()]
        return {"ok": False, "local": False,
                "reason": ("no local VISION model is installed - a text-only model would "
                           "invent a caption, so this refuses. Install one: "
                           "`ollama pull gemma3:270m` (278 MB). Installed models: "
                           + (", ".join(installed) if installed else "none"))}
    if not is_loopback(ollama_url()):
        return {"ok": False, "local": False,
                "reason": f"the local runtime URL {ollama_url()} is not on this machine - "
                          "refusing to send the image off the box"}
    try:
        result = _call_ollama_chat(model, PROMPTS["describe"], image)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        return {"ok": False, "local": False,
                "reason": (f"the local runtime returned HTTP {exc.code}: "
                           f"{detail or str(exc)}")}
    except urllib.error.URLError as exc:
        return {"ok": False, "reason": f"could not reach the local runtime: {exc}",
                "local": False}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "local": False}
    result.update(ok=True, task="describe", local=True)
    return result


def status() -> dict:
    """Is a local worker available, and which model would it use?"""
    installed = ollama_installed()
    models = ollama_models() if installed else []
    gguf = os.environ.get("BODY_MCP_LOCAL_MODEL") or ""
    return {
        "available": bool(models) or bool(gguf and os.path.isfile(gguf)),
        "ollama_installed": installed,
        "ollama_reachable": bool(models),
        "ollama_url": ollama_url() if installed else None,
        "ollama_models": models,
        "gguf": gguf if gguf and os.path.isfile(gguf) else None,
        "selected": _local_model(),
        "note": "everything here runs on this machine; nothing is downloaded and nothing "
                "is sent to a remote provider",
    }
