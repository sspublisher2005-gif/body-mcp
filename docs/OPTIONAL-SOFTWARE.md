# Optional software — suggestions only, never installed

> **Who owns the local model?** Your coding agent. Body-MCP is the body; the
> reasoning model (local or remote) is the brain and belongs to the agent and
> the user. Body-MCP never installs, downloads, ships or bundles Ollama, a
> model, or any other engine — not in the build, not at runtime, not through the
> doctor. It only detects what is already there and tells you what could help:
> a **private** model keeps content on your machine (`qwen3:0.6b` /
> `qwen3-vl:2b`); an **uncensored** local model exists (`dolphin3:8b`). The
> choice, the download and the storage location are yours.

**Body-MCP installs nothing. Ever.** No engine, no model, no browser, no pip
package is installed by the body or by an agent following these docs. The body
detects what is already on the machine, says what is missing, and prints the
exact command — **you** decide whether to install it, when, and where to save it.

This is a hard rule because a coding agent can otherwise turn a small request
into gigabytes of downloads on a low-end laptop. See `docs/DECISIONS.md` (D17).

## What Body-MCP needs

Nothing. The core works with Python 3.11+ and the browser that Playwright
already ships with. Everything below is optional, free, and improves one thing.

| What it unlocks | Suggestion (run it yourself, if you want) | Download | Saves to |
|---|---|---|---|
| Local text worker (private content) | `winget install Ollama.Ollama` → `ollama pull qwen3:0.6b` | ~160 MB installer + 498 MB model | Ollama's own store (`%LOCALAPPDATA%\Ollama`) |
| Local eyes for a text-only brain | `ollama pull qwen3-vl:2b` | 1.80 GB | Ollama's own store |
| Vision + tools + thinking in one | `ollama pull qwen3-vl:2b` | 1.80 GB | Ollama's own store |
| Uncensored local reasoner | `ollama pull dolphin3:8b` | 4.92 GB | Ollama's own store |
| Desktop text recognition (OCR) | `winget install -e --id UB-Mannheim.TesseractOCR` | ~50 MB | your chosen install dir |
| Faster video learning | `winget install ffmpeg` or `pip install opencv-python` | ~80 MB | your chosen install dir |
| Live speech-to-text | `pip install ".[voice]"` then download `tiny.en` | model varies | your chosen cache dir |
| Driving your everyday browser | load `extension/` in Edge/Chrome (one click) | 0 MB | the browser |
| VPN assistance | install Proton VPN yourself and enable `vpn_control` | ~200 MB | your chosen install dir |
| Private browser brand | install Brave | ~200 MB | your chosen install dir |

Every size above was read from the official source (Hugging Face API / Ollama
registry manifests / the installers), not guessed. `body_local_models()` shows
the same figures with checksums and ranks them against **your** free RAM.

## If you do install something

- **You** choose the destination. Body-MCP never chooses for you.
- The catalogue gives the exact byte size and SHA-256 so you can verify it.
- `python -m body_mcp.doctor` then reports it as available, and the body uses it
  automatically — no configuration unless noted.
- If nothing is installed, the honest result stands: that capability is
  `BLOCKED` or mock-tested, never "working".

## If you don't install anything

- Browser, desktop and research still work (the browser that ships with
  Playwright is used).
- The private *browsing* level works for free.
- The private *content* level reports "no local model available" and **withholds**
  the page text instead of sending it to a remote provider.
- The image path works without OCR: a vision model can look at the screenshot
  on any machine, even with no Tesseract installed.

The proof of every capability on **your** machine is:
`python -m body_mcp.doctor`
