# Models for your agent — local, cloud, and uncensored

Body-MCP is the **body**. The model is the **brain**, and it belongs to **your
coding agent** — Body-MCP never installs, downloads, ships or bundles a model or
Ollama. This page tells you how to connect one, and what we recommend.

Nothing below is run by Body-MCP. Every command is yours to run.

## 1. Local models (private — the text and pixels never leave your machine)

Start Ollama yourself, pull a model yourself, then point your agent at it.

```powershell
winget install Ollama.Ollama          # ~160 MB, your choice
ollama pull qwen3:0.6b                # 498 MB - text worker, private content
ollama pull qwen3-vl:2b               # 1.80 GB - text + image + video
ollama serve                         # http://127.0.0.1:11434
```

**Connecting each agent** (whichever you use — the model side is the agent's):

| Agent | How to use a local Ollama model |
|---|---|
| **OpenCode** | `opencode` lists local models: `opencode models` → pick `ollama/qwen3:0.6b`. Or set it in `opencode.jsonc` under `model` (provider `ollama`, `baseURL` `http://127.0.0.1:11434`). |
| **Codex CLI** | it speaks the OpenAI API: `setx OPENAI_BASE_URL http://127.0.0.1:11434/v1` and `setx OPENAI_API_KEY ollama`, then run `codex`. |
| **Claude Code** | it expects an Anthropic-compatible endpoint. Use a local gateway (for example `claude-code-router`) that forwards to `127.0.0.1:11434`, then set `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` in `~/.claude/settings.json`. |
| **Any other agent** | if it supports an OpenAI-compatible endpoint, point it at `http://127.0.0.1:11434/v1`. |

> Private content: with a local model, `keep_content_local=True` keeps the page
> text on your machine. Without one, the body **withholds** the text rather than
> sending it anywhere.

## 2. Cloud models (convenient — your prompts and pages leave your machine)

Any hosted provider works with the same agents (Anthropic/OpenAI-compatible
endpoints). This is the default for most people: fast, no local RAM needed.
The trade-off is that the pages you read and the text you process are sent to
that provider — which is exactly what private mode is designed to avoid.

## 3. Uncensored models

**Local (preferred).** A steerable model gives *you* the system prompt and the
guidelines; nothing is imposed on you and your data stays on your machine.

| Model | Size | Context | Notes |
|---|---|---|---|
| **`dolphin3:8b`** ← **our recommendation** | **4.92 GB** | 128K | Dolphin 3.0 (Llama 3.1 8B) — "does not impose its ethics or guidelines on you", uncensored, coding + math + tool use. Llama-3.1 Community Licence. |
| `dolphin-2.9-llama3-8b` (GGUF) | 3.03 GB (Q2_K) | 8K | smaller, older, quality loss at Q2 |
| Other abliterated/uncensored builds | varies | varies | published by various authors — verify the licence and the SHA-256 before use |

```powershell
ollama pull dolphin3:8b      # 4.92 GB, ~6 GB RAM to run comfortably
```

**Cloud.** Hosted uncensored/steerable providers exist (Body-MCP's private mode
already opens **Venice AI** as the assistant tab). Cloud is convenient; the
requests leave your machine. Use cloud uncensored for convenience, local
uncensored for privacy.

## 4. What Body-MCP recommends

| Your priority | Use this | Why |
|---|---|---|
| **Privacy first** | `qwen3:0.6b` (498 MB) for the agent's thinking; `qwen3-vl:2b` (1.80 GB) if it must see images | local, Apache-2.0, tool calling |
| **Uncensored, private** | **`dolphin3:8b`** (4.92 GB, 128K) | the best local uncensored model we have measured; steerable, Apache/Llama licence, 128K context |
| **Uncensored, convenient** | a hosted steerable provider | no local RAM; data leaves the machine |
| **Nothing installed** | the agent's own remote model | the body still works; private *content* is withheld, not shipped |

The catalogue (`body_local_models`) measures the RAM your machine actually has
and tells you which of these fit, with the exact download size and SHA-256. It
never downloads them.

## 5. A real limit to know

An 8B model needs ~6 GB of free RAM. On a 4 GB laptop, nothing local fits — the
catalogue says so instead of pretending. Cloud models are then the honest
choice, and the private *content* level is simply unavailable until you have
the RAM.

## 6. The rules that do not change

- Body-MCP **never installs or downloads** a model, Ollama or anything else.
- Never download a model without an explicit request from you.
- The model is yours; Body-MCP only detects it and suggests.
