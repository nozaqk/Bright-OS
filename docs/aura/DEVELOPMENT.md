# AURA Development Guide

## Source Layout

```
aura/
├── core/           # Core service, config, logging, component manager
│   ├── __init__.py
│   ├── config.py           # Configuration parser
│   ├── logger.py           # Structured logging
│   ├── components.py       # Component lifecycle manager
│   └── aura_core_service.py # D-Bus service and main()
├── intelligence/   # AI provider abstraction  [Phase 2]
├── commands/       # Task planning & execution [Phase 3]
├── security/       # Security monitoring       [Phase 4]
├── memory/         # User memory               [Phase 5]
├── recovery/       # Backup & recovery         [Phase 5]
├── api/            # Public API definitions    [Phase 1-6]
└── tests/          # Automated tests
```

## Running Tests

```bash
# AURA Core tests
bash aura/tests/test-aura-core.sh

# Full repository test suite
for t in tests/test-*.sh aura/tests/test-*.sh; do
    bash "$t"
done
```

## Running the Service Manually (for development)

```bash
# Install dependencies (on Debian Trixie)
sudo apt install python3-dbus python3-gi python3-yaml

# Run in foreground (no install needed; uses source tree)
sudo mkdir -p /var/lib/aura /var/log/aura /etc/bright-os/aura
sudo useradd -r -s /usr/sbin/nologin -d /var/lib/aura aura 2>/dev/null || true
sudo chown aura:aura /var/lib/aura /var/log/aura

# As root (for D-Bus registration testing):
sudo python3 aura/core/aura_core_service.py --foreground --config-dir config/includes.chroot/etc/bright-os/aura

# Without D-Bus (headless, for smoke tests):
python3 -c "
import sys; sys.path.insert(0, '.')
from aura.core.aura_core_service import *
"  # will print warnings about missing D-Bus but should not crash
```

## Adding a New Component

1. Create a file in the appropriate subsystem directory (e.g. `aura/security/engine.py`)
2. Subclass `Component` from `aura.core.components`
3. Implement `start()`, `stop()`, and optionally `health_check()`
4. Register the component in `aura_core_service.py` main()
5. Add tests
6. Register any D-Bus methods on the `AURAService` class

## Coding Style

- Python 3, PEP 8
- No external dependencies beyond python3-dbus, python3-gi, python3-yaml in core
- Structured logging via `logging.getLogger("aura.<subsystem>")`
- All errors must be caught at component boundaries (never crash the service)
- No `shell=True` in subprocess calls
- All user-facing strings go through the logging/D-Bus interface, not print()

## D-Bus API Conventions

- Method names: CamelCase
- Signals: CamelCase
- Properties: use methods (Get/Set) for Phase 1; switch to properties later
- Dictionary returns: use `a{sv}` (string → variant) for extensibility
- Always include error strings in returns; don't raise uncaught exceptions to D-Bus

## Phase Status

- Phase 1 (Core): COMPLETE — service, D-Bus, systemd, config, tests
- Phase 2-8: PENDING — see ARCHITECTURE.md for details

## Testing the Intelligence Engine

The intelligence engine unit tests run without any model weights and
without llama.cpp installed, using mocked providers:

```bash
python3 -m unittest discover -s aura/tests -p 'test_*.py' -v
```

Key design rules enforced by tests:
- Models MUST NOT be loaded at boot (even when a default model is set).
- DISABLED components must stay DISABLED (regression for Phase 1 bug).
- Shutdown() must quit the active GLib mainloop (regression for Phase 1 bug).
- Idle models must be unloaded after the configured threshold.
- Cloud calls must be denied unless the mode is hybrid AND consent is given.
- API key files must have mode 0600 or be refused.
- Memory assessment must reject models larger than available RAM.
- Cancellation must interrupt in-flight requests.

### Adding a new provider

1. Subclass `aura.intelligence.provider.Provider`.
2. Implement `check_available`, `is_model_compatible`, `load_model`,
   `unload_model`, `generate`, and `estimated_memory_for`.
3. Honor `request.cancel` in your generate loop for graceful cancellation.
4. Never call the network from a provider marked `local = True`.
5. Never shell out with user-generated input.
6. Register your provider in `InferenceEngine._register_default_providers`.
