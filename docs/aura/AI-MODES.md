# AURA AI Modes

AURA supports three operating modes for artificial intelligence features:

## LOCAL (Default)

- AI inference runs entirely on the local machine
- Uses locally installed models (Qwen family, or user-supplied GGUF models via llama.cpp)
- No conversation data leaves the machine
- Model weights are NOT included on the ISO — users download them on demand
- Hardware-aware model selection (picks model size based on available RAM/VRAM)
- Works without internet

## HYBRID

- Local AI handles routine queries by default
- Optional cloud API calls for advanced reasoning
- Requires explicit cloud endpoint configuration AND API key
- Every cloud call requires user consent (configurable)
- Never uploads personal files, screen content, or conversation history without authorization
- Falls back to local if cloud is unreachable

## OFFLINE

- External AI communication disabled entirely
- Available local models may still be used
- System management and security monitoring fully functional
- Suitable for air-gapped or privacy-sensitive environments

## Model Support (Phase 2)

Initial model backends:
- **Qwen**: Qwen2.5 family (0.5B–7B), multiple quantizations
- **llama.cpp**: GGUF model support for CPU/GPU inference
- **Ollama**: Optional backend if user installs ollama (not required)

Model discovery scans common locations:
- `/var/lib/aura/models/` (system-wide)
- `~/.local/share/aura/models/` (per-user)
- `/usr/share/aura/models/` (distro-packaged)

## When No Model Is Available

AURA Core remains fully operational:
- Security monitoring active
- System health and service management work
- Command engine can perform safe built-in operations
- UI shows "AI unavailable" status
- No crash, no hang, no dependency loop

## Privacy Guarantees

- Conversation data stays local by default
- Memory engine stores user-approved preferences only
- No telemetry, no phoning home
- Cloud consent dialog shows exactly what data will be sent
- Users can inspect and delete all memory/conversation data

## Current Status

Phase 2 (intelligence engine) is pending. The configuration keys exist
(`[intelligence]` section in `/etc/bright-os/aura/aura.conf`), and the
mode defaults to "local" with provider "none" when no backend is available.
