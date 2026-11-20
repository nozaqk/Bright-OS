# Bright OS

**An independent, Linux-based hybrid desktop operating system** for developers, programmers, electronics engineers, and technical professionals — built on Debian Linux with an original desktop environment called Bright Desktop.

> **Status: Alpha 0.1 "Dawn"** — Early development release. The build system and
> installer are fully configured (**876 automated tests pass, 0 failures across
> 12 test suites**). Package architecture is cleanly separated into Core, Desktop-Plasma,
> and Desktop-Lite.
> 
> **No genuine ISO has been boot-tested yet** — see [docs/BUILDING.md](docs/BUILDING.md) for
> exact build and test reproduction steps. ISOs must be built locally on a Debian 12/13
> machine with network access to Debian package repositories (deb.debian.org).
> Boot testing in QEMU (BIOS + UEFI) and on real hardware is the next milestone.

## Download

Pre-built ISO images are published to **[GitHub Releases](https://github.com/nozaqk/Bright-OS/releases)**
when a version tag is built and released. If no release is available yet, build from source (see below).

| Edition | Description |
|---------|-------------|
| 🏠 **Home** | Bright Desktop with friendly layout for everyday users (bottom dock, productivity apps) |
| 💻 **Developer** | Bright Desktop with developer layout (side dock, terminal, dev tools, electronics apps) |
| 🪶 **Lite** | Bright Desktop with lightweight profile for older hardware (bottom panel, no dock, reduced animations) |

All three editions share the same **Bright Design System** — brand identity, colors, typography, icon style, and window appearance are consistent across editions. Only the layout, default applications, and performance settings differ.

After downloading, verify the checksum:
```bash
sha256sum -c SHA256SUMS --ignore-missing
```

> **Note:** Alpha releases have static configuration validation but no built ISO has yet
> been boot-tested. When building from source, always test in QEMU first before installing
> to physical hardware.

![Bright OS](branding/icons/bright-os-logo.svg)

## Build from Source

Bright OS is built locally on a Debian Linux machine (see [docs/BUILDING.md](docs/BUILDING.md)).

### Requirements

- **OS:** Debian 12 (Bookworm) or later; Debian 13 (Trixie) recommended
- **Architecture:** x86_64 / amd64
- **RAM:** 4 GB minimum, 8 GB recommended
- **Disk:** 20 GB free space minimum (30+ GB for all three editions)
- **Windows:** Not directly supported; use a Debian Linux virtual machine
- **macOS:** Not supported; use a Debian Linux virtual machine

### Quick Start

```bash
# 1. Set up build environment (installs dependencies)
./build/scripts/setup-build-env.sh

# 2. Build one edition
./build/scripts/build.sh home         # Home edition (KDE Plasma)
./build/scripts/build.sh developer    # Developer edition
./build/scripts/build.sh lite         # Lite edition (LXQt)

# Or build all three editions at once
./build/scripts/build-all.sh

# 3. Validate the ISO
./build/scripts/validate-iso.sh build/output/home/bright-os-0.1.0-alpha-home-amd64.iso

# 4. Publish a release (after building all three editions)
./build/scripts/publish-release.sh 0.1.0-alpha
```

For complete instructions, see [docs/BUILDING.md](docs/BUILDING.md).

## Editions

All three editions are members of one Bright OS family — they share the same logo, color palette (blue-violet accent on dark/light Slate), typography (DejaVu Sans), icon style (Breeze), window chrome, GRUB/Plymouth branding, settings design, and wallpaper set. Only the panel arrangement, dock layout, default applications, and animation levels differ.

| Edition | Layout | Default Apps | RAM Target |
|---------|--------|-------------|-----------|
| **Home** | Top panel + bottom-centered dock; full animations | Firefox, Thunderbird, LibreOffice, VLC, Files, Terminal, Settings, Software Center | 4–8 GB |
| **Developer** | Top panel + left side dock; snappy animations; CPU/Mem metrics in panel | Firefox, Terminal, Code, Git, VMs, Docker, KiCad, Arduino, Wireshark, System Monitor | 8–16 GB |
| **Lite** | Compact bottom panel + menu launcher (no dock); no animations; smaller icons/cursors | Firefox, Files (pcmanfm-qt), Terminal (qterminal), Text Editor, Calculator, Archiver | 2–4 GB |

### Shared Bright Design System

The Bright Desktop uses a centralized design system (`desktop/shell/design/DesignTokens.js`) defining:
- **Color tokens** for dark and light themes (Slate-based with blue-violet brand accent `#3b82f6`)
- **Typography scale** (DejaVu Sans UI / Hack monospace)
- **Spacing, corner radii, shadows** consistent across all components
- **Component sizing** for panels, docks, dialogs, and launcher grids
- **Animation tokens** (disabled entirely for Lite edition)

Edition profiles (`desktop/shell/profiles/EditionProfiles.js`) define per-edition dock apps, launcher categories, panel positions, dock icon sizes, and resource-saving settings — all referencing the shared design tokens.

## Features (Alpha 0.1)

- ✅ Debian Linux 13 (Trixie) base
- ✅ Bootable live ISO (UEFI + BIOS/hybrid support via GRUB)
- ✅ Calamares installer for disk installation (partitioning, users, bootloader)
- ✅ Wayland graphical desktop using KWin + custom multi-window Bright Shell
- ✅ Separate panel, dock, wallpaper, launcher, and notification windows
- ✅ Plymouth boot splash with animated spinner (Bright branded)
- ✅ Original dark and light themes with gradient wallpapers (4K SVG)
- ✅ GRUB boot menu with Bright OS branding and multiple boot options
- ✅ Bright Terminal (real PTY-based terminal emulator with tabs)
- ✅ Bright Files (file manager with sidebar, grid, context menu)
- ✅ Bright Settings (appearance, display, network, sound, power, about)
- ✅ Bright Monitor (live process list with kill, CPU/RAM/disk/network)
- ✅ Bright Control Center (firewall, users, services management)
- ✅ Bright Launcher (standalone app launcher reading .desktop files)
- ✅ Bright Update Manager (GUI for APT updates with pkexec)
- ✅ Bright Store (application marketplace for APT/Flatpak)
- ✅ Network management (NetworkManager + plasma-nm)
- ✅ Sound (PipeWire + WirePlumber + PulseAudio compatibility)
- ✅ Firewall (firewalld with secure defaults)
- ✅ Kernel hardening (sysctl settings: KASLR, kptr_restrict, Yama ptrace)
- ✅ Wine integration with prefix management scripts
- ✅ Flatpak support (Flathub pre-configured on first boot)
- ✅ APT package management with secure defaults
- ✅ Systemd-based init with all required services
- ✅ Qt6ct system-wide theme configuration
- ✅ Clean shutdown/reboot/suspend/logout/lock from power menu
- ✅ Keyboard shortcuts (Super, Super+T/E/S/L, etc.)
- ✅ First-boot setup service
- ✅ Three distinct desktop profiles (Home, Developer, Lite) sharing one unified Bright brand identity
- ✅ Centralized Bright Design System (colors, typography, spacing, radii, animations)
- ✅ Automatic edition detection at startup from /etc/bright-os/edition
- ✅ Profile-aware dock, launcher, panel layout, and quick settings
- ✅ Graceful handling of missing optional applications across editions
- ✅ Lite edition optimizations: reduced animations, basic Qt render loop, smaller UI, lighter fallback apps
- ✅ Light and dark themes that respect design tokens consistently
- ✅ Edition-aware About dialog showing correct edition name and tagline
- ✅ Calamares installer with correct module ordering for Debian Trixie
- ✅ UEFI + Legacy BIOS boot support; safe EFI partition reuse; dual-boot compatible
- ✅ LUKS2 full-disk encryption (no deprecated keyscript; GRUB cryptodisk enabled)
- ✅ SDDM display manager auto-configuration (Bright Desktop as default session)
- ✅ Robust first-boot service (idempotent, non-blocking, runs once before login)
- ✅ Post-installation script removes live packages, regenerates initramfs, configures GRUB
- ✅ fstrim.timer for SSD TRIM (instead of continuous discard mount option)
- ✅ Installer documentation: [docs/INSTALLER.md](docs/INSTALLER.md)

## Quick Start: Building the ISO

### Requirements
- Debian 12 (Bookworm) or 13 (Trixie) amd64 build machine (Trixie recommended)
- 4+ GB RAM (8+ GB recommended), 20+ GB free disk space (30+ GB for all editions)
- Internet connection

```bash
# Install build dependencies
sudo apt-get install -y \
    live-build debootstrap squashfs-tools xorriso \
    isolinux syslinux-efi grub-pc-bin grub-efi-amd64-bin \
    mtools dosfstools

# Build Home edition
git clone https://github.com/nozaqk/Bright-OS.git
cd Bright-OS
./build/scripts/build.sh home

# Result: build/output/home/bright-os-0.1.0-alpha-home-amd64.iso
```

For detailed build instructions, see [docs/BUILDING.md](docs/BUILDING.md).

### Creating a Bootable USB

```bash
sudo dd if=build/output/home/bright-os-0.1.0-alpha-home-amd64.iso \
    of=/dev/sdX bs=4M status=progress conv=fsync
```

### Testing in QEMU

```bash
qemu-system-x86_64 \
    -cdrom build/output/home/bright-os-0.1.0-alpha-home-amd64.iso \
    -m 4G -enable-kvm -cpu host -smp 4 -vga virtio
```

## Installing onto Existing Debian

If you already run Debian 12 and want to try Bright Desktop without building an ISO:

```bash
sudo ./build/scripts/install-bright-os.sh --edition home
```

Then log out and select "Bright Desktop" from your display manager's session menu.

## Repository Structure

```
Bright-OS/
├── boot/                    # Bootloader configuration (GRUB)
├── build/
│   ├── live-build/          # Debian live-build auto scripts
│   ├── scripts/             # Build, install, and validation scripts
│   └── configs/             # Build configuration templates
├── config/                  # live-build config tree (package lists, hooks, includes)
├── kernel/                  # Kernel configuration (future: custom kernel patches)
├── system/
│   ├── services/            # systemd units and system services
│   ├── security/            # Firewall, sysctl hardening, security policies
│   └── networking/          # NetworkManager and network configs
├── desktop/
│   ├── shell/               # Bright Desktop Shell (QML + Python/Qt6)
│   ├── dock/                # Dock component
│   ├── launcher/            # Application launcher
│   ├── widgets/             # Desktop widgets
│   └── themes/              # Dark/light theme definitions
├── applications/
│   ├── bright-files/        # File manager
│   ├── bright-settings/     # System settings
│   ├── bright-terminal/     # Terminal emulator
│   ├── bright-monitor/      # Task manager / system monitor
│   ├── bright-control-center/ # System administration
│   ├── bright-launcher/     # Standalone launcher
│   ├── bright-update/       # Update manager
│   └── bright-store/        # Application store
├── compatibility/
│   ├── wine/                # Wine integration scripts
│   └── proton/              # Proton gaming integration
├── editions/
│   ├── home/                # Home edition package lists
│   ├── developer/           # Developer edition package lists
│   └── lite/                # Lite edition package lists
├── branding/
│   ├── wallpapers/          # Desktop wallpapers (SVG)
│   ├── icons/               # Icons and logos
│   ├── boot/                # Boot artwork
│   └── plymouth/            # Boot splash theme
├── installer/               # Calamares installer configuration
├── packages/                # Debian packaging for Bright OS components
├── tests/                   # Test scripts
├── docs/                    # Documentation
├── LICENSE                  # GNU GPL v3
└── README.md                # This file
```

## Technology Stack

| Component | Technology |
|-----------|-----------|
| Base Distribution | Debian Stable (Bookworm) |
| Kernel | Linux (Debian kernel) |
| Architecture | x86-64 |
| Bootloader | GRUB 2 (UEFI + BIOS) |
| Init System | systemd |
| Display Server | Wayland (with XWayland) |
| Compositor | KWin |
| UI Framework | Qt 6 + QML |
| Programming | Python (PyQt6), C++ (future), QML, Bash |
| Packages | APT + Flatpak |
| Windows Compatibility | Wine |
| Gaming | Proton (via Wine/Steam) |
| Build System | Debian live-build |
| Installer | Calamares (in progress) |

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Super` | Open/close launcher |
| `Super+T` | Open terminal |
| `Super+E` | Open file manager |
| `Super+S` | Open settings |
| `Super+L` | Lock screen |
| `Ctrl+Shift+T` | New terminal tab |
| `Alt+F2` | Open launcher |
| `Esc` | Close overlays |

## Development Roadmap

- **Phase 0 (DONE):** Repository audit, project structure
- **Phase 1 (IN PROGRESS):** Debian live-build foundation, bootable ISO
- **Phase 2:** Complete branding (Plymouth, GRUB theme, cursor theme)
- **Phase 3:** Bright Desktop refinements (window management, widgets, multi-monitor)
- **Phase 4:** System application polish
- **Phase 5:** Wine/Proton integration and compatibility database
- **Phase 6:** Bright Store with full APT/Flatpak management
- **Phase 7:** Edition optimization and testing
- **Phase 8:** Calamares installer integration, recovery mode
- **Phase 9:** Hardware testing, performance optimization, security audit
- **Phase 10:** Bright OS 1.0 release

## Contributing

This is an active open-source project. Contributions welcome:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## Security

Bright OS includes:
- Firewalld with secure defaults (deny incoming, allow outgoing)
- Kernel hardening sysctls (KASLR, kptr_restrict, Yama ptrace scope)
- Network hardening (no source routing, no ICMP redirects)
- PolicyKit for privilege escalation (no running graphical apps as root)
- Package signature verification (APT GPG)
- sudo group-based administration

## License

Bright OS is free software licensed under the **GNU General Public License v3**. See [LICENSE](LICENSE) for the full text.

Individual applications and components may be under compatible free software licenses. All original Bright OS code is GPL v3.

---

**Bright OS** — Linux for developers & makers.
