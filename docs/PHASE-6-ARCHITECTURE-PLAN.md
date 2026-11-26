# Phase 6: Ultra-Lightweight Architecture & USB/Desktop Compatibility
## Revised Architecture & Implementation Plan (v2)

> Status: **PLAN FOR REVIEW — DOCUMENTATION ONLY** (no OS/package/session/ISO changes yet).
> Base: `origin/main` at `f3f58e3` (Phase 5, PR #43 merged).
> Working branch: `arena/phase6-lightweight-arch` (commit `aa83c6d` contains v1 of this plan; this commit revises it).
> Review feedback applied per instructions dated 2026-11-26.

---

## 0. Approved decisions (baseline)

These are adopted as fixed architectural decisions:

1. **Compositor:** `labwc` (wlroots-based) is the default compositor. KWin remains an optional alternative session.
2. **ISO strategy:** **One** Lite ISO targeting **under 2 GB**. Home/Developer/Android/Wine are optional installable components (post-install metapackages).
3. **Filesystem:** **ext4** default. **btrfs** offered as an advanced option in Calamares.
4. **Firmware:** **Retain broad firmware support initially.** Do not trim firmware to chase ISO size before measuring. Optimize only after real ISO size is known.
5. **Desktop shell:** Retain the existing PyQt6/QML shell for Phase 6. No C++ shell rewrite in this phase.
6. **GitHub Actions:** Approved for PR validation, automated ISO builds and QEMU testing.
7. **Same OS in both modes:** USB-live and installed systems use the same rootfs, desktop, apps and system components; differences are handled via boot parameters and a firstboot service.

---

## 1. Current architecture assessment (recap of audited state)

- **Phase 5 present in main:** yes. Commits `0dfea5b`, `68c1445`, `5ee3f71`, `a0da32a` are merged via `f3f58e3`.
- **Build:** Debian live-build targeting Debian 13 Trixie amd64, BIOS+UEFI hybrid ISO, systemd init.
- **Current desktop stack (default Home):** SDDM → KWin (Wayland) → bright-desktop-shell.py (PyQt6+QML) embedded in KWin → Qt6 apps. Plasma workspace is also pulled in.
- **Lite edition:** still pulls KWin (in core) and adds LXQt + openbox + picom; multiple WM paths.
- **Persistence:** not implemented (no `persistence` boot param, no setup tool, no `toram` entry, no safe-shutdown).
- **core.list.chroot:** 173 non-comment lines; includes SDDM, KWin, full Qt6+QML stack, X server full video drivers, gvfs-backends, GNOME/KDE disk utilities, CUPS, blueman, flatpak, imagemagick, neofetch, partitionmanager, gparted, policykit-1-gnome, breeze+adwaita icon themes.
- **AURA:** correct D-Bus activation (not started at boot). **bright-android:** user session-activated (correct). **AURA Polkit authorization** hardened in Phase 5.
- **Services enabled at boot:** systemd, NetworkManager, firewalld, sddm, polkit agent, udisks2, upower, systemd-logind, pipewire (user), flatpak system helper, auditd, apparmor.
- **Tests:** ~600 Python unit tests pass; 15 shell suites pass as root+nobody; no RAM/boot/ISO-size/persistence/QEMU tests; no GitHub Actions.
- **Duplication:** 62 Python files have byte-identical packaged copies under `config/includes.chroot/` (enforced by sync tests).

See §1 of the v1 plan (`docs/PHASE-6-ARCHITECTURE-PLAN.md` prior to this revision) for full file-level inventory.

---

## 2. Corrected system architecture

### 2.1 Init, session management and security
- **Init:** `systemd` (keep). Debian systemd already provides `systemd-logind`; **do NOT add elogind** (would conflict and is unnecessary).
- **Sessions:** standard systemd PAM sessions (not custom).
- **Polkit agent:** exactly one authentication agent in the default user session. Options on Debian Trixie:
  - `policykit-1-gnome` (~500 KB installed, GTK3, widely tested, used by XFCE/Cinnamon) — **recommended default.**
  - `lxpolkit` (GTK2, from LXDE, very small but GTK2 is legacy).
  - `polkit-kde-agent-1` (pulls KF5; do not use outside KDE optional session).
  - `polkit-dumb-agent` / custom: do not write a custom agent; avoid insecure shortcuts.
  - **Decision:** `policykit-1-gnome` as the default Polkit agent. It is the least-KDE, reasonably small, well-maintained option that does not depend on X11-exclusive toolkits (it works on Wayland).
- **Do NOT disable** security (polkitd, apparmor, auditd, firewalld), networking (NetworkManager, iwd, wpasupplicant), audio (pipewire/wireplumber), hardware/firmware, filesystem (udisks2, btrfs/ext4/lvm2/cryptsetup, gvfs) or storage (udisks2, udisks2-policy) in the name of RAM. Measure first; optimize only non-essential services.
- **Preserve AURA on-demand startup** (D-Bus activation only; no `WantedBy=`) exactly as it is in main.
- **Preserve Bright Android's activation model**: session bus D-Bus activation (`Type=dbus`, `BusName=…`, `PartOf=graphical-session.target`). Do not change it without auditing: pkexec requirement, LXC namespace needs, `RestrictNamespaces=no` relaxation, and the signal/OperationComplete ordering all depend on the current unit. Any change must be a separate audited commit with tests.
- **Networking:** NetworkManager + iwd; firewalld retained.
- **Audio:** PipeWire + wireplumber + pipewire-pulse retained (industry standard; lightweight enough at ~15–25 MB).
- **Filesystems:** keep btrfs, ext4, xfs, ntfs-3g, exfat, f2fs support; udisks2 retained.

### 2.2 Default installed size and packages

**Default Lite ISO target:** one read-only squashfs rootfs containing `bright-os-core` + `bright-os-live` + `bright-os-lite-apps` set. Post-install Calamares removes `bright-os-live` packages (Calamares itself, memtest, GRUB theme assets only needed on media). Optional metapackages (home/apps, developer, android, wine) install post-boot.

Packages NOT removed from default:
- Broad firmware support (kept for hardware compatibility).
- XWayland (many apps still need it; labwc runs it natively).
- One Polkit agent (policykit-1-gnome).
- Networking, audio, udisks2, gvfs, cryptsetup/LVM.
- `xserver-xorg-core` only if X11 fallback is kept in (review: can drop if Xwayland alone is sufficient — TBD in 6.1, measured).
- `linux-image-amd64` (kernel); `linux-headers-amd64` moves to a `-dev` metapackage (not default).

Packages removed or made optional:
- SDDM → replaced with greetd (default installed) or direct live-autologin (live only).
- KWin → moves to optional `bright-os-compositor-kwin` session package; removed from core.
- Full X11 video driver set (`xserver-xorg-video-all`) → replaced with just the modesetting driver + xwayland; vendor-specific drivers pulled in by firmware/Xorg metapackage if needed.
- Qt6 QML modules not actually required by our shell (audit imports in sub-phase 6.1).
- GNOME/KDE utilities (gnome-disk-utility, partitionmanager, gparted, kwrite, ark, bluedevil, discover, print-manager, powerdevil, etc.) → optional or live-only.
- `imagemagick` → only on live-medium (used for GRUB theme rendering during build; not needed installed).
- `plymouth-themes`/`plymouth-label` → optional or dropped for Lite.
- `neofetch`, `hplip`, `cups` (printing) → optional metapackage.
- `breeze-icon-theme` + `adwaita-icon-theme` → one icon theme kept (Papirus or Adwaita, measured).

Packages/configuration retained as-is:
- All Phase 5 security hardening (Polkit fail-closed in both AURA and Bright-Android, GUI worker lifecycle, sync tests, etc.).
- Calamares (live-medium only; removed post-install).
- Packaged source copies under `config/includes.chroot/` remain synchronized with source until proven unnecessary (removing them is out of scope for Phase 6 — can be a later cleanup).

---

## 3. Corrected login architecture

### 3.1 Two different login policies
- **Live USB:** automatic login to `user` account (password `live`, passwordless sudo). No display manager required; auto-start the bright session directly from agetty/systemd. **No insecure custom lock screen** on live — persistence is disabled by default; locking the screen on a live system isn't a security boundary since `user` has passwordless sudo.
- **Installed system:** a display manager / greeter runs by default, presenting a normal authentication prompt. User chooses session (bright-labwc, bright-kwin if installed). Session locking is provided by the display manager / session locker.

### 3.2 Greeter evaluation (greetd+tuigreet vs LightDM)
Both greetd+tuigreet and LightDM with a lightweight greeter are available on Debian 13 Trixie. Evaluated against requirements:

| Requirement | greetd + tuigreet/gtkgreet | lightdm + lightdm-gtk-greeter |
|---|---|---|
| Debian 13 Trixie packages | `greetd` 0.10.3-4 (~1.3 MB installed) + `tuigreet` 0.9.1-5 (~2 MB); `gtkgreet` available as `greetd-gtkgreet` (note: Debian package name split; see §3.3) | `lightdm` 1.32.0-6 (~818 KB) + `lightdm-gtk-greeter` (~1–3 MB plus GTK runtime) |
| Memory at greeter | ~2–8 MB (tuigreet is TUI; gtkgreet ~10–20 MB) | ~30–70 MB (greeter ~50 MB per community measurements, see [darrengoossens]) |
| systemd user sessions | Yes (PAM `pam_systemd.so`) | Yes |
| Wayland support | Yes (gtkgreet is GTK3/Wayland; tuigreet is terminal and works on any VT) | Yes (via `lightdm-autologin`/greeter session) |
| Screen locking | Requires a separate screen locker (swaylock/swaylock-effects integrated with greetd for relogin); well understood pattern | LightDM re-authenticates on unlock via `dm-tool lock` |
| Maintainability | Minimal code base, actively maintained (Kenny Levinsen, wlroots author) | Mature, widely deployed; but larger code base and GTK dependency |
| Graphical greeter | gtkgreet available (Wayland native, no X11 required) | lightdm-gtk-greeter (GTK3) |
| Multi-user switching | Supported via greeter | Supported |
| Autologin support | Yes (config.toml command) | Yes |

**Recommendation: `greetd` with `gtkgreet` (graphical Wayland greeter) as the default display manager for installed systems.** Tuigreet is kept available as a fallback for recovery/VT.

Rationale:
- greetd is ~10× lighter than LightDM+GTK greeter (important for 1 GB target).
- It is Wayland-native; we do not need X11 for the login screen.
- It is maintained by the wlroots author (labwc is wlroots-based); tight protocol compatibility.
- It supports PAM/systemd sessions correctly; does not require elogind.
- It does not pull in GTK2/KDE/Qt dependencies (gtkgreet uses GTK3, which we already pull via policykit-1-gnome and xdg-desktop-portal-gtk; no additional heavy stack).

LightDM remains available as an optional `bright-os-dm-lightdm` package for users who prefer it.

**Screen locking:** use `swaylock-effects` (or `swaylock`) with a PAM stack; greetd handles re-authentication. No custom insecure lock screen. The shell triggers lock via the standard `loginctl lock-session` / `swayidle` idle timeout.

### 3.3 Note on greetd package naming on Debian
Per a known Debian Trixie packaging quirk, greeters are named `tuigreet` and `gtkgreet` (NOT `greetd-tuigreet`/`greetd-gtkgreet`). This has bitten other installers (see ansible-collection-desktop issue #300). Build scripts and tests will assert the correct package names.

---

## 4. labwc + shell compatibility: proof-of-concept plan

This is the highest-risk integration point. We will NOT remove KWin from the default path until a proof-of-concept demonstrates that the shell runs on labwc with panel/dock/layer-shell working.

### 4.1 How the shell currently works with KWin
Investigation sub-tasks for sub-phase 6.2:
1. Audit how `bright-desktop-shell.py` starts KWin: the session script calls `kwin_wayland --exit-with-session=/usr/share/bright-os/bright-desktop-shell.py`; KWin treats the shell's QQuickView as a regular Wayland window and its own decorations/panel support is unused.
2. Determine if the shell uses KWin-specific protocols/features:
   - Window rules (`bright-kwin-rules.kwinrule`) — KWin-only; ignored on labwc.
   - Does the shell position itself fullscreen? Set window type hints? Use KWin scripting/D-Bus?
   - Does the shell manage other windows (panel/dock as separate surfaces)?
   - Which Qt platform plugin does it use (`wayland`, `xcb`, `kwin`?)?
3. Inventory every `import` in Shell.qml to determine which Qt6 modules are actually needed (Quick, Controls, Layouts, Window, Dialogs, Templates, Shapes, Particles, GraphicalEffects, FolderListModel, Settings, WorkerScript). Many of these may not be needed for a panel/dock/launcher surface.

### 4.2 QtWayland layer-shell availability
Verified: Debian Trixie ships `layer-shell-qt` 6.3.4-1 (KDE Frameworks) which provides:
- `liblayershellqtinterface6` — runtime library exposing the zwlr_layer_shell_v1 protocol to Qt6 windows.
- `qml6-module-org-kde-layershell` — QML import that lets a QML window declare itself as a layer-shell surface (anchor, layer, exclusive zone, margin, keyboard interactivity).
- The package is in the `kde/` section but its dependencies are just `libc6`, `libqt6core6t64`, `libqt6waylandclient6`, `libstdc++6`, and a Qt6 Wayland ABI package. It does NOT pull in KWin or Plasma.

Implication: our PyQt6 shell can become a layer-shell panel/dock/notification-surface by loading this QML module and setting layer/anchor/exclusive-zone properties — without writing compositor code. The shell runs as a normal Qt client window; labwc (which supports wlr-layer-shell-unstable-v1) composits it as a panel/dock.

**Risk:** `layer-shell-qt` is maintained by KDE; while it has minimal runtime deps, it is one more dependency to watch. A non-Qt panel (e.g. waybar or a small custom C++ panel) could replace it in future but is out of scope for Phase 6.

### 4.3 Proof-of-concept acceptance criteria (sub-phase 6.2)
Before KWin is moved to optional:
1. Build a test rootfs (chroot or VM) with labwc installed and KWin still installed.
2. Configure labwc to auto-start `bright-desktop-shell.py` with `QT_QPA_PLATFORM=wayland` and `QT_WAYLAND_SHELL_INTEGRATION=layer-shell` (or equivalent env var provided by layer-shell-qt).
3. Modify Shell.qml minimally to register the layer-shell surface (panel at top/bottom, dock at bottom, exclusive zone set correctly).
4. Boot to the labwc session in QEMU (TCG and KVM if available).
5. Verify:
   - Shell appears as a panel/dock covering the correct edges.
   - Regular windows (terminal, file manager, settings) tile/maximize/focus correctly below/around the panel.
   - Launcher popups, dialogs and menus render above panel surfaces.
   - Notifications (mako) appear on the correct layer.
   - xdg-desktop-portal-wlr screenshots/screencast work.
   - xdg-desktop-portal-gtk file picker works (launches by client apps).
   - Polkit agent prompts appear on top.
   - Bright Android window opens via XWayland/Wayland.
   - Session logout and restart work.
6. Compare KWin recovery: the KWin session must still be selectable and functional after the change; removal from core must NOT break recovery back to KWin.
7. Measure idle RAM in the labwc session vs the current KWin session.

If these criteria cannot be met, labwc integration is deferred and we keep KWin in core while investigating a smaller Qt-based panel (or the C++ shell is pulled forward).

### 4.4 "Small separate panel" alternative
If layer-shell-qt proves problematic (e.g. the full QML shell can't reliably be a layer surface), an alternative is to keep the shell as a regular maximized/compositor-fullscreen surface under labwc and use an established lightweight panel (`waybar`, `lxqt-panel`, or `fuzzel`/`wofi` for launcher) — but this duplicates effort and breaks the existing custom panel/dock. **Layer-shell-qt is preferred first; panel alternative is a fallback.**

---

## 5. USB persistence and boot design (corrected)

### 5.1 Live-boot parameters — verified against Debian Trixie live-boot 7
Parameters below are taken from `live-boot(7)` in Debian Trixie (manpages.debian.org/trixie/live-boot-doc). Parameters that were proposed without evidence (`swap=true` as universal default, `elevator=noop`, `rootdelay=10`) are NOT added as defaults without measurement; they may appear as compatibility boot entries.

| Parameter | Verified meaning | Default |
|---|---|---|
| `boot=live` | Activate live-boot | Always set |
| `persistence` | Probe devices for persistence media (partition label/GPT name `"persistence"` by default; see `persistence-label`) | Not set (default live boot); set explicitly on persistent entries |
| `persistence-label=LABEL,...` | Use custom label(s) instead of "persistence" when probing | We will set `persistence-label=bright-os-home` for home-only persistence, `bright-os-persist` for full-root persistence |
| `persistence-media=removable-usb` | Restrict persistence probing to USB mass-storage removable media (avoid touching internal disks) | Set on persistent entries (safety!) |
| `persistence-method=overlay` | Use overlayfs persistence (default; explicit for clarity) | Set on persistent entries |
| `persistence-storage=filesystem` | Probe labeled filesystems; do not search for archive/image files | Set on persistent entries |
| `persistence-read-only` | Mount overlay read-only (changes not saved) | Offered as "persistent read-only diagnostics" option |
| `persistence-encryption=none,luks` | Allow unencrypted and LUKS-encrypted persistence; prompt for passphrase | Set on persistent entries |
| `nopersistence` | Disable persistence even if a labeled partition exists (useful for "normal live boot" from media that previously had persistence) | Explicitly set on non-persistence entries |
| `toram` | Copy entire read-only squashfs to RAM before mounting (faster operation on USB 2.0; requires enough RAM) | Set on copy-to-RAM entry, not default |
| `components` | Enable live-config components (user setup, autologin, etc.) — verify required for our `05-bright-os` hook | Verify in 6.4 |
| `quickreboot` | Skip fsck on reboot (makes live shutdown faster) | Investigate; default may already skip sync |
| `nofull` | ? — not a live-boot parameter; **do not add**. |
| `swap=true` | Enable use of local swap partitions; not a universal default because it may activate swap from internal disks during live boot. Investigate; off by default unless proven safe. | NOT default; tested in 6.4 |
| `elevator=noop`/`none` | Kernel I/O scheduler parameter; modern kernels use `none`/`mq-deadline` automatically. Do NOT set as a universal default; USB devices get `none`/`mq-deadline` already. | Not added |
| `rootdelay=10` | Wait 10 seconds for root device; only needed for slow USB/MMC devices where the storage is slow to enumerate. | NOT default; added to "USB compatibility" entry only. |

Persistence configuration file (`persistence.conf`) — from `persistence.conf(5)`:
- Each line maps a source directory to a mount (overlay).
- Home-only persistence uses `/home` as the single line.
- Full-root persistence uses `/` (union mount of entire rootfs; caution: more risk of breaking on upgrade).
- **Initial implementation: home-directory persistence only.** This is safer, doesn't capture system/package changes that could brick the live system across Debian updates, and covers user documents/settings.
- Full-root persistence is offered as an advanced/explicit option with a documented risk warning.

### 5.2 GRUB boot entries (live medium)
Distinct, clearly labeled entries (no "automatically enables full persistence"):
1. **Start Bright OS Live (Default)** — `boot=live quiet splash ...`; no persistence flag (writes go to tmpfs overlay in RAM; no persistence probed).
2. **Start Bright OS Live with Persistent Storage** — `boot=live persistence persistence-label=bright-os-home persistence-media=removable-usb persistence-method=overlay persistence-storage=filesystem persistence-encryption=none,luks` (probes for `bright-os-home` labeled partition on removable USB; mounts `/home` persistently).
3. **Start Bright OS Live (No Persistence, even if present)** — adds `nopersistence`; for when the USB has a persistence partition you don't want to use.
4. **Start Bright OS (Copy to RAM)** — adds `toram`; shows a warning if RAM < 2 GB (enforced by GRUB or initramfs check).
5. **Start Bright OS Live (Safe Graphics)** — `nomodeset xforcevesa` (same as current).
6. **Start Bright OS Live (USB Compatibility)** — adds `rootdelay=10`, disables KMS if needed, uses more conservative USB handoff.
7. **Install Bright OS** — boots live and starts Calamares directly (no shell autologin? Or autologin with Calamares auto-launched; review current Calamares desktop shortcut).
8. **Advanced options** submenu: verbose boot, single-user/rescue, BIOS/UEFI force entries, memtest.

### 5.3 Persistence setup tool
A small GUI/CLI tool (`bright-persistence-setup`, shipped only on live medium, not on installed system) that:
1. Lists removable USB partitions.
2. Warns the user THREE times before modifying a partition (explicit confirmation dialog).
3. Never silently formats an existing partition. If a partition already exists with data, offers to:
   - Use the existing partition if it is labeled correctly and has a valid `persistence.conf`.
   - Back up first (copy existing files somewhere).
   - Cancel.
4. For new persistence setup: creates a new partition after the live-system partition (or uses free space), formats ext4, labels it `bright-os-home`, writes `/persistence.conf` containing `/home`, sets correct UUID in fstab if installed.
5. Offers LUKS encryption (passphrase twice; uses `persistence-encryption=luks`).
6. Instructs user to reboot.
7. Does not touch internal disks (filters to removable USB only, same logic as `persistence-media=removable-usb`).

### 5.4 Safe shutdown / filesystem synchronization
- Before shutdown/reboot, Plymouth splash or the shell displays "Saving data…" while `sync` runs and overlay is unmounted.
- Use `FinalKillSignal=SIGTERM` and `TimeoutStopSec=10s` in the live session systemd units; final "You may now remove the USB drive" message only appears after `systemd-shutdown` has unmounted all filesystems.
- Unclean removal: use overlayfs with `volatile` defaults for non-persistence mode (already overlay on tmpfs), so unclean USB removal during live-nonpersistent session at worst loses unsaved work from RAM; filesystem remains intact on the read-only squashfs.
- For persistence mode, `persistence-fsck=true` is the live-boot default and is retained. On boot, `FSCKFIX=true` is NOT enabled (prompts via console or recovery mode to avoid silent corruption fixes).

---

## 6. Memory optimization strategy and measurement methodology

### 6.1 Baseline first, optimize second
**No optimizations are merged before a baseline measurement exists.** Sub-phase 6.0 builds an automated measurement harness that reports per-build/per-commit numbers. After every package/session change, the same measurement runs in CI.

### 6.2 Measurement method
Idle RAM measurement protocol:
1. Boot to desktop in QEMU (KVM if available; TCG otherwise, with documented performance caveats).
2. Wait for a fixed idle period: **120 seconds** after the shell's window is mapped and CPU is idle (< 2% utilization on user+system combined for 10 consecutive seconds).
3. Capture:
   - `/proc/meminfo`: MemTotal, MemFree, MemAvailable, Buffers, Cached, SReclaimable, Shmem, Slab, PageTables, KernelStack, SwapUsed.
   - Per-process PSS and RSS via `/proc/<pid>/smaps_rollup` (Pss, Rss, Private_Clean, Private_Dirty, Shared_Clean, Shared_Dirty, Swap). PSS (Proportional Set Size) is the primary "fair" accounting because it divides shared library memory across consumers.
   - systemd service memory: `systemctl status` / `systemd-cgtop` for user-$UID.slice and system.slice.
   - Kernel memory: Slab + VmallocUsed + PageTables + KernelStack summed.
   - Reclaimable cache: Cached + SReclaimable + Buffers (separately reported; these can be dropped by the kernel under pressure so they should not be counted against "used" memory).
4. Compute:
   - **Used after idle (MemAvailable perspective):** MemTotal − MemAvailable (this is what the user would see in `free -h`).
   - **Application PSS sum:** sum of PSS across all user-session processes (excluding kernel threads).
   - **Kernel working set:** Slab unreclaimable + PageTables + KernelStack.
   - **Reclaimable cache:** Cached + SReclaimable + Buffers (reported separately, not counted against idle target).
   - **Per-service breakdown:** list user services and system services sorted by PSS.
5. Take measurements at:
   - Greeterscreen (greetd/gtkgreet running, before login).
   - Desktop idle (2 min after shell appears).
   - With one application open (terminal + file manager + browser new-tab) to show steady-state.
6. Store results in CI as JSON artifacts per commit for trend comparison.

### 6.3 Target (provisional; NOT a claim)
- Greeter: < 100 MB resident.
- Desktop idle (Lite, labwc + shell + pipewire + NM + polkit + portal + keyring + file indexer): **target 250–350 MB PSS / MemAvailable perspective**.
- Kernel working set: < 80 MB.
- These are engineering targets, not achieved facts.

### 6.4 Optimization boundaries
Do NOT disable: polkitd, systemd-logind, NetworkManager, udisksd, firewalld, pipewire/wireplumber, polkit agent, portal (wlr+gtk), AURA D-Bus activation, auditd/apparmor (can be tuned but not removed), cron/systemd timers that are essential, timesyncd, journald, systemd-resolved (if in use).
Candidates for optimization (measured one at a time):
- Package trimming (see §7).
- Service socket activation where applicable (e.g. udisks2 already is; cups if installed should be socket-activated).
- Reducing number of started user services (e.g. geoclue, colord, print services not needed when no printer).
- Enabling `zswap` with zstd to reduce swap pressure on 1 GB systems (this is NOT a RAM reduction but helps 1 GB target).
- Disabling optional user-space daemons (e.g. tracker/miners, baloo if present) from the Lite session.
- Switching icon themes to one with smaller footprint.

---

## 7. Package restructuring plan (corrected)

### 7.1 Audit before removing anything
Every package removal is preceded by:
1. `apt-cache rdepends --installed` check against the package lists to confirm nothing essential still depends on it.
2. A boot test in QEMU after removal to confirm the session still works.
3. An idle-RAM comparison (§6.2) to measure actual savings.
4. An install test (Calamares) to confirm the installed system still boots and updates.

### 7.2 Specific moves
- `linux-headers-amd64`: move to a `-dev-kernel` metapackage (not default for Lite; build environments and DKMS users install it explicitly).
- `sddm`: move to optional `bright-os-dm-sddm` package; not removed from repo; kept as recoverable alternative.
- `kwin-wayland` and all KDE Plasma packages (`plasma-workspace`, `plasma-desktop`, `breeze`, `powerdevil`, `bluedevil`, etc.): move to optional `bright-os-session-kde` metapackage; kept in repo; KWin session remains installed if user chooses KDE metapackage.
- Qt6 modules: in sub-phase 6.1, run an audit of Shell.qml imports and remove modules that are not used (qml6-module-qtquick-particles, qtquick-effects, qtquick-shapes, qt5compat-graphicaleffects, qml-workerscript candidates; verify each).
- `xserver-xorg-video-all`: replace with `xserver-xorg-video-modesetting` only; vendor-specific `xserver-xorg-video-*` packages become optional/recommends via a `bright-os-x11-drivers` metapackage. `xserver-xorg-core` is only retained if X11 apps cannot run on Xwayland alone; Xwayland does NOT need xserver-xorg-core.
- Firmware: kept broad in the default ISO; after measuring ISO size, a `-firmware-lite` ISO variant may be offered later.
- Calamares: live-medium only; Calamares packages module (`packages.conf`) must be tested to ensure removing `live-boot*`, `calamares*`, `calamares-settings-debian`, and installer-artwork post-install does not remove shared dependencies required by the desktop. The packages list will be maintained explicitly (not "remove live-*" glob).
- `imagemagick`: only needed for Plymouth/GRUB theme rendering during build (build-time dependency) — remove from installed/live chroot after the hook runs, OR keep as a recommends of a graphics metapackage.
- `gvfs-backends`: review; `gvfs` is needed for removable media; individual backends (smb, afp, gphoto2, mtp, etc.) can be split out. Keep what's needed for USB drives/MTP cameras.

---

## 8. Improved testing plan

### 8.1 Test categories
Tests are separated into four tiers: (A) automated unit/static, (B) automated QEMU boot+install, (C) automated ISO build+validation, (D) manual hardware/USB.

### 8.2 Required tests for Phase 6
| # | Test | Tier | Notes |
|---|---|---|---|
| 1 | Default live USB boot (to shell) | B (QEMU) | Boots to desktop; shell mapped within 120 s (TCG) or 60 s (KVM) |
| 2 | Non-persistent USB boot | B (QEMU) | Reboot twice; verify no files persist |
| 3 | Persistent USB boot (home-only) | B (QEMU) | Create file on desktop, reboot, verify persistence |
| 4 | Copy-to-RAM boot with insufficient-memory protection | B (QEMU) | Boot with <1.5 GB RAM; expect clear failure message, not silent hang |
| 5 | Copy-to-RAM boot with sufficient memory | B (QEMU) | Boot with 3 GB; eject "ISO" mid-session; system stays up |
| 6 | Installation to internal storage | B (QEMU) | **Use ≥20 GB virtual disk** (per 16 GB Calamares requirement + headroom); EFI and BIOS variants; verify partitioning, GRUB install, user creation |
| 7 | First boot after installation | B (QEMU) | Installed system boots; no live user or live-boot present; polkit agent runs; system updates work (`apt update`) |
| 8 | Login and session startup (installed) | B (QEMU) | Greeter appears; credentials accepted; labwc session starts; lock/unlock via swaylock works |
| 9 | labwc desktop + application compatibility | B (QEMU) | Launch terminal, file manager, settings, Firefox; XWayland apps render; file dialogs open |
| 10 | USB shutdown and persistence integrity | B (QEMU + device flush test) | Write files during session, shut down cleanly, reboot, verify integrity; simulate unclean removal (QEMU quit without shutdown) once, verify fsck runs and persistence is mountable after |
| 11 | Actual ISO size | C | Fail build if ISO exceeds 2.0 GB; report exact size as artifact |
| 12 | Idle memory measurement | B (QEMU) | Capture metrics per §6.2; report per commit |
| 13 | Recovery from failed session startup | B (QEMU) | Break labwc config; verify fallback to TTY/recovery session, not a black screen |
| 14 | Boot time | B (QEMU) | GRUB → greeter and greeter → desktop measured per build; target: <60 s on KVM, <120 s on TCG |
| 15 | Package sync tests | A | Existing packaged-copies sync tests must still pass |
| 16 | Polkit authorization tests | A | All Phase 5 tests must still pass (no regression in security) |
| 17 | Shell suites root & nobody | A | 15 suites all pass |
| 18 | KWin recovery session | B (QEMU) | After moving KWin to optional, verify installing `bright-os-session-kde` produces a bootable selectable session |

### 8.3 QEMU environment notes
- **GitHub Actions runners (ubuntu-latest) do not support KVM** (Azure Ddsv5 series without nested virtualization at time of writing). Tests in CI will use TCG (software emulation). Expect boot times ~3–5× slower than hardware; set expectations accordingly in CI thresholds.
- KVM tests will be documented as requiring a self-hosted runner with `/dev/kvm` access; they produce more realistic measurements.
- Boot-only tests (boot to shell, check for expected D-Bus name) are separated from full installation tests to keep CI times manageable.
- Installation tests run on a **20 GB virtual disk** (Calamares requires 16 GB minimum; we use 20 GB to leave headroom for packages during install). Installation tests run less frequently (nightly or tag builds), not on every PR.
- Physical USB compatibility is NEVER claimed from QEMU results. USB 2.0 / USB 3.0 testing on real hardware remains a manual step; hardware test reports include exact USB stick models, machines, and measured boot/RAM numbers.

---

## 9. Revised implementation roadmap (corrected order)

Each sub-phase is its own PR with independent tests. KWin/SDDM remain installed and bootable until 6.2+6.3 pass their acceptance tests.

| Sub-phase | Scope | Exit criteria |
|---|---|---|
| **6.0** | CI scaffolding (GitHub Actions: static + unit + shell), baseline memory/boot measurement harness (QEMU, scripts that capture §6.2 metrics and post them as artifacts). No package changes. Add `.github/workflows/`. Add ISO size budget test. No ISO build yet (that needs live-build). | All existing tests pass on CI; baseline RAM/ISO numbers recorded against current main. |
| **6.1** | Minimal package restructuring. Move `linux-headers` out of default; trim packages whose removal is safe (plymouth-themes, imagemagick runtime, gnome-disk-utility to live-only, etc.). Add labwc, greetd, gtkgreet, layer-shell-qt, xdg-desktop-portal-wlr, swaylock, swayidle, mako as NEW packages (do not remove KWin/SDDM yet). Audit Qt6 QML module imports; remove unused modules. Start building a first test ISO. | ISO builds, boots in QEMU, existing KWin session still works; package set documented; size measured. |
| **6.2** | labwc proof-of-concept session. Add `bright-labwc.desktop` wayland session, session script, labwc rc.xml, autostart. Adapt shell minimally to register layer-shell surfaces. Keep KWin session working. DO NOT change default session yet. | PoC acceptance criteria in §4.3 all pass (manual + QEMU); KWin session still boots; RAM measured. |
| **6.3** | Shell + panel integration polish. Panel/dock exclusivity zones, launcher popups, notifications on correct layer, mako config, xdg-desktop-portal-wlr config, screen lock via swayidle/swaylock, logout/reboot/shutdown. Change default session from bright-kwin to bright-labwc for Lite. KWin/SDDM remain installed via the `bright-os-session-kde` and `bright-os-dm-sddm` packages. | Session boots by default; panel works; applications tile around panel; lock/logout works; KWin session remains selectable and functional. |
| **6.4** | USB persistence + boot configuration. Add new GRUB entries (§5.2); add live-boot `persistence`/`persistence-label`/`nopersistence`/`toram`/`persistence-media=removable-usb` flags; add `bright-persistence-setup` tool; add overlay fs-safe shutdown messaging. Implement home-only persistence first; add full-root as advanced option. Test each boot entry in QEMU. | Boot entries all tested in QEMU; home persistence round-trips; tool warns before modifying partitions; internal disks are never touched; toram fails gracefully on low RAM. |
| **6.5** | Calamares and installed-system compatibility. Trim live-only packages (Calamares, live-boot, live-config, installer branding, memtest, bright-persistence-setup) via Calamares `packages` module (tested — not globbing). Configure installed system for greetd + bright-labwc as default session (with KWin option retained if installed). Set ext4 default, btrfs as advanced option. Configure post-install autologin OFF by default (greetd prompts). Test BIOS + UEFI installs. | Installed system boots, greeter appears, login works, no live user present, no live-boot in initramfs, Calamares install completes on 20 GB disk, reboot works. |
| **6.6** | Optional metapackages and firstboot wizard. Build `bright-os-home-meta`, `bright-os-developer-meta`, `bright-os-android` (Waydroid + GUI integration), `bright-os-wine`, `bright-os-session-kde`, `bright-os-dm-sddm`, `bright-os-dm-lightdm`. Firstboot service offers optional components, firmware updates, Nvidia/AMD driver detection. | Metapackages install correctly; firstboot runs once, is idempotent, can be skipped. |
| **6.7** | Automated ISO builds and QEMU tests in GitHub Actions. Nightly builds produce an ISO artifact; PR validation builds a smaller test image (or does a package-only validation if ISO build is too slow). Integrate RAM/boot-size measurement scripts into CI. | Every PR runs static+unit+shell tests; nightly produces ISO with boot and RAM measurements posted. |
| **6.8** | Hardware compatibility and USB optimization. Run builds on physical USB 2.0/3.0 sticks; add `rootdelay=10` and related compatibility quirks only as non-default entries with clear labeling; test on low-spec hardware (≤4 GB RAM, dual-core); collect hardware-compat reports; tune zswap/zstd for low-RAM systems; firmware trimming ONLY after measuring. | Hardware test report; USB 2.0 boots in <120 s; low-RAM systems reach desktop and launch apps. |
| **6.9** | Actual memory/boot/ISO measurement pass on hardware. Run the §6.2 measurement protocol on reference hardware (low-spec, mid-spec, modern); iterate on remaining bottlenecks; final report documents measured vs target numbers. | Measured numbers for idle RAM, boot time, ISO size on ≥3 reference machines; gaps documented; further work triaged. |

---

## 10. Risks and unresolved questions

1. **layer-shell-qt depends on Qt6 and KDE infrastructure** — runtime deps are small but the package lives in the `kde/` section; we will verify at 6.1 that it does not pull in unwanted stack. If it does, alternatives are `waybar` (separate panel, C++) or writing a minimal Qt layer-shell client plugin ourselves (post-Phase 6).
2. **gtkgreet / greetd PAM configuration** needs to include `pam_systemd.so` for systemd user sessions to start correctly; otherwise XDG_RUNTIME_DIR and similar won't be set. Documented and tested at 6.2.
3. **Shell as a layer-shell surface** may need more refactoring than expected (panel/dock/launcher/desktop windows currently live in one QQuickView; layer-shell requires each surface to be a distinct window, or at least have layer/anchor properties). May need splitting the shell into panel + desktop + dock processes, or using separate layer-shell surfaces from one process.
4. **Home-only persistence** means APT updates, system settings changes, and application installs do not persist; users will expect a way to make system changes persist. Design a "create persistent system partition" option later (explicit, with size warning), but Phase 6 initial release only does `/home`.
5. **SDDM removal from the default session** must preserve recovery: if greetd breaks, the user must be able to select a failsafe session or install an alternative DM easily. We will ship a `text-login` target and document recovery in GRUB.
6. **Calamares displaymanager module** currently configures SDDM. We must either extend it to configure greetd, or replace that module step with a shellprocess that enables greetd and disables SDDM.
7. **ISO size target under 2 GB** is tight with broad firmware. If Lite with broad firmware exceeds 2 GB, we will measure and either trim non-firmware packages first or ship a `-firmware-lite` variant before touching firmware. Broad firmware remains the default until measurement shows what to cut.
8. **TCG emulation in CI is slow.** Installation tests may be too slow for PR feedback; we will separate boot-only smoke tests (<5 min) from full installation tests (nightly only).
9. **Bright Android on labwc/Wayland** needs testing — Waydroid should work on wlroots compositors generally, but clipboard integration, window management, and launcher shortcuts may need adjustments.
10. **No KVM in GitHub Actions** means performance numbers from CI are not representative of real hardware; all published idle RAM / boot time numbers must be from KVM or physical hardware, with CI numbers labeled as TCG.

---

## 11. Git and repository rules (restated for Phase 6)

- Working branch: `arena/phase6-lightweight-arch`.
- Each sub-phase is a separate reviewed PR; do not merge to `main` without approval.
- Keep `main` untouched except via PR merges.
- Do not force-push.
- Do not delete existing branches, clones, or hooks.
- Packaged source copies under `config/includes.chroot/` remain synchronized with their originals; do not remove them without proving they are no longer required.
- All Phase 5 security changes (AURA Polkit hardening, Bright Android async InstallApk, non-root tests, GUI lifecycle) are preserved; any change near them requires dedicated security review.
- GitHub Actions are approved and used in sub-phase 6.0 onward.

---

## 12. What I will do next after approval

After you approve this revised plan, I will begin **sub-phase 6.0 only** (CI scaffolding + baseline measurement tests + QEMU harness) as a separate PR. No package lists, boot entries, session scripts, or shell code will change in that PR — it adds `.github/workflows/` and the measurement/test harness only, so we can measure the baseline before making optimizations.

I will stop after each sub-phase PR for review.
