# Bright OS

**An independent, Linux-based hybrid desktop operating system** for developers, programmers, electronics engineers, and technical professionals — built on Debian Linux with an original desktop environment called Bright Desktop.

> **Status: Alpha 0.1 "Dawn"** — Early development release. The build system is
> fully configured and validated (**326 automated tests pass**). Package architecture
> is cleanly separated into Core (169 packages), Desktop-Plasma (37 packages for
> Home/Developer), and Desktop-Lite (29 packages for Lite).
> The ISO must be built on a Debian 13 Trixie machine per the instructions below.
> Boot testing is pending the first ISO build.

![Bright OS](branding/icons/bright-os-logo.svg)

## Editions

| Edition | Description | RAM Target |
|---------|-------------|-----------|
| **Home** | Complete desktop for everyday use | 8 GB |
| **Developer** | Full toolchain for software & electronics | 16 GB |
| **Lite** | Lightweight edition for older hardware | 4 GB (2 GB experimental) |

All editions share the same codebase, system services, and Bright Desktop technology.

## Features (Alpha 0.1)

- ✅ Debian Linux 12 (Bookworm) base
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
- ✅ Three edition configurations (Home, Developer, Lite)

## Quick Start: Building the ISO

### Requirements
- Debian 12 (Bookworm) amd64 build machine
- 4+ GB RAM, 15+ GB free disk space
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
