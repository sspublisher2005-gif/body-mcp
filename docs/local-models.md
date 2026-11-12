# Local models: the catalogue, the tiers, and how to pick one

Body-MCP never downloads a model. You pick one, you fetch it, you point
`BODY_MCP_LOCAL_MODEL` at it. This page tells you what exists, what it costs and
what your machine can actually run.

## The role of a local model

| Role | What it does | Size class |
|---|---|---|
| **worker** (private) | extraction to JSON, classification, dedup keys, PII scrubbing, short summaries — **all offline** | 0.3–1.7 B |
| **reasoner** | the agent's own thinking, run locally instead of remotely | 8 B+ |

The body is the body: the **worker** does the private, local, cheap passes; the
**brain** (your agent's model) still does the reasoning. A local worker never
replaces the brain.

## The catalogue (measured sizes and SHA-256 from the Hugging Face API)

| Model | File size | RAM needed | Licence | Tools | Uncensored | Tier |
|---|---|---|---|---|---|---|
| **Qwen3-0.6B (Q4_0)** | **409 MB** | ~900 MB | Apache-2.0 | ✅ | no | 1 — the default worker |
| Gemma-3-270m-it (Q8_0) | 278 MB | ~700 MB | Gemma terms (free, use policy) | ✗ | no | 1 — the smallest |
| Qwen3-1.7B (Q4_K_M) | 1.22 GB | ~2.0 GB | Apache-2.0 | ✅ | no | 2 — clearly stronger |
| Dolphin 2.9 Llama-3-8B (Q2_K) | 3.03 GB | ~4.4 GB | Apache-2.0 weights | ✗ | ✅ | 3 — smallest uncensored |
| Dolphin 2.9 Llama-3-8B (Q3_K_M) | 3.83 GB | ~5.4 GB | Apache-2.0 weights | ✗ | ✅ | 3 — better uncensored |

All of them are the same GGUF + llama.cpp on **Windows, macOS and Linux** — one
catalogue, three platforms.

### Verified download + integrity data

```
Qwen3-0.6B-Q4_0.gguf        428 970 080 B
  sha256 da2572f16c06133561ce56accaa822216f2391ef4d37fba427801cd6736417d4
Gemma-3-270m-it-Q8_0.gguf    291 545 600 B
  sha256 0ef57d2c838458a1952664260dcba38e5bdda37494f3af732f06e4add24068e3
Qwen3-1.7B-Q4_K_M.gguf     1 282 439 264 B
  sha256 d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5
dolphin-2.9-llama3-8b-Q2_K.gguf   3 179 141 824 B
  sha256 72a1461f5be05f668d330b94b6e011bafe69a25605f88aba7f01056c6c37639a
dolphin-2.9-llama3-8b-Q3_K_M.gguf 4 018 929 152 B
  sha256 0f9e5d9e1fadbe6e8dcac550aae56e9488910e374f735cd70f6522254e4fb61b
```

## How the recommendation works (per machine, not per author)

`body_local_models()` measures your **free RAM** and ranks the catalogue:

* models that fit are listed first, with the headroom spelled out;
* a model that does **not** fit is still listed, but marked `fits: false` with the exact
  shortfall — never recommended as "the one to use";
* if nothing fits, the tool says so instead of pretending.

The runtime is separate: `pip install llama-cpp-python` (Body-MCP never installs it).
Point `BODY_MCP_LOCAL_MODEL` at the file, and `body_privacy_preflight()` will report it
as configured — and verify its checksum.

## The rules

* **Never downloaded automatically.** The user fetches; the catalogue gives the URL, the
  size and the checksum.
* **Never loaded before it is needed** — the worker loads lazily and only when a task
  asks for it.
* **Nothing leaves the machine** through the worker: that is the whole point of it.
* **Uncensored is a choice, not a default.** Under ~3 GB there is no notable uncensored
  model, and for *research* the blockers are platform policies, not the model's
  permissiveness.
