"""Configuration for Body-MCP.

Reads optional `.env` (stdlib parser, no dependencies) and sensible defaults.
All values are local-only; no API keys are used or required.
"""
import os
import shutil

DEFAULTS = {
    "BODY_MCP_WHISPER_MODEL": "small.en",
    "BODY_MCP_BROWSER_MODE": "headed",
    "BODY_MCP_POLITE_DELAY_MS": "1500",
    "BODY_MCP_MAX_CONCURRENCY": "2",
    "BODY_MCP_HARD_MAX_CONCURRENCY": "4",
    "BODY_MCP_BATCH_DEADLINE_MS": "120000",
    "BODY_MCP_PARALLEL_DEADLINE_MS": "180000",
    "BODY_MCP_TASK_DEADLINE_MS": "60000",
    "BODY_MCP_BACKOFF_BASE_S": "1",
    "BODY_MCP_BACKOFF_MAX_S": "60",
}


def _int_env(name: str, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(get(name) or DEFAULTS[name])))
    except (ValueError, KeyError):
        return int(DEFAULTS.get(name, minimum))


def max_concurrency() -> int:
    """Configured parallel task limit, clamped to [1, hard max]."""
    return _int_env("BODY_MCP_MAX_CONCURRENCY", 1,
                    _int_env("BODY_MCP_HARD_MAX_CONCURRENCY", 1, 8))


def hard_max_concurrency() -> int:
    return _int_env("BODY_MCP_HARD_MAX_CONCURRENCY", 1, 8)


def batch_deadline_ms() -> int:
    return _int_env("BODY_MCP_BATCH_DEADLINE_MS", 5000, 300000)


def parallel_deadline_ms() -> int:
    return _int_env("BODY_MCP_PARALLEL_DEADLINE_MS", 5000, 600000)


def task_deadline_ms() -> int:
    return _int_env("BODY_MCP_TASK_DEADLINE_MS", 1000, 300000)


def backoff_base_s() -> float:
    try:
        return max(0.1, min(30.0, float(get("BODY_MCP_BACKOFF_BASE_S") or DEFAULTS["BODY_MCP_BACKOFF_BASE_S"])))
    except ValueError:
        return 1.0


def backoff_max_s() -> float:
    try:
        return max(1.0, min(3600.0, float(get("BODY_MCP_BACKOFF_MAX_S") or DEFAULTS["BODY_MCP_BACKOFF_MAX_S"])))
    except ValueError:
        return 60.0


def backoff_delay(attempt: int) -> float:
    """Bounded exponential backoff with full jitter. attempt is 0-based."""
    import random

    base = backoff_base_s()
    cap = backoff_max_s()
    ceiling = min(cap, base * (2 ** max(0, attempt)))
    return random.uniform(0, ceiling)


def load_env() -> None:
    """Populate os.environ from a .env file next to the current working directory."""
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def get(name: str) -> str:
    load_env()
    return os.environ.get(name, DEFAULTS.get(name, ""))


def whisper_model() -> str:
    return get("BODY_MCP_WHISPER_MODEL") or DEFAULTS["BODY_MCP_WHISPER_MODEL"]


def browser_headless() -> bool:
    return get("BODY_MCP_BROWSER_MODE").strip().lower() == "headless"


def polite_delay_ms() -> int:
    try:
        return max(0, int(get("BODY_MCP_POLITE_DELAY_MS") or DEFAULTS["BODY_MCP_POLITE_DELAY_MS"]))
    except ValueError:
        return int(DEFAULTS["BODY_MCP_POLITE_DELAY_MS"])


def tesseract_cmd() -> str | None:
    """Locate the tesseract binary, or None if it is not installed."""
    load_env()
    explicit = os.environ.get("TESSERACT_CMD")
    if explicit and os.path.isfile(explicit):
        return explicit
    found = shutil.which("tesseract")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None
