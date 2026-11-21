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
