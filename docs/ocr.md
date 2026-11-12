# Live desktop OCR

Body-MCP can read the screen: one capture on demand, or a **live observation session**
that samples the screen and only runs OCR when the frame actually changed.

Everything is local. Screenshots live in memory for the moment they are processed and are
never written to disk, the audit log or the persistent memory.

## 1. The OCR engine

OCR is a **provider**, not a hard-coded dependency (`src/body_mcp/ocr/`):

| Provider | Licence | Default? | Notes |
|---|---|---|---|
| `tesseract` | Apache-2.0 | **yes** | small, offline, fast; `tessdata_fast` models |
| `rapidocr` | Apache-2.0 | no | optional alternative; install with `pip install -e ".[ocr-rapid]"` |

Discovery order for Tesseract (first hit wins):

1. `BODY_MCP_TESSERACT_CMD` / `TESSERACT_CMD` — an explicit path,
2. a **bundled** engine in a packaged release: `vendor/tesseract/<platform>/tesseract[.exe]`,
3. `tesseract` on `PATH`,
4. the platform's standard install locations.

Language data is looked for next to the binary (`tessdata/`), in `TESSDATA_PREFIX` and in
the system locations. **Additional languages are never downloaded automatically** - a
packaged release may bundle `eng`, and the user can add more themselves.

If no engine is installed, the tools say so with the exact install command:

```
winget install -e --id UB-Mannheim.TesseractOCR     # Windows
brew install tesseract                              # macOS
apt install tesseract-ocr                           # Linux
```

## 2. Tools

| Tool | What it does |
|---|---|
| `eyes_see_desktop(monitor, language, region, provider)` | capture one screen/region and OCR it |
| `desktop_monitors()` | list the screens and which OCR engines are usable |
| `desktop_watch_start(monitor, interval, language, region, provider)` | start a live observation session |
| `desktop_watch_read(session_id, since)` | the latest observation (text, timestamp, whether it changed) |
| `desktop_watch_stop(session_id)` | stop the session and release its resources |

`region` is `[left, top, width, height]` in **physical pixels** (Windows display scaling
included).

## 3. How the live session behaves

- the screen is sampled every `interval` seconds (default 3 s, minimum 1 s);
- a frame is hashed; **only a changed frame is sent to OCR** - an idle screen costs
  almost nothing (`ocr_skipped` counts the skipped frames);
- OCR runs in a worker thread, so the MCP server never blocks;
- when free memory is low the sampling interval grows automatically
  (`< 512 MB` → ×2, `< 256 MB` → ×4) and the reason is reported in
  `desktop_watch_read().data.pressure`;
- at most two sessions run at a time;
- MCP has no push channel, so the agent **polls** `desktop_watch_read()`; the console
  shows the same events live. The tool never claims the agent "sees" changes by itself.

## 4. Privacy

- a session starts **only** on an explicit request;
- the recognised text is returned on request and is never written to disk, the audit log
  or the memory store;
- only the screen(s) or region(s) the user selected are captured;
- screen content is treated as untrusted data: it can never grant a permission or
  authorise an action; a follow-up browser/file/desktop action goes through the normal
  permission layer;
- the MCP permission `desktop_capture` gates every call (default: allow).

## 5. Acceptance test

```powershell
python scripts\acceptance_desktop.py
```

It opens a real window with a known token, captures the real screen and checks that the
OCR engine reads the token. On a machine without Tesseract it reports:

```
[PASS_REAL ] desktop capture: 170638 bytes PNG of 1920x1080 (in memory only)
[BLOCKED   ] OCR engine: no OCR engine installed -> winget install -e --id UB-Mannheim.TesseractOCR
```

That is the honest result: capture works, recognition is blocked by the missing engine.

## 6. Tesseract vs RapidOCR

| | Tesseract 5 | RapidOCR (ONNX) |
|---|---|---|
| licence | Apache-2.0 | Apache-2.0 |
| install | system package or bundled binary | `pip` extra |
| model data | separate `tessdata` files | shipped with the package |
| languages | 100+ (`tessdata_fast` covers most scripts) | mainly CJK + English |
| memory | a few MB per process | higher (ONNX runtime + models) |
| speed on a 1920x1080 screen | not measured here | not measured here |

**Measured comparison: none.** RapidOCR is not installed on this machine and Tesseract is
not installed either, so no accuracy/latency/memory numbers exist for either engine here.
That is exactly why RapidOCR is **not** the default: the recommendation in the brief was to
evaluate it before enabling it, and that evaluation has not happened. Run
`python scripts/acceptance_desktop.py --compare` (after installing both) before changing
the default.

## 7. Platform status

| Platform | Capture | OCR | Live watch | Verified here |
|---|---|---|---|---|
| Windows 11 x64 | yes (MSS) | needs Tesseract | yes | capture only (OCR blocked) |
| macOS | needs Screen Recording permission | needs Tesseract | yes | not run |
| Linux | needs a real display | needs Tesseract | yes | not run |
