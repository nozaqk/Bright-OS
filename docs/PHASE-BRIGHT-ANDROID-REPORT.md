# Phase Bright Android — Implementation Report (Updated: Phase 2.1 Security Fix)

**Branch:** `arena/01bb330c-bright-os` (Phase 2.1)
**Original PR:** #35 (Phase 1 merged), #36 (Phase 2 merged)
**Date:** 2026-11-20 (Phase 2.1 update: 2026-11-23)
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

---

## Phase 2.1: D-Bus Authorization Security Fix

Phase 2.1 hardens the D-Bus authorization model to remove the session-bus
implicit-trust bypass, validate every caller's identity, and separate
authentication (Polkit) from user-facing confirmation (AURA).

### Security Issues Fixed

1. **Session-bus implicit trust bypass removed**
   - Old code: `if sender is None: return True, "session bus implicit trust"`.
     On the session bus dbus-python always supplies a sender; however the
     `sender=None` fallback was reachable via internal calls and constituted
     a confused-deputy risk. Removed. Every method now requires a valid
     sender (or `bus=None` for explicit in-process calls, which is not
     reachable from a remote D-Bus peer because dbus-python always supplies
     a bus object for dispatched methods).

2. **Wrong D-Bus credential API corrected**
   - Old code used `bus.get_unix_process_id()` / `bus.get_unix_user_id()`
     (non-existent methods that raise AttributeError and fell through to the
     implicit-trust bypass). The correct dbus-python API is
     `bus.get_connection_unix_process_id(sender)` /
     `bus.get_connection_unix_user(sender)`, which raise DBusException for
     unknown senders. The fix uses the correct methods with broad exception
     handling so any credential failure results in denial.

3. **Other-local-account access vector closed**
   - Same-UID enforcement: caller UID must match service UID (or be root).
     Other local users connecting to the same session bus (e.g. via a leaked
     `DBUS_SESSION_BUS_ADDRESS`) cannot control the active user's Android
     environment.

4. **Polkit actions added for LaunchApp/SyncAppList/SetConfig**
   - Previously `LaunchApp` and `SyncAppList` had no auth checks at all and
     `SetConfig` incorrectly used the START action. Added three new action
     constants: `POLKIT_ACTION_SET_CONFIG` (auth_admin_keep),
     `POLKIT_ACTION_LAUNCH` (allow_active=yes),
     `POLKIT_ACTION_SYNC` (allow_active=yes).

5. **Polkit policy hardened**
   - All admin/destructive actions (init, install-apk, set-config) require
     `auth_admin_keep`; remove-data requires `auth_admin` (no caching for
     data destruction). Session-user actions (start/stop/uninstall/launch/
     sync) use `allow_active=yes`. No action grants `allow_any=yes`.

6. **Fail-closed when Polkit unavailable**
   - If Polkit is unavailable and the caller is not root (and the action
     does not allow same-user), the call is denied.

7. **Read-only methods now check auth**
   - GetVersion, GetCompatibilityReport, GetStatus, GetConfig, ListApps,
     ValidateApk, and GetDiagnostics all now verify the caller's identity
     (same-UID only; no Polkit prompt).

8. **NoNewPrivileges trade-off documented**
   - The systemd unit retains the absence of NoNewPrivileges because pkexec
     needs setuid. A detailed comment block explains the trade-off, the
     existing layers of defense (Polkit + same-UID), and a concrete
     follow-up plan (narrow pkexec helper, then re-enable
     NoNewPrivileges). Additional hardening directives added:
     RestrictNamespaces=yes, RestrictRealtime=yes, LockPersonality=yes,
     MemoryDenyWriteExecute=no (Python JIT/W^X), SystemCallArchitectures=native.

### Authorization Decision Flow

```
D-Bus method call (sender, bus present)
  │
  ├─ bus=None or HAS_DBUS=False          ──► ALLOW (in-process / headless)
  ├─ sender is None                       ──► DENY
  ├─ credentials unobtainable             ──► DENY (fail closed)
  ├─ invalid pid/uid                      ──► DENY
  ├─ uid == 0 (root)                      ──► ALLOW
  ├─ uid != service UID                   ──► DENY (other local user)
  ├─ allow_same_user=True (read/user)     ──► ALLOW
  ├─ Polkit unavailable                   ──► DENY (fail closed)
  └─ Polkit.check_authorization_sync()
        ├─ is_authorized=True             ──► ALLOW
        ├─ is_challenge=True              ──► DENY (auth required)
        └─ else                            ──► DENY
```

### Files Modified in Phase 2.1

| Path | Change |
|------|--------|
| `bright_android/core/android_service.py` | Removed implicit-trust bypass; fixed dbus-python credential API; added same-UID enforcement via `SERVICE_UID`; added `POLKIT_ACTION_SET_CONFIG/LAUNCH/SYNC`; renamed `_check_polkit` to `_check_authorization` with `allow_same_user` parameter; all 15 D-Bus methods now call `_check_authorization`; fail-closed on credential or Polkit failure; SetConfig uses correct action; LaunchApp/SyncAppList now require auth; backwards-compat alias retained |
| `config/includes.chroot/usr/share/polkit-1/actions/org.bright_os.BrightAndroid.policy` | Added set-config, launch-app, sync-apps actions; comment documenting the authorization model; no action uses allow_any=yes; admin actions auth_admin_keep; remove-data auth_admin |
| `config/includes.chroot/usr/lib/systemd/user/bright-android.service` | Detailed block comment documenting NoNewPrivileges trade-off and future helper plan; added RestrictNamespaces/Realtime/LockPersonality/SystemCallArchitectures hardening; rephrased comments to avoid literal directive strings |
| `bright_android/tests/test_bright_android_auth.py` | **New**: 49 auth regression tests (AuthorizationTests, SecurityRegressionTests, MethodSourceAuthTests, PolkitPolicyTests, SystemdSecurityTests) + 2 skipped real-D-Bus integration tests |
| `bright_android/tests/test_bright_android.py` | Updated 3 SecurityValidationTests to use new `_check_authorization` API with correct dbus method names; updated `test_service_does_not_block_pkexec` to ignore comment lines |
| `docs/BRIGHT-ANDROID.md` | Rewrote Security Model section with authorization flow, Polkit action matrix, authentication-vs-confirmation, systemd hardening details |

### Test Results (Phase 2.1 final)

| Suite | Passed | Failed | Skipped |
|---|---|---|---|
| AURA Python tests | 233 | 0 | 0 |
| Bright Android Python tests | 109 | 0 | 4 (real Waydroid + D-Bus integration) |
| Installer shell tests (pyyaml) | 227 | 0 | 0 |
| **Total** | **569** | **0** | **4** |

Skipped tests are real-system integration tests (Waydroid runtime + live
D-Bus/Polkit) that require a provisioned Debian machine with the service
running. They are gated by `WAYDROID_INTEGRATION=1` and
`BRIGHT_ANDROID_REAL_INTEGRATION=1` and are NOT counted as passed per the
standing rule.

**Environment note:** The sandbox lacks `python3-dbus` and `python3-gi`;
production behavior (HAS_DBUS=True, HAS_POLKIT=True) is exercised via mocks
and source-level inspection. Real D-Bus/Polkit integration is covered by
the skipped `RealDBusIntegrationTests` class.

### Coverage for 11 Required Scenarios

| # | Scenario | Tests |
|---|----------|-------|
| 1 | Missing sender denied | `test_missing_sender_is_denied`, `test_no_implicit_trust_bypass_in_source` |
| 2 | Invalid pid/uid denied | `test_missing_pid_is_denied`, `test_missing_uid_is_denied`, `test_invalid_pid_type_denied`, `test_negative_pid_denied`, `test_zero_pid_denied`, `test_negative_uid_denied` |
| 3 | Other local user denied | `test_other_user_denied_for_admin_action`, `test_other_user_denied_for_same_user_action` |
| 4 | Root caller allowed | `test_root_is_always_allowed` |
| 5 | Same user allowed for read/session actions | `test_same_user_allowed_for_read_actions`, `test_same_user_allowed_for_launch` |
| 6 | Polkit unavailable fail-closed (non-root) | `test_polkit_unavailable_fails_closed_for_non_root` |
| 7 | Polkit authorized → allow | `test_polkit_authorized_allows` |
| 8 | Polkit challenge → deny | `test_polkit_challenge_denied` |
| 9 | Polkit error → deny | `test_polkit_error_denied`, `test_polkit_not_authorized_denied` |
| 10 | All 15 D-Bus methods invoke authorization with correct action IDs | `test_all_dbus_methods_call_check_authorization` + 12 per-method `MethodSourceAuthTests` |
| 11 | systemd hardening preserved; NoNewPrivileges trade-off documented | `test_hardening_directives_present`, `test_no_nonewprivileges_active_directive`, `test_nonewprivileges_tradeoff_documented`, `test_readwrite_paths_for_waydroid`, `test_exec_uses_session_bus` |

Additional regression checks: no `shell=True` in any core module; correct
dbus-python credential method names (`get_connection_unix_process_id` /
`get_connection_unix_user`, not the old buggy names); Polkit XML has no
`allow_any=yes` and correct auth levels per action.
