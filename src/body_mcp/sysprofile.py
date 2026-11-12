"""Read-only system capability inventory.

Used to choose tools and models sensibly on a low-memory machine. It collects
only what a recommendation needs, never crawls private files, and never uploads
anything. The result is cached locally (non-sensitive) and can be cleared.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time

from . import permissions

CACHE_TTL_SECONDS = 3600
OPTIONAL_MODULES = {
    "playwright": "browser control",
    "mss": "desktop capture",
    "pytesseract": "desktop OCR",
    "PIL": "image handling",
    "sounddevice": "microphone capture",
    "faster_whisper": "local speech-to-text",
    "numpy": "array maths for audio",
}
AGENT_CLIS = ("opencode", "claude", "codex", "gemini", "ollama")


def cache_path() -> str:
    return os.path.join(permissions._config_dir(), "profile.json")


def _ram_mb() -> tuple[int | None, str]:
    """Available RAM in MB. Returns (value, source)."""
    if os.name == "nt":
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullAvailPhys // (1024 * 1024)), "GlobalMemoryStatusEx"
        except Exception:
            return None, "unavailable"
    try:
        pages = os.sysconf("SC_AVPHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int(pages * page_size // (1024 * 1024)), "sysconf"
    except Exception:
        return None, "unavailable"


def _gpu() -> dict:
    """GPU facts if a local tool can report them, otherwise explicitly unknown."""
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            out = subprocess.run([smi, "--query-gpu=name,memory.total,memory.used",
                                  "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10)
            if out.returncode == 0 and out.stdout.strip():
                parts = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
                return {"available": True, "name": parts[0],
                        "memory_total_mb": int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None,
                        "source": "nvidia-smi"}
        except Exception:
            pass
    return {"available": False, "name": "unknown", "memory_total_mb": None,
            "source": "not detectable without extra tooling",
            "note": "detecting a GPU does not mean it is usable by any local engine"}


def _disk(paths: tuple[str, ...] = ()) -> dict:
    out = {}
    for path in paths or (os.path.expanduser("~"),):
        try:
            usage = shutil.disk_usage(path)
            out[path] = {"free_mb": int(usage.free // (1024 * 1024)),
                         "total_mb": int(usage.total // (1024 * 1024))}
        except Exception:
            out[path] = {"free_mb": None, "total_mb": None}
    return out


def _whisper_cache() -> dict:
    base = os.environ.get("HF_HOME", os.path.join(os.path.expanduser("~"), ".cache", "huggingface"))
    present = []
    models_dir = os.path.join(base, "hub")
    if os.path.isdir(models_dir):
        try:
            present = sorted(name for name in os.listdir(models_dir) if "whisper" in name.lower())
        except OSError:
            present = []
    return {"cache_dir": base, "models_present": present[:10]}


def collect(refresh: bool = False) -> dict:
    """Gather the inventory (cached). Never installs or downloads anything."""
    path = cache_path()
    if not refresh and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                cached = json.load(f)
            if time.time() - cached.get("collected_at", 0) < CACHE_TTL_SECONDS:
                cached["cached"] = True
                return cached
        except Exception:
            pass

    optional = {}
    import importlib.util

    for module, purpose in OPTIONAL_MODULES.items():
        try:
            # find_spec only LOOKS for the module: importing faster-whisper or playwright
            # here would load a large runtime just to answer a status question
            installed = importlib.util.find_spec(module) is not None
        except Exception:
            installed = False
        optional[module] = {"installed": installed, "purpose": purpose}

    agents = {}
    for cli in AGENT_CLIS:
        path_exe = shutil.which(cli)
        agents[cli] = {"installed": bool(path_exe), "path": path_exe}

    ram_mb, ram_source = _ram_mb()
    profile = {
        "collected_at": time.time(),
        "cached": False,
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine(), "version": platform.version()},
        "python": {"version": platform.python_version(), "executable": sys.executable,
                   "implementation": platform.python_implementation(),
                   "prefix": sys.prefix,
                   "in_venv": sys.prefix != getattr(sys, "base_prefix", sys.prefix)},
        "cpu": {"logical_cores": os.cpu_count()},
        "memory": {"available_mb": ram_mb, "source": ram_source},
        "disk": _disk(),
        "gpu": _gpu(),
        "optional_modules": optional,
        "agent_clis": agents,
        "whisper": _whisper_cache(),
        "browser": {"playwright_browsers_dir": os.path.join(
            os.path.expanduser("~"), "AppData", "Local", "ms-playwright")},
    }
    try:
        os.makedirs(permissions._config_dir(), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2, default=str)
    except OSError:
        pass
    return profile


def clear() -> bool:
    try:
        os.remove(cache_path())
        return True
    except OSError:
        return False


def summary() -> dict:
    """Short, agent-friendly capability view."""
    profile = collect()
    ram = profile["memory"]["available_mb"]
    return {
        "platform": profile["platform"]["system"] + " " + profile["platform"]["machine"],
        "python": profile["python"]["version"],
        "cpu_cores": profile["cpu"]["logical_cores"],
        "ram_available_mb": ram,
        "gpu": profile["gpu"]["name"] if profile["gpu"]["available"] else "unknown",
        "optional_modules": {k: v["installed"] for k, v in profile["optional_modules"].items()},
        "agent_clis": {k: v["installed"] for k, v in profile["agent_clis"].items()},
        "whisper_models_local": profile["whisper"]["models_present"],
        "cached": profile.get("cached", False),
    }
