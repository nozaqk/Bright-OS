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
├── core/           # Service manager, config, logging, D-Bus interface
├── intelligence/   # AI provider abstraction (local/hybrid/offline) [Phase 2]
├── commands/       # Task planning, permissions, restricted execution  [Phase 3]
├── security/       # Behavioural monitoring and controlled protection [Phase 4]
├── memory/         # User-controlled local memory                      [Phase 5]
├── recovery/       # Backup, integrity checks, safe rollback          [Phase 5]
├── api/            # Public D-Bus API definitions                      [Phase 1]
└── tests/          # Automated tests
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
| `Shutdown()` | → | Request clean shutdown (requires auth) |

### Signals

| Signal | Signature | Description |
|--------|-----------|-------------|
| `ComponentStateChanged` | `ssa{sv}` | A component changed state |
| `SecurityAlert` | `sa{sv}` | Security engine detected a threat |

## Lifecycle

1. systemd starts `aura-core.service` as user `aura`
2. Service loads configuration from `/etc/bright-os/aura/aura.conf`
3. Component manager registers all subsystems
4. Components start; watchdog monitors health (5-second poll)
5. Failed components are restarted up to `component_restart_limit` times
6. D-Bus name `org.bright_os.AURA` is claimed
7. Service runs until SIGTERM or Shutdown() call

## Current Implementation Status

- **Phase 1 (Core)**: IMPLEMENTED — systemd service, D-Bus API, config, logging, component manager, security hardening
- **Phase 2 (Intelligence)**: Pending
- **Phase 3 (Commands)**: Pending
- **Phase 4 (Security)**: Pending
- **Phase 5 (Memory/Recovery)**: Pending
- **Phase 6 (Desktop UI)**: Pending
- **Phase 7 (Editions)**: Pending
- **Phase 8 (ISO regression)**: Pending
