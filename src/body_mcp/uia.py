"""Desktop hands: drive native Windows apps the way a human does.

A person does not only use web pages - they click buttons in real windows, type into
real fields, and move between apps. This module gives the agent the same reach,
through **Windows UI Automation** (pywinauto): controls are found by their visible
name, not by blind coordinates.

Safety model (the same rules as the browser hands):
  - only windows the USER names may be touched (never "the topmost window"),
  - window selection is precise: exact title first, then the foreground match -
    two windows with the same title never get mixed up,
  - reading a window's controls is allowed; clicking or typing needs the
    `desktop_control` permission (default: ask),
  - clicks go through UI Automation's Invoke pattern - not blind coordinates,
  - typing refuses sensitive-looking fields (password boxes),
  - nothing is screenshotted or stored: the window title and control names are the
    only things that leave the machine.
"""
from __future__ import annotations

import contextlib
import re
import time

MAX_CONTROLS = 200
MAX_NAME = 120
SENSITIVE_HINTS = ("password", "passwort", "secret", "pin", "otp", "credit card",
                    "card number", "cvv", "security code")


def _desktop():
    try:
        from pywinauto import Desktop
    except Exception as exc:
        raise RuntimeError(f"pywinauto is not installed ({exc}) - pip install pywinauto") from exc
    return Desktop


def _candidate_handles(title: str) -> list[int]:
    """Visible top-level windows whose title matches (exact first, then contains)."""
    try:
        import win32gui
    except Exception:
        return []
    exact: list[int] = []
    partial: list[int] = []
    needle = (title or "").strip().lower()

    def collect(handle, _extra):
        if not win32gui.IsWindowVisible(handle):
            return True
        text = (win32gui.GetWindowText(handle) or "").strip()
        if not text:
            return True
        lowered = text.lower()
        if lowered == needle:
            exact.append(handle)
        elif needle and needle in lowered:
            partial.append(handle)
        return True

    win32gui.EnumWindows(collect, None)
    return exact + partial


def _window_text(window) -> str:
    try:
        return window.window_text()
    except Exception:
        return ""


def _connect(title: str, timeout: float = 10.0):
    """ONE specific window: exact title first, then the foreground match."""
    Desktop = _desktop()
    handles = _candidate_handles(title)
    chosen = None
    if handles:
        try:
            import win32gui

            foreground = win32gui.GetForegroundWindow()
            chosen = foreground if foreground in handles else handles[0]
        except Exception:
            chosen = handles[0]
    if chosen is not None:
        try:
            window = Desktop(backend="uia").window(handle=chosen)
            window.wait("exists ready", timeout=timeout)
            return window
        except Exception:
            pass
    try:
        from pywinauto import Application

        app = Application(backend="uia").connect(title_re=f".*{re.escape(title)}.*", timeout=timeout)
        return app.top_window()
    except Exception as exc:
        raise RuntimeError(f"no window whose title matches {title!r} ({exc})") from exc


def _find_control(window, name: str):
    """A control by exact visible name, then by a containing name."""
    needle = (name or "").strip().lower()
    exact = []
    partial = []
    for control in window.descendants():
        try:
            control_name = (control.element_info.name or "").strip()
        except Exception:
            continue
        if not control_name:
            continue
        lowered = control_name.lower()
        if lowered == needle:
            exact.append(control)
        elif needle and needle in lowered:
            partial.append(control)
    return exact or partial


def inspect(title: str, timeout: float = 10.0) -> dict:
    """List the named controls of a window (name, type, position, state)."""
    try:
        window = _connect(title, timeout)
        controls = []
        for control in window.descendants():
            try:
                info = control.element_info
                name = (info.name or "")[:MAX_NAME]
                control_type = info.control_type or ""
                rect = control.rectangle()
                controls.append({
                    "name": name,
                    "type": control_type,
                    "enabled": bool(control.is_enabled()),
                    "visible": bool(control.is_visible()),
                    "left": rect.left, "top": rect.top,
                    "width": rect.width(), "height": rect.height(),
                    "sensitive": any(hint in name.lower() for hint in SENSITIVE_HINTS),
                })
            except Exception:
                continue
            if len(controls) >= MAX_CONTROLS:
                break
        return {"ok": True, "window": _window_text(window), "controls": controls,
                "count": len(controls)}
    except RuntimeError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def focus(title: str, timeout: float = 10.0) -> dict:
    """Bring a named window to the front."""
    try:
        window = _connect(title, timeout)
        try:
            window.set_focus()
        except Exception:
            window.restore()
            window.set_focus()
        return {"ok": True, "focused": _window_text(window)}
    except RuntimeError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def click(title: str, name: str, timeout: float = 10.0) -> dict:
    """Invoke a control by its visible name (never by coordinates)."""
    try:
        window = _connect(title, timeout)
        matches = _find_control(window, name)
        if not matches:
            return {"ok": False, "reason": f"no control named {name!r} in that window"}
        control = matches[0]
        try:
            control.invoke()
        except Exception:
            control.click_input()
        time.sleep(0.2)
        return {"ok": True, "clicked": (control.element_info.name or name)[:MAX_NAME],
                "window": _window_text(window)}
    except RuntimeError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def type_text(title: str, name: str, text: str, timeout: float = 10.0) -> dict:
    """Type into a named field (refuses password-like fields)."""
    if any(hint in (name or "").lower() for hint in SENSITIVE_HINTS):
        return {"ok": False,
                "reason": f"refusing to type into {name!r} - it looks like a password or "
                          "card field; the user must type those"}
    try:
        window = _connect(title, timeout)
        matches = _find_control(window, name)
        if not matches:
            return {"ok": False, "reason": f"no field named {name!r} in that window"}
        control = matches[0]
        with contextlib.suppress(Exception):
            control.set_focus()
        # the caret needs the window to actually have focus before keystrokes land
        time.sleep(0.3)
        try:
            control.set_edit_text(text)
        except Exception:
            control.type_keys(text, with_spaces=True, pause=0.03)
        time.sleep(0.3)
        return {"ok": True, "typed": len(text), "into": (control.element_info.name or name)[:MAX_NAME],
                "window": _window_text(window)}
    except RuntimeError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}


def read_value(title: str, name: str, timeout: float = 10.0) -> dict:
    """Read the current value of a named field (the verification step)."""
    try:
        window = _connect(title, timeout)
        matches = _find_control(window, name)
        if not matches:
            return {"ok": False, "reason": f"no field named {name!r} in that window"}
        control = matches[0]
        value = ""
        try:
            value = control.get_value()
        except Exception:
            try:
                value = control.window_text()
            except Exception:
                value = ""
        return {"ok": True, "value": (value or "")[:500], "window": _window_text(window)}
    except RuntimeError as exc:
        return {"ok": False, "reason": str(exc)}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
