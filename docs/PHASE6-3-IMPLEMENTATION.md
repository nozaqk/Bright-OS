# Phase 6.3 — Lightweight Core Architecture: Implementation Summary

## Architectural changes

The default Bright OS desktop is now a lightweight stack:

```
Linux kernel → systemd → greetd + cage + gtkgreet (display manager)
                    → labwc (Wayland compositor, wlroots-based)
                    → Bright Desktop Shell (PyQt6/QML on layer-shell-qt)
                    → PipeWire + WirePlumber (audio)
```

KWin and SDDM are **preserved** as a recovery option via the
`optional-recovery-kwin.list.chroot` package profile; they are no longer
installed by default.

## Files added

- `config/package-lists/optional-bluetooth.list.chroot`
- `config/package-lists/optional-printing.list.chroot`
- `config/package-lists/optional-network-extras.list.chroot` (ModemManager, OpenVPN, Avahi)
- `config/package-lists/optional-wine.list.chroot`
- `config/package-lists/optional-devtools-core.list.chroot`
- `config/package-lists/optional-recovery-kwin.list.chroot` (sddm + kwin-wayland)
- `config/package-lists/optional-secureboot.list.chroot` (shim-signed + signed grub)
- `config/package-lists/optional-plymouth.list.chroot`
- `config/package-lists/optional-qemu.list.chroot`
- `config/includes.chroot/etc/greetd/config.toml`
- `config/includes.chroot/usr/lib/sysusers.d/bright-greeter.conf`
- `config/includes.chroot/usr/lib/tmpfiles.d/bright-greeter.conf`
- `config/hooks/live/15-display-manager.hook.chroot`
- `tests/test-phase6-3-lightweight.sh`
- `docs/PHASE6-3-AUDIT.md` (dependency audit)
- `docs/PHASE6-3-IMPLEMENTATION.md` (this file)

## Files modified

### Package lists
- `config/package-lists/core.list.chroot` — replaced KDE/SDDM/KWin/Plymouth/shim-signed
  defaults with labwc + greetd + cage + wlroots ecosystem; added lightweight
  apps (alacritty, featherpad, pcmanfm-qt, engrampa, xfce4-power-manager, etc.)
- `config/package-lists/desktop.list.chroot` — slim user-app overlay (firefox-esr,
  mpv, viewnior, galculator, transmission, breeze-gtk-theme); no KDE/Plasma deps.
- `config/package-lists/desktop-lite.list.chroot` — reduced to extra low-RAM
  utilities; labwc is now inherited from core so LXQt/Openbox/picom are no longer needed.
- `config/package-lists/aura-core.list.chroot` — trimmed to packages NOT in core;
  restored gir1.2-polkit-1.0.
- `config/package-lists/android.list.chroot` — added linux-headers-amd64 (needed
  by binder DKMS).
- `editions/home/packages.list` — added Bluetooth, Printing, Avahi, OpenVPN,
  Thunderbird, VLC, GIMP, LibreOffice; dropped Wine (moved to optional-wine);
  dropped Android duplicates (still shipped via android.list.chroot).
- `editions/lite/packages.list` — kept minimal; no Bluetooth/Printing/Android.
- `editions/developer/packages.list` — added Bluetooth/Printing/network-extras,
  Secure Boot shim, full dev toolchain.

### Display manager / session
- `config/hooks/live/00-bright-os-branding.hook.chroot` — bright.desktop now
  launches labwc via /usr/bin/bright-desktop-shell; bright-kwin.desktop only
  written when kwin_wayland is present (recovery path).
- `config/hooks/live/10-bright-os-components.hook.chroot` — enables greetd not
  sddm; copies labwc config; enables bluetooth/cups only when present.
- `config/hooks/live/15-display-manager.hook.chroot` (new) — sets greetd as
  default via display-manager.service symlink, disables sddm/lightdm/gdm3 if present.
- `config/includes.chroot/usr/bin/bright-desktop-shell` — rewritten to prefer
  labwc, fall back to kwin_wayland if present, then X11; supports --labwc /
  --kwin / --shell-only flags.
- `desktop/session/bright-desktop-session-labwc.sh` — productionized (no longer
  experimental); uses XDG_CONFIG_DIRS, starts pipewire/wireplumber via systemd --user.
- `desktop/session/labwc/autostart` — updated header comment (now default).

### Build pipeline
- `build/scripts/build.sh` — masks bluetooth/cups/ModemManager/avahi-daemon by
  default (the 10-components hook re-enables them only when installed).
- `installer/calamares/modules/displaymanager.conf` — greetd preferred, SDDM fallback.

### Live boot
- `config/includes.chroot/lib/live/config/05-bright-os` — configures greetd
  autologin; writes SDDM autologin only when SDDM exists.

### Tests (updated for Phase 6.3)
- `tests/test-packages.sh`, `tests/test-live-boot.sh`, `tests/test-installer.sh`,
  `tests/test-build-pipeline.sh`, `tests/test-calamares.sh`,
  `tests/test-labwc-poc.sh`, `tests/test-phase6-2-iso-pipeline.sh` — updated
  assertions from "sddm/kwin default" to "labwc/greetd default + recovery".
- `tests/test-phase6-3-lightweight.sh` (new) — covers 75 architectural assertions.
- `aura/tests/test_phase3_integration.py`, `aura/tests/test_phase32_runtime.py`
  — accept packages from core.list.chroot as well as aura-core.list.chroot.

### Sync
- AURA and Bright Android packaged Python files in `config/includes.chroot/usr/lib/`
  are re-synced with source trees.

## Packages removed from the default (core) image

| Package | Reason |
|---|---|
| `sddm`, `sddm-theme-debian-breeze` | Heavy Qt5/KDE DM; replaced by greetd+gtkgreet (~5 MB vs ~120 MB) |
| `kwin-wayland` | Heavy KDE compositor (~200+ MB); replaced by labwc (~50 MB total including wlroots) |
| `shim-signed`, `grub-efi-amd64-signed` | Needed only for Secure Boot; optional-secureboot |
| `plymouth`, `plymouth-themes`, `plymouth-label` | Boot eye candy; optional-plymouth |
| `genisoimage`, `syslinux-efi` | Redundant with xorriso + GRUB EFI |
| `btrfs-progs` (kept), but `fuseiso`, `man-db/manpages/info` (kept man-db), `command-not-found`, `linux-headers-amd64`, `neofetch`, `gnome-disk-utility`/`partitionmanager` (kept gparted), `network-manager-openvpn`, `network-manager-gnome` wait — network-manager-gnome is IN | |
| `plasma-*`, `breeze(-gtk)`, `kde-config-gtk-style*`, `powerdevil`, `bluedevil`, `print-manager`, `plasma-discover(+backends)`, `kcalc`, `kwrite`, `ark`, `qt5-style-kvantum`, `gtk2-engines-murrine`, `sassc`, `optipng`, `volumeicon-alsa` | KDE/Plasma components; not needed for Bright Shell |
| `xserver-xorg-video-all` | Replaced with minimal set (-amdgpu, -intel); -modesetting is in -core |

## Packages moved into optional profiles

| Feature | Profile | Status |
|---|---|---|
| Bluetooth | optional-bluetooth | Masked by default; enabled only when installed |
| Printing (CUPS) | optional-printing | Masked by default |
| VPN/WWAN/mDNS | optional-network-extras | Masked by default |
| Wine/Proton | optional-wine | Not installed by default |
| Build/debug/electronics/dev tools | optional-devtools-core | Developer edition only |
| KWin + SDDM recovery | optional-recovery-kwin | Recovery path preserved |
| Secure Boot (shim + signed GRUB) | optional-secureboot | For SB-enabled firmware |
| Plymouth boot splash | optional-plymouth | Eye candy |
| QEMU/OVMF | optional-qemu | For VMs/testing only |

## Dependency & recovery-path findings

- **KWin + SDDM recovery is preserved**: installing `optional-recovery-kwin.list.chroot`
  restores the full KWin/SDDM session; the 15-display-manager hook prefers
  greetd but falls back to SDDM if greetd is absent. Calamares config lists both.
- **AURA**: strictly on-demand D-Bus activation preserved; systemd unit has no
  WantedBy= so it does not start at boot. Hardening directives intact.
- **Bright Android**: remains a user-level systemd service (`bright-android.service`
  in `/usr/lib/systemd/user/`), session-activated via the bright-android launcher.
  No system-level enablement.
- **Calamares**: installer preserved with greetd support; all modules (partition,
  bootloader, users, etc.) intact.
- **Security**: AppArmor (kernel default), firewalld, sysctl hardening, policykit
  agent, AURA D-Bus policy, Bright Android D-Bus policy all retained.
- **Live USB autologin**: greetd autologin for the live user; SDDM autologin
  written only when SDDM exists.
- **Firmware**: all firmware packages (nonfree, realtek, iwlwifi, atheros, brcm,
  intelwimax) remain in core for USB/hardware compatibility.

## Test results (sandbox)

- Shell tests: 18 passed, 0 failed (including the new test-phase6-3-lightweight
  with 75 assertions).
- Python (aura): 247 tests pass (4 environmental skips due to missing system
  packages in sandbox; expected).
- Python (bright_android): 345 tests pass (49 environmental skips; expected).
- CI YAML for iso-build.yml is still valid (not tested end-to-end in this pass).

## Remaining blockers / unverified

1. **End-to-end ISO build**: The CI iso-build pipeline on GitHub Actions needs to
   be re-run for this branch. The package list changes may expose uninstallable
   packages or live-build issues that cannot be reproduced in the sandbox
   (which lacks live-build and debootstrap). This is the primary next verification
   step.
2. **Runtime VM tests**: labwc + Bright Shell + greetd have not yet been booted
   in a real Debian 13 VM with this package set; idle RAM at 120 s is not yet
   measured. The 250 MB idle target is an engineering goal and cannot be claimed
   until QEMU/KVM measurements are taken.
3. **Hardware tests**: No physical USB boot or real hardware testing performed;
   USB/EFI/BIOS boot, Wi-Fi, audio, brightness, touchpad, etc. must be verified
   on real hardware.
4. **greetd/gtkgreet session verification**: Login, session selection, logout,
   recovery-to-KWin path, and password change flows need VM testing.
5. **Package availability**: A few packages (alacritty, featherpad, pavucontrol-qt,
   mako-notifier, etc.) are expected to exist in Debian Trixie based on upstream
   knowledge but a full `lb bootstrap` + `lb chroot_install-packages` run in CI
   is the authoritative verification.
6. **Optional profile integration**: build.sh does not yet expose a CLI flag to
   select arbitrary optional profiles (e.g. `--with-bluetooth`, `--with-printing`).
   Currently optional profiles are selected implicitly by edition (home includes
   bluetooth/printing; lite excludes them; developer adds all). A future iteration
   can add explicit opt-in flags.

## Memory measurement plan

Once an ISO is successfully built, run in QEMU/KVM with 2 GB RAM, 2 vCPUs,
default display (virtio-gpu), e1000 network:
- Boot the ISO, wait 120 s after shell appears.
- Collect: MemTotal, MemAvailable, /proc/meminfo, process RSS/PSS via `ps` and
  `/proc/*/smaps`.
- Break down by: greetd/cage/gtkgreet, labwc, bright-desktop-shell.py, pipewire,
  wireplumber, NetworkManager, firewalld, systemd-journald, other services.
- Save JSON via `tools/measure/measure_memory.py` with environment metadata.
- Do NOT use container memory as a Bright OS measurement.

## Files added/modified summary

- 15 new files (9 optional package profiles, greetd config, display-manager hook,
  greeter sysusers/tmpfiles, Phase 6.3 test, audit doc, implementation doc).
- ~18 existing files modified (package lists, build scripts, hooks, session
  scripts, Calamares config, Python test sync, live-boot autologin).
- The old labwc-experimental.list.chroot is deleted (labwc is now core).
