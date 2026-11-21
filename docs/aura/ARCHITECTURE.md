# AURA Architecture

AURA (Assistant for Understanding, Response, and Action) is Bright OS's native intelligence and cybersecurity subsystem.

## Design Principles

1. **Offline-first**: AURA Core operates without internet and without AI models loaded.
2. **Least privilege**: The core service runs as the dedicated `aura` system user, not root.
3. **Fail-safe**: AURA component failures do not crash Bright OS.
4. **User consent**: Cloud AI access, privileged commands, and autonomous actions require explicit user approval.
5. **Evidence-based security**: Security detections use behavioural rules and system evidence, not AI opinion.
6. **No model bundling**: Large AI model weights are NOT included in the ISO; users install them on demand.

## Component Layout

```
aura/
├── core/                # Service manager, config, logging, D-Bus interface
├── intelligence/        # AI engine (Phase 2):
│   ├── provider.py      #   Abstract provider interface
│   ├── providers/       #   llama.cpp, Ollama (optional), cloud (HTTPS)
│   ├── inference.py     #   InferenceEngine (top-level coordinator)
│   ├── model_manager.py #   Model discovery and user-initiated downloads
│   ├── model_info.py    #   GGUF validation, memory estimation
│   ├── resource_manager.py # Adaptive RAM/CPU/battery policy (mandatory)
│   ├── mode_manager.py  #   local / hybrid / offline mode switching
│   ├── conversation.py  #   Per-conversation history + context truncation
│   ├── hardware.py      #   RAM/CPU/GPU/battery/storage detection
│   ├── health.py        #   Provider health monitor
│   ├── secure_store.py  #   API-key storage (no plaintext in config)
│   └── editions.py      #   Home / Developer / Lite edition profiles
├── commands/            # Task planning, permissions, restricted execution [Phase 3]
├── security/            # Behavioural monitoring and controlled protection  [Phase 4]
├── memory/              # User-controlled local memory                       [Phase 5]
├── recovery/            # Backup, integrity checks, safe rollback           [Phase 5]
├── api/                 # Public D-Bus API definitions                       [Phase 1]
└── tests/               # Automated tests
```

## System Integration

| Component | Path | Purpose |
|-----------|------|---------|
| Systemd unit | `/etc/systemd/system/aura-core.service` | Service activation, hardening |
| D-Bus config | `/etc/dbus-1/system.d/org.bright_os.AURA.conf` | Bus policy and permissions |
| D-Bus API | `org.bright_os.AURA` `/org/bright_os/AURA` | Service interface |
| Configuration | `/etc/bright-os/aura/aura.conf` | Admin-editable settings |
| State data | `/var/lib/aura/` | Backups, models, runtime state |
| Logs | `/var/log/aura/aura.log` + journal | Structured logging |
| Sysusers | `/etc/aura/sysusers.d/aura.conf` | Creates `aura` user/group |
| Tmpfiles | `/etc/aura/tmpfiles.d/aura.conf` | Creates state/log directories |
| Install hook | `config/hooks/live/40-aura-setup.hook.chroot` | Live-build chroot installation |
| Package list | `config/package-lists/aura-core.list.chroot` | Core Debian dependencies |
| Executable | `/usr/bin/aura-core-service` | Service entry point |
| Python modules | `/usr/lib/aura/` | All AURA Python packages |

## Service Hardening

The systemd unit applies the following restrictions to the AURA process:

- `NoNewPrivileges=yes`
- `PrivateTmp=yes`
- `PrivateDevices=yes`
- `ProtectSystem=strict`
- `ProtectHome=read-only`
- `ProtectKernelTunables=yes`, `ProtectKernelModules=yes`, `ProtectControlGroups=yes`
- `RestrictNamespaces=yes`, `RestrictRealtime=yes`, `LockPersonality=yes`
- `CapabilityBoundingSet=` (empty — no capabilities)
- `ReadWritePaths=/var/lib/aura /var/log/aura` only

## D-Bus Interface

### Methods

| Method | Signature | Description |
|--------|-----------|-------------|
| `GetVersion()` | → `s` | Return AURA version string |
| `GetStatus()` | → `s` | Return overall service status ("running") |
| `GetServiceInfo()` | → `a{sv}` | Version, uptime, PID, user |
| `ListComponents()` | → `as` | List all registered component names |
| `GetComponentStatus(s)` | name → `a{sv}` | Get state/restart info for one component |
| `GetAllComponentStatus()` | → `a{sa{sv}}` | Status of all components |
| `IsComponentHealthy(s)` | name → `b` | Quick health check |
| `GetAIMode()` | → `s` | Current AI mode ("local"/"hybrid"/"offline") |
| `SetAIMode(s)` | mode → `b` | Change AI mode (no reinstall needed) |
| `ListAIModels()` | → `aa{sv}` | List locally available models and their metadata |
| `ListAIProviders()` | → `aa{sv}` | List providers and their current state |
| `GetActiveAIProvider()` | → `s` | Name of currently active provider |
| `GetLoadedModel()` | → `s` | Model ID currently loaded (or "") |
| `LoadAIModel(s)` | model_id → `b` | Load a model (subject to resource policy) |
| `UnloadAIModel()` | → | Unload the currently loaded model |
| `GetHardwareSuitability(s)` | model_id → `a{sv}` | Check if a model fits on current hardware |
| `GetResourceUsage()` | → `a{sv}` | Current RAM/CPU/battery snapshot |
| `GetInferenceStatus()` | → `a{sv}` | Active requests / loaded model |
| `CancelInference(s)` | request_id → `b` | Cancel a running inference |
| `CancelAllInference()` | → | Cancel all in-flight requests |
| `GrantCloudConsent(b)` | granted → `b` | Grant/revoke consent for hybrid cloud calls |
| `Shutdown()` | → | Request clean shutdown (requires auth) |

### Signals

| Signal | Signature | Description |
|--------|-----------|-------------|
| `ComponentStateChanged` | `ssa{sv}` | A component changed state |
| `SecurityAlert` | `sa{sv}` | Security engine detected a threat |
| `AIEvent` | `sa{sv}` | Intelligence event (model_loaded, model_unloaded, inference_*, mode_changed) |

## Lifecycle

1. systemd starts `aura-core.service` as user `aura`
2. Service loads configuration from `/etc/bright-os/aura/aura.conf`
3. Component manager registers all subsystems
4. Components start; watchdog monitors health (5-second poll)
5. Failed components are restarted up to `component_restart_limit` times
6. D-Bus name `org.bright_os.AURA` is claimed
7. Service runs until SIGTERM or Shutdown() call

## Current Implementation Status

- **Phase 1 (Core)**: IMPLEMENTED - systemd service, D-Bus API, config, logging, component manager, security hardening; regression fixes for DISABLED-state race and Shutdown mainloop bug
- **Phase 2 (Intelligence)**: IMPLEMENTED - provider architecture (llama.cpp/Ollama/cloud), adaptive resource manager, three AI modes (local/hybrid/offline), lazy loading, idle unload, battery-aware policy, hardware suitability checks, model validation, secure key storage, conversation manager, provider health monitoring, D-Bus API extensions, edition profiles, privacy controls
- **Phase 3 (Commands)**: Pending
- **Phase 4 (Security)**: Pending
- **Phase 5 (Memory/Recovery)**: Pending
- **Phase 6 (Desktop UI)**: Pending
- **Phase 7 (Editions)**: PARTIAL (edition detection + defaults; full packaging splits pending)
- **Phase 8 (ISO regression)**: PENDING (requires full live-build environment)
