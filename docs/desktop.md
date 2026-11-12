# Desktop control: the body's hands on real Windows apps

A human does not only use web pages. They click buttons in real windows, type into
real fields, and move between apps. Body-MCP can now do the same, through **Windows
UI Automation** (pywinauto) - controls are found by their **visible name**, never by
blind coordinates.

## Tools

| Tool | What it does | Permission |
|---|---|---|
| `desktop_inspect(title)` | the real control tree of a named window: name, type, position, state | `desktop_capture` (allow) |
| `desktop_click(title, control)` | invoke a named control (UIA Invoke pattern) | `desktop_control` (**ask**) |
| `desktop_type(title, control, text)` | type into a named field | `desktop_control` (**ask**) |
| `desktop_read_value(title, control)` | read the field back - the verification step | `desktop_capture` (allow) |
| `body_windows()` | the visible windows (titles only) | `desktop_capture` (allow) |

## The rules

* **Only a window you name.** There is no "the topmost window" - a title is required,
  and the window is resolved by **exact title first, then the foreground match**, so two
  windows with the same title never get mixed up.
* **Clicking and typing need approval** (`desktop_control`, default `ask`); reading does not.
* **No blind coordinates.** Clicks go through UI Automation's Invoke pattern.
* **Password-like fields are refused** (`password`, `pin`, `otp`, `card`, `cvv`...) - the
  user types those.
* **Nothing is stored**: only window titles and control names leave the machine; no
  screenshots of the desktop are taken by this path.

## Measured, for real (this machine)

`python scripts/acceptance_desktop_control.py` opens Notepad, inspects it, types, reads
the value back and closes it:

```
[PASS_REAL ] inspect the window: 44 control(s), window='Untitled - Notepad', names=['', 'Text editor', ...]
[PASS_REAL ] type into a real field: field='Text editor' typed=27
[PASS_REAL ] read the value back (verification): value='Body-MCP desktop acceptance'
[PASS_REAL ] password-like field refused: refusing to type into 'Password' - it looks like a password or card field
[PASS_REAL ] unknown control refused (no blind click): no control named 'NoSuchButtonAnywhere' in that window
[PASS_REAL ] unknown window refused: no window whose title matches 'ThereIsNoSuchWindowAnywhere'
```

The user's own Notepad window (`.dev.vars - Notepad`) was **not** touched - the precise
window selection picked the test window.

## Limits

* Windows only (UI Automation is a Windows API); macOS/Linux need their own adapters.
* Some apps render their own UI (Electron, games, GPU-heavy tools) and expose little to
  UIA - for those, the browser path or the OCR path is the honest fallback.
* `pywinauto` must be installed (it is present on this machine; it is an optional extra).
