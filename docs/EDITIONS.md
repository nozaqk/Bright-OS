# Bright OS Editions

All three editions of Bright OS share the same **Bright Design System** — logo, colors, typography, window chrome, and system identity. They differ only in desktop layout, default applications, and performance tuning.

## Home Edition

**Target:** Everyday users, general-purpose computing, families, productivity.

**Layout:**
- Top panel (40px) with launcher button, clock, system tray
- Bottom-centered rounded-pill dock (48px icons)
- Full animations and visual effects
- Dark theme default with gradient wallpaper

**Default Applications (Dock):**
Firefox, Files, Thunderbird, LibreOffice Writer, Terminal, VLC, Settings, Software Center

**Launcher Grid (15 apps):**
Firefox, Files, Settings, Thunderbird, Software Center, LibreOffice, VLC, GIMP, Calculator, Text Editor, Terminal, System Monitor, Updates, Calendar, About

**Launcher Categories:** All Apps, Web, Office, Media, Graphics, Utilities, System

**System Requirements:**
- 4 GB RAM minimum, 8 GB recommended
- 20 GB disk space
- 64-bit x86 processor (2+ cores)
- Any GPU with basic OpenGL support

## Developer Edition

**Target:** Software developers, electronics engineers, system administrators, technical professionals.

**Layout:**
- Top panel (36px, more compact) with workspace indicator and live CPU/Memory metrics
- Left side dock (40px icons) for developer tools
- Snappy animations (0.7× speed)
- Dark theme default

**Default Applications (Dock):**
Firefox, Terminal, Files, Code Editor, Git, Virtual Machine Manager, Docker, System Monitor, KiCad, Arduino, Settings

**Launcher Grid (15 apps):**
Terminal, Code Editor, Files, Firefox, Git, Virtual Machines, Docker, KiCad, Arduino, Serial Terminal, Wireshark, Calculator, Settings, About

**Launcher Categories:** All Apps, Development, Electronics, Web, System, Utilities

**Developer Extras:**
- Live CPU/Memory percentage in panel
- Workspace indicator (4 workspaces default)
- Electronics tools: KiCad, Arduino, sigrok/pulseview, esptool
- Development: build-essential, GCC/Clang, CMake, Python/Node.js/Java, Qt 6 dev, Docker, QEMU/KVM, Wireshark, nmap, valgrind, strace

**System Requirements:**
- 8 GB RAM minimum, 16 GB recommended
- 30+ GB disk space (development tools are large)
- 64-bit x86 multi-core processor
- Virtualization support (VT-x/AMD-V) recommended for VMs

## Lite Edition

**Target:** Older computers, low-spec hardware (2-4 GB RAM, single/dual-core CPUs, netbooks).

**Layout:**
- Bottom panel (28px, compact) with menu button and quick-launch icons
- No dock (reduces memory usage and screen clutter)
- All animations disabled
- Smaller cursor (16px), smaller UI fonts
- Dark theme default with lighter rendering path

**Panel Quick Launch:**
Menu, Firefox, Files (pcmanfm-qt), Terminal (qterminal), Settings

**Launcher Grid (10 apps, essentials only):**
Firefox, Files, Terminal, Text Editor (FeatherPad), Calculator (galculator), Settings, System Monitor (qps), MPV, Archiver (Engrampa), About

**Launcher Categories:** All Apps, Internet, System, Tools, Media

**Performance Optimizations:**
- Qt Quick Controls Basic style (no Material/Fusion overhead)
- Basic Qt Scene Graph render loop
- Slower system monitor polling (10s vs 5s)
- Smaller icons, panels, cursors
- No compositing effects on X11 (Picom with minimal config if enabled)
- Openbox as X11 window manager fallback
- Lighter default applications (no LibreOffice, no KDE apps beyond essentials)
- LXQt components used instead of full Plasma desktop stack

**Lite-specific Package Differences:**
- No `plasma-desktop` or `plasma-workspace`
- Uses LXQt + Openbox instead of full Plasma
- AbiWord + Gnumeric instead of LibreOffice
- mpv instead of VLC, pcmanfm-qt instead of Dolphin
- qterminal instead of Konsole/better terminals
- FeatherPad instead of KWrite/Kate
- Engrampa instead of Ark/File-Roller

**System Requirements:**
- 2 GB RAM minimum, 4 GB recommended
- 15 GB disk space
- 64-bit or 32-bit x86 processor (64-bit build only currently)
- Basic GPU (no compositing effects needed)

## Switching Editions

The edition is set at build time by writing to `/etc/bright-os/edition`. It is possible to manually change the edition after installation by editing this file and logging out, but note that:
- Edition-specific packages (e.g. LibreOffice on Home, KiCad on Developer) will not be automatically installed
- Lite-specific optimizations (render loop, compositor settings) are applied at session startup
- User settings in `~/.config/bright-os/shell.conf` can override individual properties like `panel_height`, `dock_icon_size`, `animations`, and `theme` regardless of edition

## Design Consistency Guarantees

Across all three editions, the following are always identical:
- Bright OS sun logo (blue-violet gradient circle with rays)
- Color palette (brand blue `#3b82f6`, indigo, violet; dark `#0a0e1a`/light `#f8fafc` bases)
- Typography (DejaVu Sans UI, Hack monospace)
- Window appearance (rounded corners, semi-transparent panels, Breeze cursor)
- Icon style (Breeze icon theme)
- GRUB boot menu theme
- Plymouth boot splash
- Wallpaper set (dark + light SVG gradients)
- Settings application design
- Calamares installer branding
- About dialog design
- Notification center and power menu appearance
- Keyboard shortcuts
