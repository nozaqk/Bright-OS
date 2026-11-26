# Bright OS — Lightweight Core Dependency Audit (Phase 6.3)

## Audit Date
2026-11-20

## Current Architecture (main branch, post Phase 6.2)

- **Kernel**: linux-image-amd64 + firmware-linux + friends
- **Init**: systemd
- **Display server**: xwayland + xserver-xorg-core (X11 fallback)
- **Display manager**: sddm (KDE's display manager)
- **Default compositor**: kwin-wayland (via `kwin_wayland --exit-with-session=shell`)
- **Shell**: bright-desktop-shell.py (PyQt6/QML)
- **Desktop (Home/Dev)**: plasma-workspace + plasma-desktop + breeze + many KDE apps
- **Desktop (Lite)**: lxqt-core + openbox + picom (still pulls kwin-wayland from core)
- **Audio**: pipewire + wireplumber
- **Installer**: calamares
- **Optional in lite**: Android waydroid, bluetooth, cups are masked

## Dependency Map & Classification

### ESSENTIAL (must remain in default image)
| Package group | Why essential | Notes |
|---|---|---|
| linux-image-amd64 + initramfs-tools | boot | Required for any system |
| firmware-linux* (nonfree, realtek, iwlwifi, atheros, brcm80211) | hardware support | Keep all for USB boot compatibility |
| systemd + dbus + udev | init/IPC/hotplug | Foundation |
| coreutils, bash, apt, sudo, policykit-1 | core CLI | Cannot drop |
| network-manager + iwd + wpasupplicant + iproute2 + firewalld + openssh-client | networking | USB boot + install needs network |
| parted, dosfstools, ntfs-3g, e2fsprogs, xfsprogs, btrfs-progs, udisks2, lvm2, cryptsetup | storage / installer | Required for Calamares |
| xwayland + xserver-xorg-core + mesa-* | display server | Needed for XWayland apps |
| libqt6* + qml6-module-* + python3-pyqt6 | Bright shell runtime | Shell is PyQt6/QML |
| python3 + python3-dbus + python3-gi + python3-apt + python3-yaml + python3-pil | Python runtime | Shell + system tools |
| xdg-user-dirs + xdg-utils + xdg-desktop-portal + xdg-desktop-portal-gtk | XDG integration | App launch / file dialogs |
| pipewire + pipewire-pulse + pipewire-alsa + wireplumber + alsa-utils | Audio | PipeWire is the standard |
| fonts-dejavu + fonts-noto + fonts-hack + fontconfig | Fonts | Required for readable UI |
| breeze-icon-theme + adwaita-icon-theme | Icons | Shell and apps require these |
| calamares + calamares-settings-debian | Installer | Must preserve |
| grub-pc-bin + grub-efi-amd64-bin + grub-common | Bootloader | Required by installer; shim-signed/grub-efi-amd64-signed optional |
| ca-certificates, gnupg, curl, wget | TLS/network | Foundation |
| htop, file-roller, unzip, gzip, xz, zstd, rsync | Utilities | Basic userland |
| udisks2, gvfs + gvfs-backends | Volume mounting | Required for removable media |
| flatpak | App distribution | Core design principle |

### PRUNE / REDUCE (overlapping or heavy; remove from default core)
| Package | Reason | Action |
|---|---|---|
| sddm | Heavy Qt5/KDE DM (~80-120 MB resident) | Replace with greetd + gtkgreet (~5 MB); keep sddm as optional recovery |
| kwin-wayland (in core) | Heavy KDE compositor (~200+ MB) | Move to optional "kwin-recovery" list; default labwc |
| plasma-workspace, plasma-desktop, plasma-nm, plasma-pa | Full Plasma desktop | Remove from default Home; only keep where needed |
| plasma-discover (+backends) | Heavy software store (~150 MB) | Replace with bright-store only |
| breeze, breeze-gtk, kde-config-gtk-style | Full KDE theme engines | Keep only breeze-icon-theme + breeze-cursor-theme |
| sddm-theme-debian-breeze | SDDM theme | Only if sddm retained |
| qt5-style-kvantum, gtk2-engines-murrine, sassc, optipng | Theme engines | Not essential for core shell |
| powerdevil, bluedevil, print-manager | KDE daemons | Replace with lighter alternatives or mask |
| kcalc, kwrite, ark, pavucontrol-qt | KDE apps | Replace with lighter alternatives |
| gnome-disk-utility, partitionmanager, gparted | Duplicate partition tools | Keep only gparted (most feature-complete) |
| linux-headers-amd64 | Only needed for DKMS | Move to optional-dev profile; needed only for binder-dkms (android) |
| plymouth + plymouth-themes + plymouth-label | Boot splash | Optional visual; heavy theme assets |
| man-db, manpages, info | Documentation | Move to optional (save ~30 MB) |
| command-not-found | Heavy Python db lookup | Optional |
| fonts-noto-cjk, fonts-noto-color-emoji, fonts-liberation2 | Large font packages | Keep fonts-noto (covers CJK+emoji+Latin) but drop duplicates; fonts-liberation2 covered by fonts-dejavu |
| cryptsetup-initramfs | Pulls in cryptsetup to initrd | Keep but verify necessary only when encryption is desired (initramfs size) |
| fuseiso | Rarely used FUSE | Optional |
| network-manager-openvpn | VPN plugin | Move to optional-vpn profile |
| neofetch | Trivial demo | Drop or move to optional |
| software-properties-common | Pulls in Python+GTK | Keep (needed by add-apt-repository) but check deps |
| xserver-xorg-video-all | Pulls in many X drivers | Replace with xserver-xorg-video-{amdgpu,intel,modesetting,vesa} only |

### MOVE TO OPTIONAL PROFILES
| Package group | Optional profile name | Notes |
|---|---|---|
| bluez, blueman | bluetooth | Not everyone needs BT |
| cups, cups-filters, printer-driver-all, system-config-printer, print-manager | printing | Printing is optional |
| ModemManager, network-manager-openvpn | networking-extras | WWAN/VPN optional |
| avahi-daemon (if installed) | mdns | Rarely needed |
| waydroid, binder-linux-module-dkms, adb, fastboot | android | Keep as session-activated |
| wine, wine64, winetricks | wine | Windows compat |
| libreoffice-*, thunderbird, gimp, inkscape, audacity, vlc, cheese, gnome-weather, gnome-calendar | apps-home | Home apps as post-install options |
| build-essential, gcc, g++, cmake, qt6-*-dev, default-jdk, nodejs, docker.io, qemu, wireshark, kicad, etc. | developer | Dev edition profile |
| auditd, apparmor-utils | security-extras | Auditd is heavy; apparmor is already enabled by default in systemd |
| linux-headers-amd64 | dev-kernel | Only for DKMS |
| qemu-system-x86, qemu-utils, ovmf | vm | For VM testing/smoke test only |
| shim-signed, grub-efi-amd64-signed | secureboot | Not required for non-SB boot |
| plymouth themes | splash | Boot eye candy |

### MUST PRESERVE (Phase 5 security + AURA/Bright Android)
- AURA Python source tree at /usr/lib/aura (on-demand D-Bus activation only, no boot start)
- Bright Android at /usr/lib/bright-android (session-activated, not started at boot)
- D-Bus policies for AURA and Bright Android
- sysctl.d/99-bright-os-sysctl.conf security hardening
- Firewall defaults firewalld
- PolicyKit configuration
- Calamares installer config
- Live-boot hooks
- The EFI boot hook

## Default Edition Going Forward (Phase 6.3)

A new **"bright"** (default) lightweight profile is added:
- labwc as compositor (default)
- greetd + gtkgreet as display manager
- PyQt6 Bright Shell on Wayland via layer-shell-qt
- PipeWire + WirePlumber
- No KDE Plasma dependencies by default
- KWin + SDDM retained in a `recovery` optional profile
- AURA/Bright Android available on-demand (D-Bus/session activation)
- Calamares installer preserved
- Home/Developer/Lite editions continue to exist as layered profiles

## Targets
- **Idle RAM target**: ~250 MB after 120-second settle (measured in QEMU/KVM with 2 GB RAM, 2 vCPUs, no swap)
- **ISO size target**: keep under 2 GiB; aim for ~1.4-1.6 GiB
- **Package count**: roughly 600-800 packages installed (down from ~1300-1500 in current Home edition)
