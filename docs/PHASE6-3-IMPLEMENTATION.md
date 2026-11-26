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

---

## Corrective Review (post-merge of PR #50)

After PR #50 was merged to `main`, a corrective pass was performed on branch
`arena/phase6-3-corrective-review` to fix issues discovered during audit.

### Bugs fixed

1. **Systemd service masking was indiscriminate.** `build.sh` was symlinking
   bluetooth, cups, ModemManager, and avahi-daemon to `/dev/null` for *every*
   edition, then the components hook called `systemctl enable` which silently
   fails on masked units. Moreover, ModemManager and avahi-daemon were never
   enabled even when their package list was included.

   Fix: Added `mask_if_disabled()` which only masks services whose feature flag
   resolves to `false`, and removes stale mask symlinks when the feature is
   `true`. Added `enable_optional_svc()` helper in the components hook that
   calls `systemctl unmask` before `systemctl enable`, and added enable paths
   for ModemManager and avahi-daemon gated on network-extras.

2. **Optional profile flags were not implemented.** PR #50 added package list
   files but the build script had no CLI surface or gating logic; the lite
   edition log message claimed minimalism but no code enforced it.

   Fix: Added 10 feature flags (`WITH_BLUETOOTH`, `WITH_PRINTING`,
   `WITH_NETWORK_EXTRAS`, `WITH_WINE`, `WITH_ANDROID`, `WITH_DEVTOOLS`,
   `WITH_RECOVERY_KWIN`, `WITH_SECUREBOOT`, `WITH_PLYMOUTH`, `WITH_QEMU`) each
   with explicit edition defaults (home: BT/printing/net-extras/android on;
   developer: home + devtools/qemu/secureboot/wine on; lite: all off). Added
   `--with-*` / `--without-*` CLI flags, `copy_opt_list()` helper that writes
   unique `opt-*.list.chroot` filenames (avoiding duplicate-install races),
   and unknown-flag rejection.

3. **greetd greeter could not start sessions.** The greeter user's login shell
   was `/usr/sbin/nologin` (pam_nologin rejects session startup for such
   users); `config.toml` did not pass `-s /usr/share/wayland-sessions` so
   gtkgreet had no session list; the display-manager hook did not create the
   greeter user, its group memberships, or `/run/user/<uid>` runtime dir
   (sysusers.d/tmpfiles.d do not execute during `lb chroot` hooks). A stale
   PoC session file `bright-labwc.desktop` clashed with the real
   `bright.desktop`.

   Fix: Changed greeter shell to `/bin/bash`; added `useradd` + group
   memberships (video/input/render) + mkdir/chown `/var/lib/greeter` and
   `/run/user/<uid>` to the display-manager hook; set cage command to
   `cage -s -- gtkgreet -s /usr/share/wayland-sessions`; removed the stale
   PoC desktop file; added SDDM fallback path when greetd is unavailable.

4. **KWin recovery session was unconditionally installed.** A hardcoded
   `bright.desktop` Exec was switched to labwc but the KWin recovery path had
   no generation logic.

   Fix: `bright.desktop` is always the labwc default (TryExec=labwc). A new
   hook `00-bright-os-session-files.hook.chroot` writes `bright-kwin.desktop`
   only if `/usr/bin/kwin_wayland` exists in the chroot (i.e. WITH_RECOVERY_KWIN
   resolved on and the package list was copied); it removes the file otherwise.
   `/usr/bin/bright-desktop-shell` is now the KWin recovery wrapper only.

5. **Polkit agent on Wayland.** `policykit-1-gnome` is X11-only; labwc/Wayland
   needs a Wayland-native polkit agent.

   Fix: Added `polkit-kde-agent-1` to core package list; autostart now prefers
   `polkit-kde-authentication-agent-1` and falls back to GTK/lx* agents.
   Added `wl-clipboard` and `jq` (essential CLI tools for Wayland and shell
   scripts).

### Tests added / updated

- `tests/test-build-pipeline.sh`: added ~10 assertions covering unknown flag
  rejection, edition-default resolution for all three editions,
  mask-if-disabled logic, unmask-before-enable in components hook, greeter
  shell not-nologin, correct cage command, bright.desktop pointing at labwc,
  bright-kwin.desktop hook-only generation. 55/0 pass.
- `tests/test-labwc-poc.sh`: updated to match corrected session layout
  (bright.desktop = labwc default; bright-kwin.desktop = hook-generated). 69/0.
- All 18 shell suites pass; AURA 247/247 pass; Bright Android 345/345 pass
  (49 skipped due to missing system packages, expected in sandbox).

### Outstanding / not verified in sandbox

- The sandbox has no KVM and no Trixie apt cache, so this corrective pass
  does **not** include:
  - A real `lb build` ISO build (would require ~30-90 min and network access
    to Debian mirrors; out of egress allowlist).
  - Boot-in-QEMU verification of greetd → gtkgreet → labwc login, Bright
    Shell startup, application launch, logout/return-to-greeter, or KWin
    recovery session entry.
  - Runtime RAM measurements; the 250 MB idle target is **not yet claimed**.
  - Runtime validation of ModemManager/avahi service states in a built
    chroot (tests cover logic statically, not actual systemd state).
- These require the GitHub Actions ISO build workflow and a runner capable
  of nested virt, or a local build+QEMU run. The new PR will be kept in
  draft state pending that validation.

### Debian 13 Trixie package availability (web-verified)

The following packages were verified to exist in Debian Trixie via
packages.debian.org: greetd 0.10.3-4, gtkgreet 0.8-1+b1, cage 0.2.0-2, labwc
0.8.3-1, layer-shell-qt 6.3.4-1, qml6-module-org-kde-layershell 6.3.4-1,
xdg-desktop-portal-wlr 0.7.1-2, mako-notifier, swaylock 1.8.2-1, swayidle
1.8.0-1, kanshi, grim, slurp, brightnessctl 0.5.1-31, wl-clipboard 2.2.1-2,
polkit-kde-agent-1 4:6.3.6-1, breeze-gtk-theme 6.3.4-1, sddm, kwin-wayland.
