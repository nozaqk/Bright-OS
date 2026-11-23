# Phase Bright Android — Implementation Report (Updated: Phase 2 Bug Fixes)

**Branch:** `arena/e4dafc42-bright-os` (Phase 2 fixes)
**Original PR:** #35 (Phase 1 merged)
**Date:** 2026-11-20
**Status:** Code complete; real-hardware validation pending

## Phase 2 Summary

This phase fixes critical bugs in the initial Bright Android implementation
(#35) and adds hardware readiness assessment for the AMD A10-8700P target.

### Bugs Fixed

1. **Runtime status permanently false** (`gui.py` line 221)
   - Bug: `elif compat["running"] if False else False:` was always False
   - Fix: `run_full_check()` now returns a proper `running` bool from `waydroid_manager.is_running()`; the GUI's `refresh_status()` uses an async `StatusRefreshWorker` QThread to avoid blocking; status distinguishes not-installed / not-initialized / stopped / starting / running.

2. **memfd detection always true** (`compatibility.py` line 142)
   - Bug: `result["memfd_available"] = os.path.exists("/dev/ashmem") or True`
   - Fix: Real memfd detection via ctypes `syscall(SYS_memfd_create)` probe, kernel version fallback (>= 3.17), tmpfs check.

3. **Unauthorized `modprobe` from GUI**
   - Bug: `check_kernel_binder()` called `modprobe binder` directly
   - Fix: Removed. Checker reports `module_needs_loading=True` and provides a clear pkexec command as remediation. Module loading requires Polkit-authorized root.

4. **D-Bus PID/UID retrieval broken**
   - Bug: `bus.get_unix_process_id()` returns int directly, but code treated it as dict; `HAS_DBUS` gate blocked pid/uid retrieval even when a bus was passed.
   - Fix: Proper int handling; bus credential extraction no longer gated on HAS_DBUS.

5. **systemd unit blocked pkexec**
   - Bug: `NoNewPrivileges=yes` prevented pkexec (setuid root) from working.
   - Fix: Removed `NoNewPrivileges` (Polkit is the authorization gate). Added `ProtectKernelTunables=yes`, `ProtectKernelModules=yes`, `ProtectControlGroups=yes`, `RestrictSUIDSGID=no`.

6. **systemd ExecStart missing --session**
   - Bug: Service connected to system bus instead of session bus.
   - Fix: `ExecStart=/usr/bin/bright-android --service --session`.

7. **Missing ReadWritePaths**
   - Bug: `ProtectSystem=strict` would make /etc and /var read-only even for pkexec'd children (same mount namespace).
   - Fix: Added `/etc/waydroid /var/lib/waydroid` to ReadWritePaths.

8. **GUI thread blocked by subprocess calls**
   - Bug: 5-second auto-refresh timer called `run_full_check()` on GUI thread, invoking mount command, kernel config reads, `waydroid status`, and `waydroid app list`.
   - Fix: `StatusRefreshWorker` (QThread) runs checks off-GUI; `AppListWorker` for Applications page; 3-second status TTL cache in waydroid_manager; timer increased to 10 seconds.

9. **Package list errors**
   - Fixed: Removed nonexistent `binder-user-systemd` package; replaced with `binder-linux-module-dkms`; corrected misleading comments.

10. **APK install flow offered no recovery when stopped**
    - Fix: Install dialog now offers to start Android first, then chains to install.

### New Features

- **Hardware readiness assessment** (`assess_hardware_readiness()`): Returns three tiers (supported / supported_with_limitations / unsupported) with warnings, blockers, and recommendations.
- **Full system info in compatibility page**: CPU arch/cores/model, RAM (total+available), swap (total+free), GPU vendor/renderer/GL version, binder, memfd, Wayland.
- **8 GB RAM warning**: Prominent warning on HomePage when system has <=8 GB RAM about resource contention.
- **AMD Radeon R6 detection**: Specific warning about ~1 GB VRAM for 3D apps.
- **Status caching** in `waydroid_manager` (3-second TTL) to avoid repeated subprocess invocations.
- **Real Waydroid status parsing** (`_parse_status_output`) distinguishes RUNNING / STOPPED / STARTING states.
- **Clear separation of unit tests vs integration tests**: Integration tests are skipped unless `WAYDROID_INTEGRATION=1`.

## Files Modified in Phase 2

| Path | Change |
|------|--------|
| `bright_android/core/compatibility.py` | Rewrote: real memfd detection, binder state machine, CPU/swap/graphics checks, hardware readiness, removed modprobe, fixed always-true memfd |
| `bright_android/core/waydroid_manager.py` | Rewrote: status parsing, TTL caching, correct start/stop/init flow, actionable errors, proper pkexec usage, package name regex validation |
| `bright_android/core/android_service.py` | Fixed D-Bus PID/UID retrieval, improved _check_polkit |
| `bright_android/gui.py` | Fixed `if False` bug, added StatusRefreshWorker/AppListWorker QThreads, async refresh, proper button state, 8GB warning, install-start-chain, improved compatibility page |
| `bright_android/tests/test_bright_android.py` | 62 tests covering all fixed bugs + hardware readiness + systemd/polkit validation |
| `config/includes.chroot/usr/lib/systemd/user/bright-android.service` | Removed NoNewPrivileges, added --session, added /etc/waydroid + /var/lib/waydroid to ReadWritePaths, added ProtectKernel* hardening |
| `config/package-lists/android.list.chroot` | Fixed package names (binder-linux-module-dkms) |
| `docs/BRIGHT-ANDROID.md` | Updated requirements, binder remediation, 8GB notes |
| `docs/PHASE-BRIGHT-ANDROID-HARDWARE-READINESS.md` | New: AMD A10-8700P assessment, limitations, recommendations |

## Test Results

### Test Count Reconciliation
The previous implementation report cited 1,169 shell assertions, but some runs showed 1,155. The difference is **14 YAML validation tests** in `tests/test-installer.sh` that are **skipped** when `python3-yaml` (pyyaml) is not installed. When pyyaml is available, installer tests show 227 passed (vs 213 without).

| Environment | Shell assertions | Python tests |
|-------------|-----------------|--------------|
| Without pyyaml | 1155 passed | 233 AURA + 38/62 Bright Android |
| With pyyaml | **1169 passed** | 233 AURA + 62 Bright Android |

Skipped tests are NOT counted as passed (per requirements).

### Final Test Run (this environment, pyyaml installed)
- **233 AURA Python tests** — all pass
- **62 Bright Android Python tests** — 60 pass, 2 skipped (real Waydroid integration)
- **1169 shell test assertions** (15 suites) — all pass
- **compileall** — all modules compile
- **py_compile** — GUI compiles (cannot import-test without PyQt6 in sandbox)
- Polkit XML valid, D-Bus config valid
- Installer config: 227 passed
- Package lists: 15 passed, 0 warnings

### Coverage Areas
- ✅ Binder kernel detection (devices, config, module presence — no modprobe)
- ✅ memfd_create detection (ctypes probe, kernel version, tmpfs)
- ✅ Wayland session detection
- ✅ Graphics/renderer/OpenGL detection
- ✅ RAM (total/available/low-resource flags)
- ✅ Swap detection and warnings
- ✅ Disk space
- ✅ CPU architecture and core count
- ✅ APK validation (x86_64, universal, ARM-only, null bytes, path safety)
- ✅ Waydroid manager (argv lists, pkexec escalation, status parsing, package name validation)
- ✅ Runtime state machine (not-installed → not-initialized → stopped → starting → running)
- ✅ D-Bus PID/UID extraction (fixing dict-vs-int bug)
- ✅ Polkit authorization (root allow, invalid pid reject, fail-closed)
- ✅ Launcher integration (desktop entries, sync, removal)
- ✅ Config permissions (0600)
- ✅ Edition packaging (Lite excludes Android packages; Home/Developer include)
- ✅ systemd unit correctness (session bus, pkexec compatibility, ReadWritePaths)
- ✅ Polkit policy XML (admin for init/install-apk/remove-data; active user for start/stop/uninstall)
- ✅ AURA confirmation gating (mutating ops require confirmation)
- ✅ Hardware readiness tiers (supported/limited/unsupported)
- ✅ 8 GB RAM warnings
- ✅ Subprocess never uses shell=True

## Known Limitations
- End-to-end Waydroid validation requires a provisioned Debian machine with network access (sandbox egress blocks Debian mirrors — same constraint as Phase 19).
- PyQt6 GUI cannot be import-tested without PyQt6 in sandbox; follows existing bright-settings pattern and compiles cleanly.
- ARM translation is not bundled (licensing); ARM-only APKs are clearly rejected.
- Calamares netinstall entry is deferred (Android installs post-install via apt + GUI).

## Security Model Preserved
- No shell=True anywhere; all subprocess calls use argv lists
- No modprobe from unprivileged GUI
- No auto-start at login (default)
- Polkit required for init/install-apk/remove-data
- NoNewPrivileges removed ONLY because it blocked pkexec; other sandboxing preserved (ProtectSystem, ProtectHome, PrivateTmp, ProtectKernel*)
- Config files 0600
- APK paths validated for null bytes, extension, size
- Package names validated via regex before passing to waydroid
- AURA cannot bypass Polkit or perform root operations without user consent
