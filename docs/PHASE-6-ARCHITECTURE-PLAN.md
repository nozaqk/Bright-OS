# Phase 6: Ultra-Lightweight Architecture & USB/Desktop Compatibility
## Architecture Assessment & Implementation Plan

> Status: **PLAN FOR REVIEW** — no desktop/compositor/ISO changes made yet.
> Base: `origin/main` at `f3f58e3` (PR #43, Phase 5, merged).
> Working branch: `arena/phase6-lightweight-arch`.

---

## 1. Current Architecture Assessment

### 1.1 Repository status
- **Phase 5 present in `main`:** yes — `0dfea5b`, `68c1445`, `5ee3f71`, `a0da32a` are all in main via merge commit `f3f58e3`.
- **Branch tip:** `f3f58e3 Merge pull request #43`.
- **GitHub Actions:** not configured (no `.github/workflows/`). Builds/validation are manual today.
- **Packaged copies:** source at `aura/`, `bright_android/`, `desktop/`, `applications/` is duplicated under `config/includes.chroot/usr/lib/...`; kept byte-identical by sync tests (`test_phase32_runtime.py`, `GuiCopyTests`, etc.).
- **Duplication count:** 62 Python files have identical packaged twins under `config/includes.chroot`. All shell/desktop binaries are also copied by `10-bright-os-components.hook.chroot` at build time.

### 1.2 Build system
- **Tool:** Debian `live-build` (`lb`) targeting Debian 13 Trixie amd64.
- **Config:** `build/live-build/auto/config` auto-detects live-build capability (handles Ubuntu-vs-Debian hosts, modern vs legacy `--bootloaders`/`--bootloader` flags).
- **Boot:** BIOS (isolinux/grub-pc) + UEFI (grub-efi with `shim-signed`/Secure Boot if built on Trixie). Hybrid ISO via `iso-hybrid`.
- **Init:** systemd. No `debian-installer` in the live image (`--debian-installer false`); Calamares is the post-boot installer.
- **Kernel:** `linux-image-amd64` with full `firmware-linux-nonfree`, `firmware-misc-nonfree`, and per-vendor firmware packages.
- **Current build outputs a ~2.5–3.5 GB ISO estimate** (see §1.5).
- **Persistent USB:** not configured. Live-boot uses `boot=live` with no `persistence` or `persistence-label` parameters. No overlay persistence partition setup; no live-boot persistence package added.

### 1.3 Installer (Calamares)
- Calamares 3.3.x with a LUKS-aware sequence (`partition → mount → unpackfs → … → bootloader`).
- Configured modules include LUKS (`luksbootkeyfile` + `initramfscfg`), GRUB, displaymanager (SDDM), systemd services, and post-install shell cleanup.
- Required RAM: 2048 MB; required disk: 16 GB.
- Post-install removes `live-boot*` before `initramfs` rebuild (so installed system is a normal Debian system, not a live system).
- No OEM/preseed install mode yet; no automatic partition-preserving reinstall.

### 1.4 Session / compositor / shell (current state)
| Component | Current choice | Notes |
|---|---|---|
| Display server | Wayland default, X11 fallback | `xwayland` + full `xserver-xorg-video-all` installed |
| Compositor (Home/Dev) | **KWin** (`kwin-wayland`) | Full KWin with effects |
| Compositor (Lite) | KWin (no effects) or openbox + picom on X11 | Lite still pulls KWin per core list |
| Display manager | **SDDM** (with `sddm-theme-debian-breeze`) | Overhead ~30–60 MB resident |
| Desktop shell | **bright-desktop-shell.py + Shell.qml** | PyQt6 + QML (~558 + 715 lines), embedded in KWin |
| Apps | PyQt6 custom (launcher, files, terminal, settings, monitor, control-center, about, store, update) | 8 apps, 2 961 lines total Python |
| Panel/dock | In-application in Shell.qml | No separate panel |

**Important architectural observations:**
1. The current "shell" is a QML app running inside KWin (which acts as the Wayland compositor). We are NOT already running a custom compositor; KWin is the compositor.
2. Even the **Lite** edition pulls `kwin-wayland` (because it is in `core.list.chroot`), plus LXQt + openbox + picom. "Lite" is not actually that light — it layers three possible WMs.
3. The core package list pulls both `kwin-wayland` AND `xserver-xorg-core` AND `xserver-xorg-video-all` — full X stack even though default is Wayland.
4. `sddm` is always installed even though it is a heavy DM; there is no direct-session autologin alternative for the installed system.

### 1.5 Package footprint (approximate, from package lists)
| List | Effective packages (non-comment/blank lines) | Estimated installed size |
|---|---|---|
| `core.list.chroot` | 173 | ~1.1–1.4 GB (kernel + firmware + Qt6 + KWin + Python + Calamares + NetworkManager + PipeWire + fonts) |
| `desktop.list.chroot` (Home/Dev) | 34 | ~0.9–1.3 GB (full KDE Plasma + Firefox + printing + Blueman + Discover + CUPS) |
| `desktop-lite.list.chroot` | 29 | ~0.3–0.4 GB (LXQt + picom + featherpad etc.) |
| `aura-core.list.chroot` | 18 | ~0.1 GB (auditd/apparmor/psutil) — most overlap with core |
| `android.list.chroot` | 6 | ~0.5–1.0 GB (Waydroid + LXC + images not in ISO but post-install) |
| `editions/home` | 25 | ~0.6–0.9 GB (LibreOffice + VLC + GIMP + Thunderbird + Wine) |
| `editions/lite` | 12 | ~0.1 GB (mpv + abiword + gnumeric) |
| **Total Home (estimated)** | ~250 packages + recommends | **2.6–3.2 GB installed; ISO ~2.2–2.8 GB** |
| **Total Lite (estimated)** | ~220 packages + recommends | **1.7–2.2 GB installed; ISO ~1.4–1.9 GB** |

These are engineering estimates based on package lists; actual sizes must be **measured**, not claimed.

### 1.6 Services running at boot (from installed config)
| Service | User | Notes |
|---|---|---|
| systemd + journald | root | always |
| NetworkManager | root | + firewalld |
| sddm | root | display manager, always starts |
| AURA (`aura-core.service`) | `aura` | **NOT** enabled by default (D-Bus activation only, per unit file) — good for idle RAM |
| bright-android | user (session) | `WantedBy=graphical-session.target`; only runs when logged in |
| pipewire + wireplumber | user | audio |
| Calamares | — | only on live medium |
| polkitd, udisksd, upower, systemd-resolved, systemd-timesyncd | system | standard |
| auditd, apparmor | root | from aura-core list |
| flatpak system-helper | system | flatpak installed |
| grub-initrd-fallback, plymouth | — | boot |

No measured idle RAM figure exists yet; 250–350 MB target vs likely **500–800 MB** today (SDDM + KWin + Plasma/LXQt components + sddm-theme + Polkit agent + NetworkManager applet + blueman + pipewire + AURA (D-Bus activated, so 0 until called)).

### 1.7 USB / live support today
- Live boot works via `boot=live` kernel parameter (Debian live-boot).
- Grub entries: Default, Safe Graphics, Verbose, Recovery (`nox11autologin nopersistence debug`), chainloader, advanced.
- Live user: `user`/`live`, passwordless sudo, SDDM autologin.
- **Missing:**
  - Persistence partition setup (no `persistence`/`persistence-label=bright-os` boot parameter, no `live-boot-initramfs-tools` persistence tools enabled by default, no persistence.conf template, no partition-detector hooks).
  - USB 2.0 vs 3.0 tuning (no `rootdelay` tuning, no I/O scheduler hints for slow USB).
  - "Safe USB removal" / data integrity protocol (no explicit sync on shutdown indicator, no overlay fs flush markers).
  - Toram/copy-to-RAM boot option.
  - Automatic recovery from read-only USB errors (overlay error handling).
  - Hybrid ISO verification before writing.

### 1.8 Existing tests
- **Python unit tests:** 17 source test files (≈600 tests) covering AURA, Bright Android, security, authorization. All passing as of Phase 5. Plus 17 identical packaged copies under `config/includes.chroot` (kept in sync by sync tests).
- **Shell tests:** 15 suites (test-apps, test-build-readiness, test-installer, test-live-boot, test-calamares, test-packages, test-aura-core, etc.) covering package lists, syntax, config structure, Calamares, ISO validator.
- **Tests that DO NOT yet exist:**
  - ISO size budget test.
  - Idle RAM measurement test.
  - Boot time measurement test.
  - Persistence enable/disable smoke test.
  - USB safe-unmount / sync-on-shutdown test.
  - Installed-system package footprint delta test.
  - qemu/kvm-based boot-smoke test (boot to desktop screenshot + RAM probe).
  - GitHub Actions CI for build+validation.

### 1.9 Key risks & findings
1. **KWin + Qt6 + SDDM + Plasma/LXQt ≠ lightweight.** Meeting 250–350 MB idle with KWin/SDDM/Plasma is unlikely. Even LXQt + SDDM + KWin is ~400–500 MB.
2. **Core package list is bloated for a "minimal" foundation.** `xserver-xorg-video-all`, full Qt6 stack with QML modules, KWin, SDDM, `gnome-disk-utility`, `partitionmanager`, `gparted`, `firewalld`, `cups`, `blueman`, `breeze-icon-theme`, `adwaita-icon-theme`, `gvfs-backends`, `flatpak`, `plymouth-themes`, `hplip`-class items, `imagemagick`, `neofetch`, `file-roller`, etc. are all in *core*.
3. **Two desktop stacks in Lite** (KWin for Wayland shell + openbox/picom for X11 fallback) wastes space and memory.
4. **Python everywhere** (shell + apps + AURA + bright-android CLI) adds interpreter overhead. Acceptable if services are on-demand, but the shell being PyQt6/QML adds 50–80 MB resident on startup.
5. **AURA is correctly on-demand (D-Bus activated, not started at boot)** — good.
6. **Bright Android is session-activated, not started at boot** — good.
7. **No firmware-split:** firmware-linux-nonfree pulls everything; per-firmware-reduce could cut ISO size for Lite.
8. **Persistent USB is not implemented at all.**
9. **No GitHub Actions** — build/validation/release is manual.
10. **Duplicate "source+packaged" layout doubles maintenance** — any change must be copied; sync tests catch divergence but don't eliminate the copy.

---

## 2. Proposed Lightweight Architecture

### 2.1 Design principles
1. **One OS, two modes.** The *same* rootfs is used for live USB and installed system. Differences are implemented via boot parameters, a firstboot service, and a writable overlay — not separate package sets.
2. **Lite is the new baseline.** The "Home" edition becomes Lite + optional extra packages (LibreOffice, VLC, etc.) added via metapackages, not a heavier desktop stack. Developer edition = Home + dev tools. This directly targets the 1 GB / 250–350 MB idle goal.
3. **Compositor choice: wlroots-based compositor rather than writing from scratch.** After evaluation:
   - **KWin** retained only as an *optional* alternative (for users who want full KDE effects); not default.
   - **Default compositor for all editions: a wlroots-based compositor.** Evaluated options:
     - **labwc** — wlroots, Openbox-like XML config, small footprint, good XWayland support, actively maintained, no Qt dependency. ~2–5 MB resident.
     - **sway** — wlroots, i3-compatible, tiling; keyboard-driven, good fit for "Developer" edition but less natural as a default DE compositor.
     - **Wayfire** — wlroots, 3D effects, larger than labwc.
     - **Cage** — single-app kiosk compositor; too minimal.
     - **Smithay (Rust)** — library, not a usable compositor; would effectively require writing one.
   - **Recommendation: labwc as the default compositor**, with an optional `bright-compositor` wrapper that provides panel/dock/launcher integration via the layer-shell protocol. We do NOT write a compositor from scratch in Phase 6.
4. **Display manager: eliminate SDDM from the default path.** Options:
   - Use `lightdm` with a minimal greeter (~5–10 MB) — but still a second process.
   - Use **autologin via a systemd user session + `bright-session` launcher script** on installed systems (like Endless OS / SteamOS); autologin into a `bright` user, lock screen handled by the shell. For multi-user systems or manual login, lightdm can be installed optionally.
   - For live USB, autologin is already the default — just remove SDDM from the default path.
   - **Recommendation: default to direct session autologin with a built-in lock screen; ship lightdm-gtk-greeter as an optional DM for multi-user installs. Remove sddm from the default core list.**
5. **Native C++ shell deferred.** The Phase 6 plan retains the PyQt6/QML shell for now (rewriting it is a large project that would delay the lightweight target). Priority is compositor/DM/service/package/footprint work first. The native shell is a subsequent phase.
6. **On-demand AURA preserved.** (Already correct.)
7. **Bright Android (Waydroid/Wine) optional** — pulled in via metapackage, not default for Lite.

### 2.2 Target package set (proposed "bright-core")
A revised `core.list.chroot` target:
- **Kernel:** `linux-image-amd64` (no headers in default installed system; headers in -dev metapackage).
- **Firmware:** split into `firmware-linux-free` + `firmware-misc-nonfree` + an explicit smaller list of common firmware (realtek/intel wifi/amdgpu) — installer/Live ISO can still include the full set via an `-extras` ISO variant; base ISO uses a trimmed set to hit 2 GB.
- **Init/system:** `systemd-sysv`, `dbus`, `udev`, `util-linux`, `coreutils`, `bash`, `apt`, `sudo`, `policykit-1`, `elogind` (instead of pulling full logind via a DM), `tzdata`, `locales`, `keyboard-configuration`, `console-setup`, `kmod`, `ca-certificates`, `curl`, `wget`, `btrfs-progs`, `e2fsprogs`, `xfsprogs`, `dosfstools`, `ntfs-3g`, `exfatprogs`, `fuse3`, `lvm2`, `cryptsetup`, `udisks2` (without gvfs-backends deps), `openssh-client`.
- **Networking:** `network-manager` (without `network-manager-openvpn` by default; add via vpn metapackage), `iwd`, `iproute2`, `iputils-ping`, `wpasupplicant`, `wireless-tools`, `dnsmasq-base`, `firewalld`.
- **Audio:** `pipewire`, `pipewire-pulse`, `wireplumber`, `alsa-utils`, `pavucontrol` (not pavucontrol-qt to avoid Qt dep).
- **Graphics:** `mesa-vulkan-drivers`, `mesa-va-drivers`, `mesa-vdpau-drivers`, `xwayland`, `libgl1-mesa-dri`, `xserver-xorg-core` (opt-in; not pulled unless X11 fallback needed), `xserver-xorg-input-libinput` only (drop `-video-all`; KMS drivers are in the kernel).
- **Compositor:** `labwc`, `xwayland`, `wl-clipboard`, `swayidle`, `swaylock`, `grim`, `slurp`, `mako` (notifications), `waybar` (panel, optional — we may use our shell's panel instead), `wlr-randr`.
- **Shell/Apps:** keep PyQt6 minimal: `python3-pyqt6` only (drop qml, quick, svg, network, printsupport unless shell needs them; audit Shell.qml imports). Replace `breeze-icon-theme` + `adwaita-icon-theme` with `papirus-icon-theme` (smaller?) or one icon theme. `qt6ct` for Qt theming.
- **DM (optional):** `lightdm` + `lightdm-gtk-greeter` in its own list, not core.
- **Fonts:** keep `fonts-dejavu`, `fonts-liberation2`, `fonts-noto-cjk` opt-out via metapackage, `fonts-noto-color-emoji`, `fontconfig`.
- **Utilities:** `htop`, `neofetch` (optional), `file-roller`, `unzip`, `p7zip-full`, `rsync`, `upower`, `acpid`, `xdg-user-dirs`, `xdg-utils`, `xdg-desktop-portal` + `xdg-desktop-portal-wlr` (critical for labwc), `xdg-desktop-portal-gtk` (file picker).
- **Installer:** `calamares` + `calamares-settings-debian` + `os-prober` + `grub-pc-bin`/`grub-efi-amd64-bin` — these live on the live medium only; uninstalled post-install via Calamares packages module.
- **Boot:** `grub-common`, `grub-pc-bin`, `grub-efi-amd64-bin`, `shim-signed`, `plymouth` (but drop `plymouth-themes`/`plymouth-label` for Lite).
- **Remove from current core:** `sddm`, `kwin-wayland`, `plasma-workspace`, `qt6-qml*` modules not needed, `qml6-module-*`, `breeze-icon-theme` (if replaced), `gvfs-backends`, `gvfs-fuse` (keep `gvfs`), `network-manager-openvpn`, `policykit-1-gnome` (replace with `polkit-kde-agent-1` or `lxpolkit`), `gnome-keyring-daemon` (replaced with a smaller kwallet/lite substitute or nothing by default), `gnome-disk-utility`, `partitionmanager`, `gparted` (move to installer/live only), `cups`, `blueman`, `print-manager`, `imagemagick`, `firefox-esr` (move to editions), `volumeicon-alsa` (not needed with pipewire applet), `software-properties-common`, `optipng`, `sassc`, `neofetch`.

### 2.3 Metapackage strategy
Replace giant package lists with metapackages built in-tree:
- `bright-os-core` — base system + compositor + shell (live + installed).
- `bright-os-live` — live-medium-only (installer, memtest, recovery tools); removed post-install.
- `bright-os-lite` — minimal apps (firefox-esr, mpv, abiword, gnumeric, pcmanfm, featherpad).
- `bright-os-home` — Lite + office suite, media apps, accessories.
- `bright-os-developer` — Home + dev toolchain.
- `bright-os-android` — Waydroid support (optional add-on).
- `bright-os-wine` — Wine/Proton (optional add-on).

This keeps the core ISO under 2 GB by shipping only `bright-os-live + bright-os-lite` in the default ISO; Home/Developer/Android/Wine are installable post-install or via a "full" ISO variant.

### 2.4 Session architecture (post-change)
```
[systemd] → autologin (or lightdm if installed)
   │
   └─ bright-session.target (user)
        ├── pipewire + wireplumber
        ├── xdg-desktop-portal (-wlr + -gtk)
        ├── bright-android.service (D-Bus activated, only when opened)
        ├── polkit agent (lxpolkit / polkit-gnome-agent)
        ├── mako (notifications)
        ├── swayidle (idle management)
        └── labwc (compositor) ── exec bright-desktop-shell.py
                                    │
                                    ├─ panel/dock/launcher (PyQt6 shell)
                                    └─ xdg-desktop-portal file pickers
```
No KWin, no SDDM, no Plasma components in the default path. Expected idle RAM: **200–300 MB** once shell is warmed up. KWin/SDDM/Plasma remain installable as a "KDE Desktop" session option.

---

## 3. USB and Internal Installation Design

### 3.1 Live USB architecture
**Boot flow:**
1. BIOS/UEFI loads GRUB from hybrid ISO (MBR+GPT, same as today).
2. Default boot entry: `boot=live persistence components` (added: `persistence`, `components`, `swap=true`, `quickreboot`, `nofull`).
3. GRUB menu adds new entries:
   - "Start Bright OS Live (Default)" — with persistence if present
   - "Start Bright OS Live (No Persistence)" — `nopersistence`
   - "Start Bright OS (Copy to RAM)" — `toram` (for USB 2.0 slow media)
   - "Start Bright OS (Safe Graphics)"
   - "Install Bright OS" (direct to Calamares, no shell autologin)
   - "Recovery Mode" (root shell, no GUI)
4. `live-boot` mounts the squashfs + overlay (tmpfs by default, persistent partition if labeled `BRIGHT_OS-PERSIST` with `persistence.conf`).
5. `live-config` (via existing `05-bright-os` hook) sets up `user` account, autologin (to bright-session, not to SDDM), hostname, os-release, MOTD.
6. bright-session starts labwc + shell on tty1.
7. User sees desktop with "Install Bright OS" shortcut.

**Persistence:**
- Partition label `BRIGHT_OS-PERSIST` (ext4), mountpoint `/`, type `overlay` (live-boot persistence).
- A setup tool (`bright-persistence-setup`, a small Python/CLI tool run from the live desktop) creates the partition + filesystem + persistence.conf and instructs user to reboot.
- Home-directory-only persistence (`/home`) as an option, plus full root persistence.
- Safe unmount: the session logout + shutdown sequence calls `sync` and waits for overlay fs to flush; shutdown splash shows "You may now remove the USB drive" only after filesystems are unmounted.

**USB 2.0 / 3.0:**
- `elevator=noop` (or `none` for modern kernels) for USB media.
- `rootdelay=10` on the "USB compatibility" entry.
- `toram` option copies the entire squashfs to RAM for USB 2.0 sticks; requires ≥1.5 GB available RAM.
- Slab/page cache tuning (lower `vm.vfs_cache_pressure`? — actually default is fine; don't tune without measurement).

**Recovery:**
- Recovery mode boots to a root shell with networking; includes `bright-repair` script that can:
  - check filesystem integrity
  - reinstall GRUB
  - reset user password
  - enable/disable persistence
  - re-run firstboot

### 3.2 Installed desktop architecture
- Calamares unpacks the same live rootfs (no separate "installed" image) and runs post-install scripts to:
  - remove live packages (`live-boot`, `live-config`, `calamares*-only-on-live`, installer desktop shortcut).
  - set up hostname, users, locale, timezone (already Calamares modules).
  - install GRUB to the target disk (already bootloader module).
  - enable `bright-session` autologin (or set up lightdm if chosen).
  - generate initramfs without live-boot hooks.
- The installed system uses:
  - Same bright-core packages as live.
  - Same shell, compositor, apps.
  - Persistent storage on internal HDD/SSD (btrfs default, with optional LUKS).
  - Normal apt updates via a `bright-os` apt suite (initially just Debian Trixie; Bright OS repo can be added later).
- Post-install, systemd `bright-os-firstboot.service` runs once to:
  - set edition,
  - install metapackage updates,
  - offer to install Nvidia/AMD firmware,
  - offer to install Bright Android (Waydroid) / Wine.
- Updates: normal `apt upgrade`; use `unattended-upgrades` for security by default (opt-out).
- Optional features (AURA models, Waydroid, Wine, LibreOffice, dev tools) are lazy-installed, not started at boot.

### 3.3 Filesystem layout
- Live medium: GPT, BIOS boot partition + EFI System Partition (FAT32) + read-only squashfs + boot partition; optionally added persistence partition.
- Installed system: default GPT + EFI + btrfs root (with subvolumes `@`, `@home`, `@cache`, `@log`, `@swap` as swapfile on btrfs or separate swap partition; offer LUKS). Dual-boot with Windows supported (Calamares already handles this).
- Writable overlay for live mode is tmpfs (RAM) by default; persistence partition extends it to disk.

---

## 4. Memory Optimization Opportunities

Ranked by expected impact:

| # | Opportunity | Estimated RAM saving | Risk |
|---|---|---|---|
| 1 | Replace SDDM with direct autologin (+ optional lightdm) | 30–60 MB | Low; needs new lock screen |
| 2 | Replace KWin with labwc (default) | 80–150 MB (KWin ~100–150 MB; labwc ~3–8 MB) | Medium; need layer-shell shell integration |
| 3 | Drop full X stack from default (xserver-xorg-video-all → just xserver-xorg-core+xwayland) | ~20–40 MB + ISO size | Low; some GPUs may need specific -video-* packages which are installable |
| 4 | Trim `core.list.chroot` — remove GNOME/KDE utilities (gnome-disk-utility, partitionmanager, gparted, blueman, kwrite, discover, etc. to optional/live-only) | 50–150 MB RSS + ISO | Low |
| 5 | Reduce Qt6/QML modules loaded by shell — audit Shell.qml imports; can we move away from QtQuick.Controls/Particles/Shadows? | 10–30 MB | Medium; may require shell UI simplification |
| 6 | Replace `breeze-icon-theme` (huge) + `adwaita-icon-theme` with single lighter theme (Papirus/Hicolor) | 5–15 MB + ISO | Low |
| 7 | Disable unused systemd units by default (cups, bluetooth if no BT hw, ModemManager, avahi if installed, fwupd, flatpak system helper, udisks poller) | 10–30 MB | Low; use socket activation where possible |
| 8 | Move heavy apps (firefox, thunderbird, libreoffice, gimp, wine, waydroid) out of core/lite default (metapackage-gated) | 0 RAM, major ISO size | None; user installs on demand |
| 9 | Avoid loading AURA, bright-android at startup (already on-demand; verify no .timer or .path pulls them in early) | 0–20 MB | None |
| 10 | PipeWire is fine; but don't start pipewire-pulse as root (already per-user) | ~5 MB | None |
| 11 | `zswap` enabled + compressed swap with zstd to reduce disk pressure on 1 GB systems | indirect | Low |
| 12 | Audit Python services — defer AURA intelligence engine loading until first query (engine.start is lazy already) | 10–30 MB when idle | Low |

**Estimated post-optimization idle RAM:** 220–320 MB (labwc + shell + pipewire + NM + polkit + portal + login/keyring). Must be MEASURED on real hardware/VM, not assumed.

---

## 5. Required Repository Changes

1. **Package lists restructure:**
   - Rewrite `config/package-lists/core.list.chroot` around the new minimal core.
   - Add `bright-os-live.list.chroot` (installer/memtest/recovery tools, Calamares, only on live; removed by Calamares `packages` module post-install).
   - Replace edition `packages.list` files with metapackage definitions (or keep lists and have build scripts generate metapackages).
2. **Session files:**
   - Add `config/includes.chroot/usr/share/wayland-sessions/bright-labwc.desktop`.
   - Add `bright-session.sh` target that starts labwc + shell (not kwin_wayland).
   - Remove `bright-kwin-rules.kwinrule` from default path (moved to optional kde session).
   - Add SDDM/lightdm configs as optional, not default.
3. **Default autologin via systemd (agetty override + bright user service) instead of SDDM autologin**; add lock-screen support in shell.
4. **Bootloader (GRUB):**
   - Add persistence entries.
   - Add toram entry.
   - Add USB compatibility entry with rootdelay/elevator.
   - Add direct "Install" entry.
5. **Live-boot config:**
   - Add `persistence` and `components` and `swap=true` to default boot parameters.
   - Add live-boot-initramfs persistence hooks to build.
   - Add `config/includes.chroot/lib/live/config/06-bright-persistence` for persistence setup UI.
6. **Calamares:**
   - Add persistence removal in postcfg if user requests "install without persistence partition wipe".
   - Adjust packages module exclude list to remove live-only packages (live-boot, calamares itself from target? — careful; keep calamares libs needed for other things? No, remove).
   - Add btrfs subvolume layout as default.
7. **Shell/session:**
   - Shell must run under labwc via wlr-layer-shell instead of being embedded in KWin. This is a shell output/panel protocol change: panel needs to be a layer-shell surface, not a KWin window.
   - Add a simple lock-screen (or use `swaylock` with config).
8. **xdg-desktop-portal:** use `xdg-desktop-portal-wlr` for screenshots/screencast instead of `-kde`.
9. **Scripts/tools:**
   - `bright-persistence-setup` tool.
   - `bright-repair` recovery script.
   - Memory/boot measurement tooling in tests.
10. **GitHub Actions:** add `.github/workflows/` for:
    - Static validation (shell/python tests) on every push.
    - ISO build on Debian Trixie container (nightly / tag).
    - Qemu boot-smoke test (boot ISO, wait for `graphical.target`, report RAM and boot time).
11. **Documentation:**
    - Update README with new architecture, edition split, USB persistence.
    - Document compositor choice (labwc), rationale, and how to switch to KWin/Sway.
12. **Tests:** add new tests listed in §7.

---

## 6. Potential Compatibility Risks

| Risk | Mitigation |
|---|---|
| **labwc may not support some KWin features users rely on** (blur, window rules, kwin scripts, activities, per-app window geometry) | Make KWin + KDE Plasma an installable alternative session; document limitations. Layer-shell protocol gives us panel/dock/notification surfaces which is what the custom shell needs. |
| **PyQt6 shell on labwc via layer-shell** is unproven in current code | Port Shell.qml incrementally; labwc supports layer-shell via wlroots. The shell can detect which compositor is running (WAYLAND_DISPLAY + compositor env) and adapt. |
| **Removing SDDM** breaks multi-user / switching users | Ship `lightdm` as an option; Phase 6 default is single-user autologin (matches target "USB + fresh install" use case). Multi-user setup documented for post-install. |
| **XWayland apps** may misbehave without full video drivers in minimal list | Keep `xserver-xorg-core` and mesa DRI drivers; don't remove `-video-all` from the full ISO, only from Lite/default. Provide safe graphics boot entry. |
| **Persistence + overlayfs on USB 2.0** can be slow / corrupt on unclean removal | Add sync-on-shutdown indicator, offer toram option, use `overlayfs` with `volatile` mode when no persistence, integrity check on boot. |
| **btrfs default** may surprise users expecting ext4 | Offer ext4 as explicit option in Calamares; default btrfs with compress=zstd for better flash life and space. |
| **Removing LibreOffice / VLC from default ISO** makes the default feel incomplete | Ship Firefox + a lightweight media player + text editor; make installing full suite one-click via bright-control-center ("Add Office", "Add Media Apps"). |
| **Bright Android / Wine on Wayland/labwc** may not fully work | Waydroid works on Wayland generally; Wine/Proton works via Wine Wayland or XWayland. Test thoroughly. |
| **Existing users with Plasma/KWin** upgrading may have their session broken | Keep KDE Plasma session as an installable `bright-os-desktop-kde` metapackage; upgrade path preserves whichever session they used. |
| **firmware-linux-nonfree trimmed** may leave some hardware non-functional | Keep full firmware on "full" ISO variant; include firmware loading helper in firstboot that offers to install missing firmware. |
| **No QEMU/USB test in CI** may miss regressions | Add qemu boot-smoke test to GitHub Actions with measured RAM/boot time. Physical USB testing must remain a manual step. |

---

## 7. Testing Plan

Four tiers, clearly separated:

### 7.1 Automated (static + unit) — runs on every push (GitHub Actions)
- **All existing Python unit tests** (≈600 tests).
- **All existing shell suites** (15 suites) — as root and as nobody (Phase 5 already passes both).
- **New static checks:**
  - ISO package-footprint budget test (count installed packages in the live chroot; fail if Lite exceeds ~220 packages or Home exceeds ~280).
  - No-KWin/SDDM-in-default test (assert `kwin-wayland` and `sddm` are not in `core.list.chroot` for Lite build).
  - Service enablement audit (assert no heavy services are enabled by default; only sockets/activation).
  - Shell and packaged-copies synchronization (already exists).
  - Polkit policy well-formedness (already exists).
  - GRUB menu entry persistence/toram present.
  - Persistence.conf template installed.

### 7.2 Virtual machine tests (QEMU/KVM) — nightly + on release PRs
- Build ISO in CI (Debian Trixie container or self-hosted runner).
- Boot ISO in QEMU with 1 GB RAM, 2 GB disk:
  - **Boot-time test:** measure time from GRUB selection to shell-ready (dbus idle + shell window mapped); target < 60 s in VM.
  - **Idle RAM test:** sample `free -m` 60 s after shell ready; target ≤ 350 MB in VM (which is a conservative proxy for hardware).
  - **Install test:** run Calamares in unattended/autopilot mode to a virtual disk, reboot, verify the installed system boots to shell.
  - **Persistence test:** boot with a second virtual disk labeled BRIGHT_OS-PERSIST, create a file on desktop, reboot, verify file still present.
  - **Shutdown test:** verify system reaches poweroff target without hanging.
- Run with both BIOS and UEFI (OVMF).

### 7.3 USB media tests (manual / semi-automated)
- Write ISO to USB 2.0 stick and USB 3.0 stick (two different brands).
- Boot on at least three reference machines:
  - Low-spec: ≤ 4 GB RAM, dual-core CPU, HDD, Intel integrated graphics (1 GB RAM target).
  - Mid-spec: 4–8 GB RAM, SATA SSD, recent AMD/Intel.
  - Modern: NVMe, UEFI, ≥ 8 GB RAM.
- Measure:
  - Boot time (GRUB to desktop).
  - Idle RAM (`free -h` after 5 min idle).
  - Application launch time (terminal, file manager, browser).
  - Persistence round-trip.
  - USB removal safety (data saved after unclean removal is acceptable only if no write was in progress; unclean removal during write → on next boot run fsck/overlay recovery).
  - Install to internal disk, reboot into installed system, verify.
  - USB 2.0 with toram boot.

### 7.4 Installed system tests
- Install on HDD (BIOS) and SSD/NVMe (UEFI) with and without LUKS.
- Verify system updates (`apt update && apt upgrade`).
- Verify reboot/shutdown.
- Verify suspend/resume on laptops.
- Verify WiFi, sound, Bluetooth, printing (if attached).
- Verify Bright Android (Waydroid) install/run/stop cycle after adding `bright-os-android` metapackage.
- Verify Wine/Proton after adding `bright-os-wine` metapackage.

### 7.5 Things we explicitly will NOT claim without measurement
- "Idle RAM is 250 MB" until measured on real hardware/VM.
- "Boots in X seconds" until measured.
- "ISO size under 2 GB" until built and measured.
- "Works on all hardware" — we will list tested hardware.

---

## 8. Phased Implementation Roadmap

Proposed sub-phases within Phase 6, each a separate commit/PR:

| Sub-phase | Commit/PR scope | Estimated risk | Prerequisite |
|---|---|---|---|
| **6.0** Repository hygiene + CI scaffolding + measurement tests | Add GitHub Actions workflow for static tests; add package-footprint and service-enablement tests; add qemu boot-smoke harness skeleton; do NOT change packages yet. | Low | None |
| **6.1** Package list restructure (core/live/lite) | Rewrite `core.list.chroot`, add `bright-os-live.list.chroot`, trim heavy packages; build ISO locally, measure size. SDDM/KWin stay in place for this PR (so desktop still boots). | Low–Medium | 6.0 |
| **6.2** Default-session switch (labwc + direct autologin) | Add labwc dependencies, add bright-session.sh, add wlr portal, add swayidle/swaylock/mako; keep KWin/SDDM sessions installable; change default session to bright-labwc. Test in qemu. | Medium | 6.1 |
| **6.3** Shell layer-shell port | Port Shell.qml panel/dock/launcher to use wlr-layer-shell (via QtWayland layer-shell or via embedding the shell in a layer-shell client). Remove dependency on KWin window embedding. | High | 6.2 |
| **6.4** USB persistence + boot entries | Add GRUB entries (persistence, toram, USB compat, install, recovery); add persistence-setup tool; add overlay/safe-shutdown indicator; add live-config hooks. Test in qemu with extra disk. | Medium | 6.2 |
| **6.5** Calamares post-install trimming + btrfs defaults | Packages module removes live packages; set btrfs subvolume default; install lightdm optionally; post-install memory verification. | Low–Medium | 6.2 |
| **6.6** Metapackages + first-run wizard | Add bright-os metapackages; firstboot service offers Android/Wine/Office/KDE options; edition detection. | Medium | 6.1, 6.5 |
| **6.7** GitHub Actions ISO build + qemu tests on PRs | Wire up nightly and PR builds; measure/record RAM, boot time, ISO size as artifacts. | Medium | 6.0, 6.1 |
| **6.8** Firmware trimming + toram + USB tuning | Trim firmware package set for Lite; add elevator/rootdelay tuning; test on USB 2.0/3.0 physical media. | Low | 6.4 |
| **6.9** Measurement & validation on physical hardware | Produce the measured-vs-target report; iterate to hit 250–350 MB idle / <2 GB ISO / 1 GB min RAM. | Low | All prior |

Each sub-phase ends with a PR against main, with CI results attached. Sub-phases 6.1 and 6.2 are the highest-risk and should have extra review. We will NOT start a C++ compositor rewrite in Phase 6 — compositor is wlroots/labwc. The native C++ shell is a post-Phase-6 project.

---

## 9. What This Plan Does NOT Do (out of scope for now)

- Rewrite the desktop shell in C++ (deferred to a future phase).
- Write a Wayland compositor from scratch (we use labwc/wlroots).
- Replace apt/DPKG with a different package system.
- Remove AURA security hardening (preserved per standing rules).
- Remove Bright Android integration (made optional-addon, not removed).
- Force a single filesystem (btrfs default, ext4/LUKS still supported).
- Require Secure Boot (shim is there if available).
- Make non-x86-64 ports (RISC-V/ARM) — targets x86-64 only for now.

---

## 10. Open Decisions Requesting Your Input

Before I begin implementation, please confirm/adjust:

1. **Compositor choice:** labwc as default compositor (wlroots-based)? Or would you prefer sway (tiling) or another?
2. **Display manager:** default to direct autologin (no DM), with lightdm optional? Or keep lightdm as the default (adds ~15–25 MB but is familiar)?
3. **ISO variant strategy:** single "Lite" ISO under 2 GB with metapackage install for Home/Dev/Android/Wine post-install; OR two ISOs (Lite + Full)?
4. **Default filesystem:** btrfs with compress=zstd + swapfile? Or ext4?
5. **Firmware:** trim firmware for the default ISO to save space (risk: some hardware needs missing firmware on first boot), OR keep full firmware set (larger ISO)?
6. **Qt6 QML dependency for the shell:** acceptable to keep for Phase 6, or do you want me to prioritize the C++ shell rewrite earlier?
7. **GitHub Actions approved** (per your rule #9) — I'll set up CI. Confirm this applies to PR validation + ISO builds.

Once you approve the plan and answer these decisions, I'll start implementation with sub-phase 6.0 (CI scaffolding + measurement tests) and work through the phases in order with separate commits and PRs per sub-phase, stopping after each for review.
