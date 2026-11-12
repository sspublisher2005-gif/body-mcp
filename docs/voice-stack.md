# The voice stack: what Body-MCP ships, and what it deliberately does not

The brief proposed a specific stack (Whisper.cpp tiny multilingual for ASR, SAPI + optional
Piper for TTS, Kokoro as an optional neural voice, Tesseract for OCR). Here is what was
**verified** about that proposal and what Body-MCP therefore does.

## 1. Fact-check of the proposal

| Claim in the brief | Verdict | How it was checked / why it matters |
|---|---|---|
| Whisper.cpp tiny multilingual ≈ 75 MiB, ~273 MB RAM, CPU-only, Windows/macOS/Linux, includes Telugu | **plausible, not verified here** | whisper.cpp is MIT and its model table lists `tiny` at that size. It is **not installed on this machine**, so Body-MCP cannot claim it as tested. |
| sherpa-onnx: offline + streaming ASR, Apache-2.0, many platforms | **correct** | it is optional in Body-MCP; a model still has to exist for it to be useful. |
| Piper: GPL-3.0-or-later, voices have their own licences | **correct - and decisive** | bundling a GPL engine inside an MIT project would impose GPL terms on the combined work. Piper is therefore **never bundled**; users install it themselves. |
| Kokoro ONNX ≈ 114 MB quantized, higher runtime memory than Piper | **plausible** | optional in Body-MCP; not installed here, not measured here. |
| Tesseract 5 + `tessdata_fast`, Telugu available | **correct** | Tesseract is the **default** OCR engine in Body-MCP; `tessdata_fast` is preferred because it is small and fast. |
| "no single model is best at everything" | **correct** | this is why Body-MCP has a *provider* interface instead of one hard-wired model. |

One correction to the brief: it wrote "Piper is GPL-3.0" while the engine's own
repository is `OHF-Voice/piper1-gpl` - the *older* `rhasspy/piper` was MIT. That
difference is exactly why the engine is not bundled here.

## 2. What Body-MCP actually ships

| Capability | Default | Alternatives | Bundled? |
|---|---|---|---|
| **Speech-to-text** | `faster-whisper` (MIT) | `whisper.cpp` (MIT), `sherpa-onnx` (Apache-2.0) | no - install with `pip install -e ".[voice]"` |
| **Text-to-speech** | Windows **SAPI** (built into the OS, zero download) | Kokoro, Piper, edge-tts | SAPI needs nothing; the others are installed by the user |
| **OCR** | **Tesseract 5** (Apache-2.0) | RapidOCR (Apache-2.0) | a packaged release may bundle the Tesseract binary + `eng` data |
| **Screen capture** | MSS (MIT) | platform adapters | yes (tiny wheel) |

Providers live in `src/body_mcp/voice.py` (ASR) and `src/body_mcp/ocr/` (OCR). Each one
reports what is installed, what is missing and what it would cost in memory.

## 3. The rules that make it work on a small machine

1. **No automatic downloads.** A model is used only if it is already present; installing
   one is an explicit user action (`pip install -e ".[voice]"` or the engine's own
   installer).
2. **Lazy loading.** Engines are imported only when a recording is transcribed or a
   sentence is spoken - never at server start-up.
3. **A memory guard.** `voice.transcribe_array()` refuses to load a speech model when
   less than 512 MB of RAM is free, and says so instead of thrashing.
4. **Silence is not text.** A recording that is essentially silent is reported as
   "no speech detected" rather than transcribed into invented words.
5. **Push to talk.** Recording only starts when the user asks for it; the raw audio never
   touches the disk and is zeroed in memory afterwards.
6. **Read Aloud is optional and stoppable** (`body_speak`, `body_stop_speaking`).
7. **Remote services are opt-in and disclosed.** `edge-tts` sends text to Microsoft; it is
   never the default and Body-MCP does not enable it for you.

## 4. Telugu and mixed-language input

The proposal's point about Telugu is right, and the honest answer for Body-MCP is:

- `faster-whisper` supports Telugu (Whisper is multilingual), but **accuracy for Telugu
  was not measured on this machine** - the model weights are not downloaded and no
  recording was transcribed;
- `whisper.cpp` with a multilingual model is the better choice if Telugu matters, and it
  is supported as an optional provider;
- **no accuracy claim is made for any language on any machine** until a real evaluation
  set has been transcribed. `docs/release.md` and the QA report keep that honest.

A measured evaluation (word error rate on a documented sample, time to first partial
transcript, peak memory) is still **open** - see the remaining items in the QA report.

## 5. What to do next (ordered)

1. `pip install -e ".[voice]"` and set `BODY_MCP_WHISPER_MODEL=tiny.en` on a 4 GB machine
   (`small.en` needs ~484 MB of weights and more RAM).
2. Grant recording consent once and run `python scripts\acceptance.py --allow-mic` to turn
   the live STT case from NOT_RUN into a real result.
3. If Telugu accuracy matters, install whisper.cpp and a multilingual model, then point
   `BODY_MCP_WHISPER_CPP` at the binary; Body-MCP picks it up without a code change.
4. Install Tesseract to unlock the desktop OCR path.
