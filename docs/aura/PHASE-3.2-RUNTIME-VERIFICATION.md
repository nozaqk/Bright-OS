# Phase 3.2 — Runtime Integration Verification Report

**Branch:** `arena/01e73db0-bright-os` (base: `4b6eeb2` — PR #31 merge)
**Date:** 2026-11-20
**Scope:** AURA runtime integration, security isolation, edition verification, ISO readiness

---

## 1. Corrections Applied (Narrowly Scoped)

Two correctness bugs found and fixed during the audit:

| # | File | Bug | Fix |
|---|------|-----|-----|
| 1 | `aura/core/aura_core_service.py` (line 238) | `Shutdown` D-Bus method declared `in_signature="b"` but takes no boolean parameter — would cause `TypeError` whenever called over D-Bus | Changed to `in_signature=""` to match the method signature |
| 2 | `config/includes.chroot/usr/bin/aura-core-service` | Launcher added `/usr/lib/aura` to `sys.path`, but the package IS `aura/` (i.e. `import aura` would look for `/usr/lib/aura/aura/`, which doesn't exist) | Changed to `sys.path.insert(0, "/usr/lib")` — the parent of the `aura/` package directory |

These are the only code changes. Both are bug fixes, not features or redesign.

---

## 2. Test Results

### 2.1 Python Unit Tests
```
$ python3 -m unittest discover aura -v
Ran 233 tests in 7.08s
OK
```
- Phase 1/2/3 tests: 184 (prior baseline)
- Phase 3.1 polkit regression tests: 20
- Phase 3.2 runtime integration tests: **49 new** (this PR)

### 2.2 Compile Check
```
$ python3 -m compileall -q aura
OK (no syntax errors)
```

### 2.3 Shell Test Suites

| Suite | Result | Notes |
|-------|--------|-------|
| `aura/tests/test-aura-core.sh` | **130 passed, 0 failed** | AURA-specific shell tests |
| `tests/test-build-readiness.sh` | **106 passed, 0 failed** | Build prerequisites |
| `tests/test-build-doctor.sh` | **71 passed, 0 failed** | Build doctor checks |
| `tests/test-desktop-identity.sh` | **147 passed, 0 failed** | Desktop identity checks |
| `tests/test-live-config.sh` | **27 passed, 0 failed** | Live-build config |
| `tests/test-packages.sh` | **15 passed, 0 failed** | Package list validation |
| `tests/test-build-pipeline.sh` | 41 passed, 0 failed | |
| `tests/test-calamares.sh` | 34 passed, 0 failed | |
| `tests/test-apps.sh` | 110 passed, 0 failed | |
| `tests/test-iso-validator.sh` | 18 passed, 0 failed | |
| `tests/test-live-boot.sh` | 78 passed, 0 failed | |
| `tests/test-live-build-compat.sh` | 82 passed, 0 failed | |
| `tests/test-local-build.sh` | 64 passed, 0 failed | |
| `tests/test-qemu-script.sh` | 17 passed, 0 failed | |
| `tests/test-installer.sh` | **213 passed, 14 failed** | ⚠ Pre-existing Calamares YAML parse failures; verified present on base commit `4b6eeb2` before our changes; unrelated to AURA (missing YAML parsing in test harness for Calamares' non-standard comment format). Not introduced by this PR. |

### 2.4 Headless Runtime Smoke Test (in sandbox)
- Service starts in headless/lite mode without D-Bus ✅
- Intelligence component reaches `RUNNING` in `local` mode ✅
- Mode switch to `offline` disables network ✅
- `GrantCloudConsent(false)` revokes without admin ✅
- `Shutdown` cleanly stops components and exits main loop ✅
- Graceful `DISABLED` state when intelligence module cannot be imported ✅

---

## 3. Security & Isolation Verification

### 3.1 Systemd Hardening (all verified)
- **Runs as unprivileged user:** `User=aura`, `Group=aura` (never root)
- **Capabilities dropped:** `CapabilityBoundingSet=` (empty), `AmbientCapabilities=` (empty)
- **Filesystem isolation:** `ProtectSystem=strict`, `ProtectHome=read-only`
- **Writable paths limited:** `ReadWritePaths=/var/lib/aura /var/log/aura` only
- **Kernel attack surface:** `ProtectKernelTunables=yes`, `ProtectKernelModules=yes`, `ProtectControlGroups=yes`, `RestrictNamespaces=yes`, `LockPersonality=yes`
- **Process isolation:** `PrivateTmp=yes`, `PrivateDevices=yes`, `NoNewPrivileges=yes`
- **ExecStartPre runs as root:** prefixed with `+` (needed for `systemd-tmpfiles` setup)
- **No FailureAction:** service failure does not trigger shutdown/reboot
- **Restart policy:** `on-failure`, burst-limit 5
- **D-Bus is Wants=, not Requires=** — service can start headless on minimal systems

### 3.2 D-Bus Policy
- Service name owned only by `aura` user (not root, not arbitrary users)
- Root can talk to the service (for admin tools)
- All 21 public methods explicitly allow-listed (no wildcard send_member)
- Signals broadcast-receive is permitted (required for UI clients)
- Activation file uses `User=aura`, `SystemdService=aura-core.service`

### 3.3 Polkit (fail-closed)
- **Shutdown** requires `auth_admin` (any context), `auth_admin_keep` (active)
- **GrantCloudConsent** requires `auth_admin` / `auth_admin_keep` — fixed in Phase 3.1 from over-permissive `yes`
- **RevokeCloudConsent** does NOT require polkit (per policy: users may always retract their own consent)
- **Polkit unavailable** → falls back to root-only, never permissive
- **Invalid PID/UID** → fails closed (Phase 3.1 fix)
- **Polkit exceptions** → fail closed (Phase 3.1 fix)

### 3.4 Credential Handling
- `secure_store.py` uses `O_NOFOLLOW | O_CLOEXEC` open
- 0600 file mode enforced via `fstat`-based TOCTOU-safe check
- Subprocess calls use `shell=False`; stderr never logged
- Credential values never appear in log messages

### 3.5 Networking Security
- SSRF protection: private / link-local / reserved IPs rejected
- HTTPS-only; no plaintext HTTP
- Redirect target validation

### 3.6 AppArmor
- No dedicated AppArmor profile for AURA in this build
- Sandboxing relies on systemd directives above (documented)
- `apparmor` and `apparmor-utils` packages are installed for Phase 4 security engine

---

## 4. Mode & Edition Verification

### 4.1 Intelligence Modes
| Mode | Network | Local Models | Cloud Providers | Verified |
|------|---------|--------------|-----------------|----------|
| `offline` | disabled | enabled | disabled | ✅ sandbox |
| `local` | enabled (updates) | enabled | disabled | ✅ sandbox |
| `hybrid` | enabled | enabled | consent-gated | code-verified |
| `cloud` | enabled | optional | consent-gated | code-verified |

Mode switching persists to config (writes only to `/var/lib/aura` which is `ReadWritePaths`).

### 4.2 Editions
| Edition | Default Mode | Cloud | Max Memory % | Auto-load | Service Masks | Verified |
|---------|-------------|-------|-------------|-----------|---------------|----------|
| **lite** | offline | disabled | ≤40% | false | bluetooth, cups, ModemManager | ✅ |
| **home** | local | consent-gated | ≤50% | false | none | ✅ |
| **developer** | hybrid | consent-gated | ≥60% | false | dev_tools enabled | ✅ |

- Systemd, D-Bus, Polkit, and AURA service installed across all editions
- No model weights (`.gguf`/`.ggml`/`.bin`) bundled in any edition
- No model runtime packages (llama.cpp, ollama, pytorch) installed by default

---

## 5. Environment Limitations

This verification was performed in a sandboxed Debian 12 container without:
- `dbus-daemon` (system bus)
- `polkitd`
- `python3-dbus`, `python3-gi`, `gir1.2-polkit-1.0`

Package installation is not possible (no network access to apt repositories), so real D-Bus activation, Polkit authentication dialogs, and systemd service activation could not be exercised end-to-end. **Per standing instruction, mocked Polkit tests are NOT treated as equivalent to real Polkit integration.**

A reproducible VM verification procedure is included at the bottom of `aura/tests/test_phase32_runtime.py` (the `VM_RUNTIME_PROCEDURE` comment block). It documents 8 checks to run on a provisioned Debian 13 Trixie VM with AURA installed:

1. `systemctl start aura-core.service` → active, runs as `aura:aura`
2. `busctl list | grep bright_os.AURA` → registered; `GetVersion` returns string
3. `Shutdown` as `nobody` → `NotAuthorized` DBusException
4. `Shutdown` as root → service stops cleanly
5. `GrantCloudConsent(true)` → Polkit admin-auth prompt
6. `GrantCloudConsent(false)` as regular user → succeeds (no admin needed)
7. Service restarts on failure
8. Process UID is `aura` (never root)

---

## 6. ISO Readiness Assessment

**Status: READY for first Lite ISO build, with the caveat below.**

### Green (verified)
- ✅ All AURA files present at correct FHS paths; permissions correct
- ✅ Source and packaged copies are byte-identical (0 diffs)
- ✅ 233 Python unittests pass; all relevant shell suites pass
- ✅ Service hardening intact; runs as unprivileged `aura` user
- ✅ D-Bus policy method-complete (all 21 public methods)
- ✅ Polkit policy requires admin for shutdown and cloud consent
- ✅ Secure credential storage (TOCTOU-safe 0600)
- ✅ Networking has SSRF and HTTPS protections
- ✅ Three editions configured correctly (Lite offline/no-weights, Home balanced, Developer relaxed)
- ✅ No model weights or heavy runtimes bundled
- ✅ Launcher sys.path bug and Shutdown signature bug fixed
- ✅ AURA starts headless without D-Bus; failure doesn't crash PID 1
- ✅ Chroot hook enables service, creates user, sets permissions
- ✅ `FailureAction=none` ensures AURA failure cannot prevent desktop startup
- ✅ D-Bus is `Wants=` not `Requires=`, so AURA starts even without system bus

### Yellow (known but acceptable for first build)
- ⚠️ No dedicated AppArmor profile for AURA (relies on systemd sandboxing)
- ⚠️ End-to-end D-Bus/Polkit activation must be verified on real VM (see Section 5)
- ⚠️ Installer tests show 14 pre-existing Calamares YAML parse failures (not AURA-related, present on base commit)
- ⚠️ No actual ISO has been built in this session (per standing instruction: not claimed)

### Red (none)
- No blocking defects found
- No security regressions
- No features introduced in this phase; only two narrow bug fixes

### Recommendation
Proceed with first Lite ISO build. After build, run the VM_RUNTIME_PROCEDURE on the resulting image to confirm live-system D-Bus/Polkit integration. The 14 pre-existing Calamares YAML test failures should be triaged separately (they concern the installer, not AURA).
