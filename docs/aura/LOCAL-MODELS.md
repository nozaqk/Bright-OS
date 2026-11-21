# Local Models in AURA

AURA runs local large-language models using **llama.cpp** (preferred, GGUF format).
Qwen-family models are supported via GGUF conversions. Ollama is optionally
auto-detected when installed but is **never required**.

## Key principles

- **Model weights are NOT included in the ISO.** The ISO ships with zero model
  weights. No AI model is downloaded automatically, and no model is loaded at
  boot.
- **User-initiated downloads.** Users choose when and which model to download,
  either by placing a `.gguf` file in the model directory or by invoking the
  download through Settings.
- **Validation before loading.** Before a model is loaded we check:
  - File is readable, non-empty, and above a minimum size
  - GGUF magic number is present for `.gguf` files
  - Estimated memory requirements fit within current resource policy
- **One loaded model at a time.** AURA keeps at most one local model loaded
  and unloads it after an idle period (default 10 minutes).

## Supported formats

| Format | Provider | Notes |
|--------|----------|-------|
| GGUF   | llama.cpp | Preferred. Works CPU-only, fast, robust |
| Ollama | Ollama (optional) | Any Ollama-pulled model, uses its own runtime |
| Cloud  | OpenAI-compatible HTTPS | Hybrid mode only, consent required |

## Model directory

Default model directory: `/var/lib/aura/models/` (mode `0755`, owned by
`aura:aura`). Change this in `/etc/bright-os/aura/aura.conf`:

```ini
[intelligence]
model_dir = /mnt/external/models
```

The Lite edition prefers external/removable storage.

## Adding a model manually

Copy a valid `.gguf` file into the model directory and rescan:

```bash
sudo cp qwen2.5-3b-instruct-q4_k_m.gguf /var/lib/aura/models/
sudo chown aura:aura /var/lib/aura/models/qwen2.5-3b-instruct-q4_k_m.gguf
dbus-send --system --type=method_call --dest=org.bright_os.AURA \
  /org/bright_os/AURA org.bright_os.AURA.ListAIModels
```

## Recommended model sizes by hardware tier

| Tier | RAM  | Recommended model |
|------|------|-------------------|
| low  | <4 GB | Qwen 2.5 1.5B (Q4) |
| medium | 4–8 GB | Qwen 2.5 3B (Q4) |
| high | ≥8 GB + GPU or 8+ threads | Qwen 2.5 7B (Q4) |

Suitability is re-evaluated live — you don't need to pick the "right" model
up front; AURA will refuse to load a model that doesn't fit.

## Downloads (user-initiated)

Use `busctl` or a Settings UI to invoke a download. Downloads validate the
file after fetching. If validation fails, the partial file is removed.

AURA never downloads over plain HTTP unless an admin explicitly configures
a mirror, and never downloads anything without an explicit user action.
