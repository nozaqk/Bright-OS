# AURA Installation

AURA is installed automatically as part of Bright OS. No manual installation is required.

## What Gets Installed

### Packages (from `aura-core.list.chroot`)
- `python3`, `python3-dbus`, `python3-gi`, `python3-yaml` — runtime
- `dbus`, `systemd`, `policykit-1` — service infrastructure
- `auditd`, `apparmor`, `nftables`, `inotify-tools` — security engine prerequisites

### Files
- `/usr/bin/aura-core-service` — service entry point
- `/usr/lib/aura/` — Python modules
- `/etc/systemd/system/aura-core.service` — systemd unit
- `/etc/dbus-1/system.d/org.bright_os.AURA.conf` — D-Bus policy
- `/etc/bright-os/aura/aura.conf` — configuration
- `/etc/aura/sysusers.d/aura.conf` — user/group creation
- `/etc/aura/tmpfiles.d/aura.conf` — directory permissions
- `/var/lib/aura/` — state directory (mode 0750, owned by `aura:aura`)
- `/var/log/aura/` — log directory (mode 0750, owned by `aura:adm`)

### Service User
- Username: `aura`
- Shell: `/usr/sbin/nologin`
- Home: `/var/lib/aura`
- Group: `aura`
- No login, no sudo, no special capabilities

## Service Management

```bash
# Check status
systemctl status aura-core

# View logs
journalctl -u aura-core -f

# Restart
sudo systemctl restart aura-core

# Stop
sudo systemctl stop aura-core
```

## Configuration

Edit `/etc/bright-os/aura/aura.conf` and restart the service.

Key settings:
- `[intelligence] mode`: `local` (default), `hybrid`, `offline`
- `[security] auto_isolate`: `false` (default), `true` (opt-in autonomous containment)
- `[core] log_level`: `debug`, `info`, `warning`, `error`

## Installing AI Models (Optional)

AURA works without AI models. To enable local AI, place GGUF model files in:
- `/var/lib/aura/models/` (system-wide, requires root)
- `~/.local/share/aura/models/` (per-user)

Or install Ollama separately if desired. Model installation is handled via the AURA Command Center UI (Phase 6).

## Uninstalling (for testing)

AURA is a core Bright OS subsystem. It cannot be removed without breaking the desktop integration. To disable temporarily:

```bash
sudo systemctl stop aura-core
sudo systemctl disable aura-core
```

## Troubleshooting

**Service fails to start**: Check logs with `journalctl -u aura-core -n 50`. Common causes:
- D-Bus configuration not installed (run `sudo systemctl reload-dbus`)
- `aura` user missing (run `systemd-sysusers /etc/aura/sysusers.d/aura.conf`)
- Permissions wrong on `/var/lib/aura` (run `systemd-tmpfiles --create`)

**D-Bus calls denied**: Check `/etc/dbus-1/system.d/org.bright_os.AURA.conf` is present and dbus was reloaded.

**AI features not available**: Check `GetAIMode()` via D-Bus; no model may be installed. This is normal.

## Current Status

Phase 1 provides the core service infrastructure. Phases 2-6 add intelligence, commands, security, memory, and desktop UI. The service runs on every Bright OS boot regardless of AI availability.
