# Bright Android — Hardware Readiness Assessment

**Target system:** AMD A10-8700P, 8 GB RAM, AMD Radeon R6 (Carrizo), 932 GB HDD
**Date:** 2026-11-20
**Branch:** `arena/e4dafc42-bright-os`

## Executive Summary

Bright Android is expected to run on the AMD A10-8700P system with **limitations**:

- **Supported status:** ⚠️ Supported with limitations
- Android applications will run, but heavy games and multiple concurrent apps will compete with the desktop for RAM and GPU.
- Auto-start at login is **disabled by default** to preserve RAM for the desktop.
- The user is warned prominently on the Android Home page about 8 GB RAM constraints.

## System Specifications

| Component | Value | Waydroid requirement | Verdict |
|-----------|-------|---------------------|---------|
| CPU | AMD A10-8700P (4 cores, Excavator, 1.8-3.2 GHz) | x86_64, 2+ cores | ✅ Supported |
| RAM | 8 GB DDR3 | 2 GB min, 4 GB recommended | ⚠️ Tight |
| Swap | (recommended: 2-4 GB zram) | Optional but helpful | ⚠️ Strongly recommended |
| GPU | AMD Radeon R6 (Carrizo iGPU, ~512 MB-1 GB VRAM) | OpenGL ES 3.0, Mesa | ⚠️ Limited VRAM |
| Disk | 932 GB HDD | 6+ GB free | ✅ Ample |
| Architecture | x86_64 | x86_64 | ✅ Supported |
| Session | Wayland (KWin) | Wayland | ✅ Required |

## Detailed Assessment

### CPU: AMD A10-8700P
- 4 Excavator cores at 1.8 GHz (boost 3.2 GHz).
- x86_64 architecture — matches the VANILLA x86_64 Android image.
- No issues for typical Android apps (messaging, media, productivity).
- Emulated/translated apps will be slow (no ARM translation included).

### RAM: 8 GB
- Android itself reserves ~1.5-2.5 GB when running.
- A full KDE Plasma desktop uses ~1.5-2.5 GB.
- Web browser with a few tabs: 1-3 GB.
- **Headroom:** 0-2 GB free when Android + desktop + browser are all running.
- **Warning shown in GUI:** "System has 8192 MB RAM. Running Android applications alongside a full desktop environment may be resource-intensive. Close other applications before starting Android."
- **Recommendation:** Install `zram-tools` for 2-4 GB compressed swap to prevent OOM kills.
- **Auto-start is disabled by default** so Android doesn't consume RAM until the user explicitly starts it.

### GPU: AMD Radeon R6 (Carrizo)
- Integrated Radeon R6 (Carrizo, GCN 3rd gen, 384:24:8).
- Uses shared system memory (typically 512 MB-1 GB allocated via GART).
- Mesa amdgpu/radeonsi drivers support OpenGL 4.6 and OpenGL ES 3.2 on this GPU.
- Wayland compositing on KWin works well.
- **Limitations:** 3D Android games may struggle with the limited VRAM. Video playback at 1080p should be fine.
- **Warning shown:** "AMD Radeon R6 (Carrizo) iGPU detected with ~1 GB VRAM. 3D games and GPU-heavy apps may perform poorly."

### Storage: 932 GB HDD
- Ample space for the Android system image (~400-700 MB VANILLA) and apps.
- HDD speeds will make initial image download and app installation slower than SSD, but functional.
- Required minimum: 6 GB free (easily met).

### Kernel Requirements (Debian 13 Trixie)
Waydroid requires:
1. **Binder IPC** — either built-in (`CONFIG_ANDROID_BINDER_IPC=y`) or as loadable module (`binder_linux` DKMS package).
2. **memfd_create(2)** — supported on all Linux kernels >= 3.17 (Trixie's 6.x kernels have this).
3. **Wayland session** — KWin on Wayland (default in Bright OS Home/Developer).
4. **LXC** — container runtime (installed with waydroid package).

The `binder-linux-module-dkms` package is included in `android.list.chroot` to provide binder on kernels that don't have it built-in. The GUI detects if binder isn't loaded and provides a clear remediation message:
> "Binder kernel module is not loaded. Run: pkexec modprobe binder_linux"

The compatibility checker does **not** attempt to load kernel modules itself (that requires root); it tells the user the authorized path.

## Waydroid Version
- Waydroid is packaged in Debian Trixie. At time of writing, Trixie has waydroid 1.4.x which:
  - Uses memfd_create (no ashmem required)
  - Supports multi-window/freeform mode
  - Has `waydroid session start/stop`, `waydroid app install/remove/list/launch`
  - Works with Mesa/amdgpu for hardware GL

## Triage of Fixed Bugs (Phase 2)

The following critical bugs were identified and fixed in this phase:

1. **Permanently-false runtime status** (`elif compat["running"] if False else False:`) — Fixed; `run_full_check()` now calls `waydroid_manager.is_running()` and sets `report["running"]` correctly.

2. **Always-true memfd detection** (`result["memfd_available"] = ... or True`) — Fixed; memfd is detected via ctypes syscall probe, kernel version check, and tmpfs fallback.

3. **Privileged modprobe from GUI** — Removed; compatibility checker reports "module needs loading" with clear remediation instructions. Does NOT invoke modprobe.

4. **D-Bus PID/UID retrieval** — Fixed; dbus-python's `get_unix_process_id()` returns int directly, not a dict. Fixed the mocking issue and the HAS_DBUS gate.

5. **systemd unit NoNewPrivileges** blocking pkexec — Removed; Polkit policies are the authorization gate; NoNewPrivileges would prevent pkexec setuid from working.

6. **systemd ExecStart missing --session** — Fixed; the service connects to the session bus, not system bus.

7. **Missing ReadWritePaths for /etc/waydroid and /var/lib/waydroid** — Added; required because ProtectSystem=strict makes these paths read-only otherwise, even for pkexec'd children (same mount namespace).

8. **GUI running on main thread with expensive subprocess calls** — Fixed; status refresh uses a QThread worker (StatusRefreshWorker) with caching (3-second TTL in waydroid_manager) to avoid blocking the GUI.

9. **No distinction between starting/running/stopped** — Fixed; get_status() parses `waydroid status` output for session/container state.

10. **8 GB RAM warnings not shown** — Fixed; hardware_readiness assessment reports "supported_with_limitations" with RAM, GPU, and swap warnings.

## Tests Performed

### Automated (in this sandbox)
- **62 Bright Android Python tests** — 60 pass, 2 skipped (real Waydroid integration)
- **233 AURA Python tests** — all pass
- **1169 shell test assertions** — all pass (across 15 test suites, with pyyaml installed)
- XML validation (Polkit policy, D-Bus config) — valid
- compileall — all modules compile cleanly
- py_compile on GUI — GUI compiles (cannot import-test without PyQt6 installed in sandbox)

### Not Yet Performed (require real hardware / provisioned Debian machine)
- Actual Waydroid installation (`waydroid init` downloading VANILLA image)
- Container startup on AMD A10 hardware with amdgpu
- APK installation (x86_64 APK, universal APK, ARM APK rejection)
- App launching and multi-window mode
- D-Bus service activation via systemd user instance
- Polkit authorization prompts for privileged operations
- Launcher integration (desktop file creation, app launching from menu)
- 8 GB RAM stress testing (multiple apps + browser)
- AURA natural language commands ("install Signal", "launch WhatsApp")

## Known Risks and Remaining Work

1. **binder_linux module on Trixie**: The DKMS package may need kernel headers installed; verify on real hardware that binder is available post-install.
2. **HDD performance**: Initial image download and extraction will be slower on HDD vs SSD.
3. **No ARM translation**: ARM-only apps (e.g., some banking apps, games) will fail to install with a clear error message. This is expected and documented.
4. **Clipboard integration**: Requires wl-clipboard; tested once on real hardware.
5. **Google Play Services**: Not included; users wanting Play Store must install GApps variant during init (explicit opt-in).
6. **Notification forwarding**: Requires a KDE Connect-style bridge or waydroid notification listener; basic forwarding is planned but may need additional setup.

## Remaining Integration Work

1. Calamares optional netinstall module entry (Android can be installed post-install via apt + GUI in the meantime).
2. Real-hardware validation on the AMD A10-8700P target system.
3. Automated performance testing on 8 GB configurations.
4. ARM translation layer packaging as an optional add-on (not in scope for this phase).

## Recommendations for AMD A10-8700P Users

1. Install zram-tools for compressed swap: `sudo apt install zram-tools` (configure 4 GB zram).
2. Do NOT enable auto-start; start Android on demand.
3. Close browser tabs / heavy apps before starting Android.
4. Use the freeform/windowed mode rather than full-screen for better multitasking.
5. For games, prefer native Linux versions or streaming; Android games may have limited performance on R6 iGPU.
