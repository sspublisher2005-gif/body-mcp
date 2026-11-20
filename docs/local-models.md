# Local models: the catalogue, the tiers, and how to pick one

Body-MCP never downloads a model. You pick one, you fetch it, and the catalogue
tells you what it costs, how to verify it, and whether **your** machine can run
it.

## The two roles

| Role | What it does | Size class |
|---|---|---|
| **worker** (private) | extraction to JSON, classification, dedup keys, PII scrubbing, short summaries — **all offline** | 0.27 B – 2 B |
| **reasoner** | the agent's own thinking, run locally instead of remotely | 2 B – 8 B |

The body is the body: the **worker** does the private, local, cheap passes; the
**brain** (your agent's model) still does the reasoning. A local worker never
replaces the brain.

## Two runtimes, one catalogue

* **Ollama** — one command, no compiler, no build step:
  `ollama pull qwen3:0.6b` → `http://127.0.0.1:11434`.
* **llama.cpp** — the same models as GGUF files you download yourself
  (URL + exact bytes + SHA-256 in the catalogue), plus
  `pip install llama-cpp-python`.

Both are local-only. The worker refuses a runtime URL that is not on the machine
(127.0.0.1), so content cannot leak through a misconfigured endpoint.

## The catalogue (measured sizes and SHA-256)

### Ollama (sizes = the exact blob bytes in the registry manifest)

| Tag | Download | RAM | Licence | Tools | Vision | Uncensored | Tier |
|---|---|---|---|---|---|---|---|
| **qwen3:0.6b** | **498 MB** (522 640 096 B) | ~950 MB | Apache-2.0 | ✅ | ✗ | no | **1 — default worker** |
| qwen3:0.6b-q8_0 | 794 MB (832 278 240 B) | ~1.25 GB | Apache-2.0 | ✅ | ✗ | no | 1 — same worker, better quality |
| gemma3:270m | 278 MB (291 545 472 B) | ~700 MB | Gemma terms | ✗ | ✗ | no | 1 — the smallest **text** model |
| **qwen3-vl:2b** | **1.80 GB** (1 889 496 384 B) | ~3.0 GB | Apache-2.0 | ✅ | ✅ | no | **2 — eyes + tools + thinking** |
| **dolphin3:8b** | **4.92 GB** (4 920 749 184 B) | ~6.2 GB | Llama-3.1 Community | ✅ | ✗ | ✅ | **3 — uncensored reasoning** |

### llama.cpp (GGUF — the URL is `huggingface.co/<repo>/resolve/main/<file>`)

| File | Download | RAM | Licence | Tools | Vision | Uncensored | Tier |
|---|---|---|---|---|---|---|---|
| **Qwen3-0.6B-Q4_0.gguf** | **409 MB** (428 970 080 B) | ~900 MB | Apache-2.0 | ✅ | ✗ | no | **1 — default worker** |
| gemma-3-270m-it-Q8_0.gguf | 278 MB (291 545 600 B) | ~700 MB | Gemma terms | ✗ | ✗ | no | 1 — the smallest **text** model |
| Qwen3-1.7B-Q4_K_M.gguf | 1.22 GB (1 282 439 264 B) | ~2.0 GB | Apache-2.0 | ✅ | ✗ | no | 2 — clearly stronger worker |
| **Qwen3-VL-2B-Instruct-Q8_0.gguf** + `mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf` | **2.14 GB** (1 834 427 296 + 445 053 056 B) | ~3.2 GB | Apache-2.0 | ✅ | ✅ | no | **2 — the one-model pick** |
| dolphin-2.9-llama3-8b-Q2_K.gguf | 3.03 GB (3 179 141 824 B) | ~4.4 GB | Llama-3 Community | ✗ | ✗ | ✅ | 3 — smallest uncensored |
| dolphin-2.9-llama3-8b-Q3_K_M.gguf | 3.83 GB (4 018 929 152 B) | ~5.4 GB | Llama-3 Community | ✗ | ✗ | ✅ | 3 — better uncensored |

**Verified digests**

```
Qwen3-0.6B-Q4_0.gguf                428 970 080 B
  sha256 da2572f16c06133561ce56accaa822216f2391ef4d37fba427801cd6736417d4
gemma-3-270m-it-Q8_0.gguf           291 545 600 B
  sha256 0ef57d2c838458a1952664260dcba38e5bdda37494f3af732f06e4add24068e3
Qwen3-1.7B-Q4_K_M.gguf             1 282 439 264 B
  sha256 d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5
Qwen3-VL-2B-Instruct-Q8_0.gguf     1 834 427 296 B
  sha256 b7802e29f71a9e5b5e3f83f613df898a2204342dcea71a231ea501d481813c39
mmproj-Qwen3-VL-2B-Instruct-Q8_0.gguf   445 053 056 B
  sha256 69066c8f279ec85ff48ab4059f6ebba0d2932ca57667f2bbdac7d9805bca9e7b
dolphin-2.9-llama3-8b-Q2_K.gguf   3 179 141 824 B
  sha256 72a1461f5be05f668d330b94b6e011bafe69a25605f88aba7f01056c6c37639a
dolphin-2.9-llama3-8b-Q3_K_M.gguf 4 018 929 152 B
  sha256 0f9e5d9e1fadbe6e8dcac550aae56e9488910e374f735cd70f6522254e4fb61b
```

Ollama blobs are content-addressed: `ollama pull` verifies the digest itself, so
you do not have to check the hash by hand.

## The tiers (the answer to "which one do I download?")

| Your machine | Download this | RAM it needs |
|---|---|---|
| ~1 GB free | **qwen3:0.6b** (Ollama, 498 MB) | ~950 MB |
| ~700 MB free | **gemma3:270m** (Ollama, 278 MB) — text only, no structured output | ~700 MB |
| ~3 GB free | **qwen3-vl:2b** (Ollama, 1.80 GB) — eyes + websearch tools + thinking | ~3.0 GB |
| ~6 GB free | **dolphin3:8b** (Ollama, 4.92 GB) — uncensored local reasoning | ~6.2 GB |
| no local model at all | nothing — the agent's own model does the reasoning; the worker is optional | — |

## How the recommendation works (per machine, not per author)

`body_local_models()` measures **your** free RAM and ranks the catalogue:

* models that fit are listed first, with the headroom spelled out;
* a model that does **not** fit is still listed, marked `fits: false` with the exact
  shortfall — it is never handed over as "the one to use";
* if nothing fits, the tool says so instead of pretending;
* models already on your machine are marked `installed: true` and ranked first.

## The rules

* **Never downloaded automatically.** You fetch; the catalogue gives the command or
  the URL, the size and the checksum.
* **Never loaded before it is needed** — the worker loads lazily and only when a
  task asks for it.
* **Nothing leaves the machine through the worker** — that is the whole point.
* **No remote fallback.** With no local model the worker refuses and says what to
  install. It never quietly sends your text to a provider.
* **Uncensored is a choice, not a default.** Under ~3 GB there is no notable
  uncensored model, and for *research* the blockers are platform policies, not the
  model's permissiveness.

## Being the eyes for a text-only brain

One of the measured models can look at an image:

* `qwen3-vl:2b` — 1.80 GB, eyes + tool calls + thinking.

**Correction (2026-11-17):** this page used to list `gemma3:270m` as having eyes.
A real GitHub Actions runner sent an image to it and Ollama answered
`"Multimodal data provided, but model does not support multimodal requests"`,
and the Gemma-3-270m GGUF release ships no vision projector. It is **text-only**;
the body now refuses to hand it an image.

With one of them installed, the body can describe what is on screen **entirely on
your machine**:

```python
image = eyes_see_desktop(as_image=True)            # the body captures the screen
caption = body_local_worker(task="describe", image=image["image_data"])
# -> "- a code editor\n- a red error banner: 'TypeError: x is not a function'\n- ..."
```

Then the text-only brain (Qwen3-0.6B, Dolphin) reads the caption like text.

Limits, stated plainly:

* a small captioner says *"a code editor with a red error banner"* — it does **not**
  give you the exact error line. OCR is better at exact text; the captioner is
  better at layout and meaning.
* a native-vision reasoner (Qwen3-VL-2B) beats both, at 1.80 GB.
* `describe` refuses when no local **vision** model is installed: a text-only model
  would invent a caption, and an invented caption is worse than none.
* the llama.cpp path does not take images yet — use Ollama for `describe`.
