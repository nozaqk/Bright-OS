# AURA AI Modes

AURA supports three operating modes for artificial intelligence features.
Mode can be changed at runtime via the D-Bus API or Settings UI; **no
reinstall is required** to switch.

## LOCAL (Default)

- AI inference runs entirely on the local machine.
- Uses locally installed GGUF models via llama.cpp (preferred).
- Ollama is auto-detected if installed but **never required**.
- Qwen-family models in GGUF format are officially supported.
- No conversation data leaves the machine.
- Model weights are **NOT included in the ISO** — users download them on
  demand through an explicit action.
- Adaptive Resource Manager selects appropriate model size based on RAM,
  CPU cores, GPU presence, and battery state.
- Works without internet.

## HYBRID

- Local AI handles routine queries by default.
- Optional cloud API calls (OpenAI-compatible HTTPS endpoint) for
  advanced reasoning.
- Requires explicit cloud endpoint configuration AND an API key retrieved
  from secure storage (either an external command or a `0600` file —
  **never** plaintext in `aura.conf`).
- Every cloud call requires interactive user consent by default.
- The endpoint is validated against SSRF (no localhost, no private IPs,
  https-only).
- Cloud is **disabled by default** even when a key is configured.
- If a cloud request fails, the error is reported to the caller; AURA
  does NOT silently fall back to sending previous prompts to a different
  provider without user awareness.

## OFFLINE

- All external AI communication disabled entirely (including model
  downloads).
- Available local models may still be used.
- System management and security monitoring remain fully functional.
- Suitable for air-gapped or privacy-sensitive environments.

## Mode switching at runtime

Changing mode (e.g. LOCAL -> OFFLINE):
- Cancels any in-flight cloud requests.
- Preserves currently loaded local model (so you can suspend cloud use
  without reloading your model).
- Emits the `AIEvent` D-Bus signal with `mode_changed`.
- Persists the new mode in `aura.conf` if the config dir is writable.

## Model support

| Backend  | Local? | Required? | Format |
|----------|--------|-----------|--------|
| llama.cpp | Yes | Preferred (installed via `llama-cli` Debian package) | GGUF |
| Ollama   | Yes | Optional (user-installed) | Ollama model store |
| Cloud    | No  | Hybrid only, consent required | OpenAI-compatible HTTPS |

Model discovery scans `/var/lib/aura/models/` by default (configurable
via `model_dir` in `aura.conf`).

## When no model is available

AURA Core remains fully operational:
- Security monitoring active
- System health and service management work
- Command engine (Phase 3) will perform safe built-in operations
- UI shows "AI unavailable" with an option to open model settings
- No crash, no hang, no dependency loop

## Privacy guarantees

- Conversation data stays local by default.
- API keys never touch the world-readable config file.
- No telemetry, no phoning home.
- The cloud consent prompt is shown per request by default.
- Prompts and responses are never written to logs.
- Users can inspect and delete all conversation data from
  `/var/lib/aura/conversations/`.

## Resource management integration

All three modes are subject to the Adaptive Resource Manager:
- Models are loaded lazily on first inference, never at boot.
- Loaded models are unloaded after 10 minutes idle (2 min on Lite, 30
  min on Developer edition).
- On low battery, memory caps tighten and CPU thread count is reduced.
- Under extreme memory pressure, in-flight requests are cancelled to
  keep the desktop responsive.

See `RESOURCE-MANAGEMENT.md` and `LOCAL-MODELS.md` for details.
