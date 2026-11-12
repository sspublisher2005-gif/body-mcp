# How the body sees and hears

The agent is the brain; the body only perceives and acts. This document states exactly
what reaches the model, what does not, and why.

## 1. Fact-check of the previous description

| Claim | Verdict | Reality in the code |
|---|---|---|
| "No screenshots are sent at all" | **was true, now changed** | Until v0.3.0 the eyes returned text and structure only. **Vision mode** (below) now hands over one downscaled image **on request**. |
| `eyes_see_browser` = Playwright DOM/accessibility tree | **mostly true** | It is the **DOM** (querySelectorAll over links/buttons/inputs/forms), *not* Playwright's accessibility tree. Text is capped at 20 000 chars, elements at 400 per page. |
| refs like `btn_1#7` | true | epoch-scoped: a ref from an older scan is refused instead of retargeting. |
| `eyes_see_desktop` = MSS → PNG in memory → Tesseract → text | true | The PNG is discarded, never stored, never sent. **On this machine OCR is BLOCKED** (Tesseract is not installed) - the capture is real, the recognition is not. |
| `desktop_watch_read` = latest OCR result | true, and now richer | text + timestamp + changed flag + skipped-frame count, **plus optionally the frame itself** (`as_image=True`). |
| "MCP has no server→client push for tool results" | true | There is no push channel for tool results, so live means *polling* `desktop_watch_read()`; the console shows the same stream live. |
| capture ~10–30 ms, OCR 0.5–1.5 s, snapshot ~200–400 ms | **plausible, only partly measured here** | The screen capture is measured (~30 ms for 1920×1080); **the OCR timings are NOT measured on this machine** (no Tesseract). The Playwright snapshot is measured per call in the QA matrix. |
| "the right addition is an optional image content block" | correct - implemented | `vision.prepare_image()` + an MCP image block next to the text (see §3). |

## 2. What the eyes give the brain

| Path | What is produced | What reaches the model |
|---|---|---|
| `eyes_see_browser(url)` | DOM structure + text | title, url, headings, text (≤20 k chars), links, buttons, inputs, forms, refs - a few KB |
| `eyes_see_browser(url, screenshot=True)` | the same **plus one image** | the text block **and** a downscaled JPEG (max width 1280, ≤900 KB) |
| `eyes_see_desktop()` | screen capture + OCR | recognised text + a safety scan; the PNG is discarded |
| `eyes_see_desktop(as_image=True)` | the same **plus one image** | text block + downscaled JPEG of the screen/region |
| `desktop_watch_read()` | the live session's latest observation | text + timestamp + changed flag + skipped frames |
| `desktop_watch_read(as_image=True)` | the same **plus the frame** | text block + the last frame, downscaled |

Rules that hold for every path:

- **Text first.** Pages are read structurally (fast, exact). OCR is the fallback for
  anything that is not a DOM.
- **Pixels only on request.** No image enters the context unless the agent asks for one.
- **One image, one call.** Never a stream of frames (that would flood the context, and a
  model cannot re-read a stream it missed).
- **Nothing is stored.** Images live in memory for the transport and are gone afterwards;
  the audit log records only that an image was produced and how many bytes it was.
- **The permission gate is the same one.** `public_web` / `desktop_capture` decide whether
  a capture may happen at all.

## 3. Vision mode - how it works

1. The tool captures the real page/screen (Playwright screenshot / MSS capture).
2. `vision.prepare_image()` downscales to ≤1280 px wide and compresses to JPEG
   (quality 70, then lower, then a further halving if it is still over the cap).
3. The result is returned as an MCP `CallToolResult` with **two content blocks**: the
   usual JSON text block (so clients without image support still get everything) and the
   image block, with the structured payload unchanged.
4. If Pillow is not installed, the raw PNG is sent when it fits the cap, otherwise the
   tool says exactly what to install - it never ships an oversized blob.

Measured here (real Chromium, real MCP client): the fixture page produced
**text + image** blocks, a **20 471-byte JPEG at 1280×720** (27 296 base64 characters).

## 4. What the ears give the brain

| Path | Behaviour |
|---|---|
| `ears_listen(seconds=8, stop_on_silence=True)` | push-to-talk: recording starts on request and **ends shortly after the user stops talking** (silence detection, 700 ms), capped at `seconds` |
| silence | reported as *"no speech detected"* - never transcribed into invented words |
| transcript | returned as **editable text**, with the fragments recognised at low confidence listed separately (`uncertain`) so the agent can ask the user to confirm them |
| raw audio | in memory only, zeroed after use, never written to disk, never transmitted |

The recording never starts on its own: it is a tool call, i.e. an explicit user action.

## 5. What still needs work

- **Streaming partial transcripts** need a streaming engine (whisper.cpp or sherpa-onnx);
  both are supported in the provider registry but are not installed here, so the agent
  still gets the transcript after the fact.
- **Word error rate / latency per language** is not measured (see `docs/voice-stack.md`).
- **Desktop OCR quality** is unmeasured on this machine (no Tesseract).
- **Accessibility-tree perception** for web pages is not used: the DOM path is cheaper and
  exact, but a canvas-only page still needs the image mode (which now exists).
