# Phase 18 — First Genuine ISO Build: Completion Report

**Branch:** `arena/fac052da-bright-os`
**Base commit:** `91bbc5757fd761fc9ceefad954027e42acba24a5` (main, after PRs #30, #31, #32 merged)
**Date:** 2026-11-23
**PR:** #33

---

## 1. Exact Git Commit Used

`91bbc5757fd761fc9ceefad954027e42acba24a5` (main HEAD) + two fix commits on branch:
- `495039f` — fix(tests): report missing pyyaml instead of false YAML parse failures
- `b633b16` — fix(build-doctor): warn when python3-yaml is missing for tests

## 2. Build Doctor Results

```
Passed:   35
Warnings: 12
Failed:   16
STATUS: NOT READY
```

### Passed (35)
- Debian OS detected (Bookworm; Trixie cross-build possible)
- amd64 architecture supported
- sudo (passwordless)
- Internet connectivity (ping + DNS)
- sha256sum found
- All 28 required project configuration files present (live-build auto scripts, package lists, hooks, branding, desktop shell, installer configs, edition packages)
- No existing Lite ISO (clean start)

### Warnings (12)
- Debian 12 Bookworm host (Trixie native recommended)
- 2 CPU cores (build will be slow)
- 3.8 GB RAM (below 4 GB minimum threshold; may OOM)
- No swap space (critical for <8 GB RAM)
- 19 GB disk (below 25 GB recommended)
- shim-signed, grub-efi-amd64-signed, ovmf, qemu-system-x86, qemu-utils, file not installed
- /dev/kvm not available (QEMU TCG software emulation only)

### Failed (16)
- **Cannot reach deb.debian.org** (HTTP: empty reply; HTTPS: TLS reset)
- **Cannot reach security.debian.org**
- Missing tools: lb (live-build), debootstrap, mksquashfs, xorriso, isolinux, syslinux-common, syslinux-efi, mtools, dosfstools, genisoimage, grub-pc-bin, grub-efi-amd64-bin, isoinfo
- live-build capability check (lb not found)

## 3. Complete Automated Test Results

### Python Tests
```
$ python3 -m unittest discover aura
Ran 233 tests in 7.1s
OK

$ python3 -m compileall -q aura
OK
```

### Shell Test Suites (all passing)

| Suite | Passed | Failed |
|-------|--------|--------|
| aura/tests/test-aura-core.sh | 130 | 0 |
| tests/test-build-readiness.sh | 106 | 0 |
| tests/test-build-doctor.sh | 71 | 0 |
| tests/test-desktop-identity.sh | 147 | 0 |
| tests/test-live-config.sh | 27 | 0 |
| tests/test-packages.sh | 15 | 0 |
| tests/test-apps.sh | 110 | 0 |
| tests/test-build-pipeline.sh | 41 | 0 |
| tests/test-calamares.sh | 34 | 0 |
| tests/test-installer.sh | **227** | **0** (was 213/14 failures before fix) |
| tests/test-iso-validator.sh | 18 | 0 |
| tests/test-live-boot.sh | 78 | 0 |
| tests/test-live-build-compat.sh | 82 | 0 |
| tests/test-local-build.sh | 64 | 0 |
| tests/test-qemu-script.sh | 17 | 0 |
| **Total shell tests** | **1167** | **0** |

### Calamares YAML Failures: Root Cause and Fix
The 14 previously reported Calamares YAML failures were **false positives from the test harness**, not installer defects.

**Root cause:** `tests/test-installer.sh` validated YAML with:
```bash
python3 -c "import yaml; yaml.safe_load(open('$file'))" 2>/dev/null
```
When `python3-yaml` (PyYAML) was not installed, the `import yaml` raised `ModuleNotFoundError`, which was silently swallowed by `2>/dev/null`. Every YAML file was then reported as "YAML parse error" even though the files themselves were perfectly valid.

**Verification:** After installing PyYAML (`pip3 install pyyaml`), all 24 Calamares YAML files (both in `installer/calamares/` and the chroot-installed copies) parse correctly with zero errors.

**Fix applied:**
1. `tests/test-installer.sh`: Detect missing pyyaml once at startup; print a clear warning; skip YAML validation tests with `[WARN]` instead of false `[FAIL]`; include actual parser error messages when validation genuinely fails; added `warn()` function and `WARN_COUNT` counter.
2. `build/scripts/bright-build-doctor.sh`: Added python3-yaml availability check so future users are warned before running tests.

All Calamares configuration files are valid YAML and correctly configured (branding: bright-os, LUKS support, module ordering correct, displaymanager, packages, initramfs, umount-last).

## 4. ISO File Location and Size

**NOT PRODUCED.** The build environment cannot access Debian mirrors, so `lb build` cannot download the ~2–4 GB of .deb packages required to populate the live filesystem chroot.

Expected output path (on a properly provisioned system):
```
build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

## 5. SHA256 Checksum

Not applicable — no ISO produced.

## 6. BIOS Boot Result

Not tested (no ISO to boot; isolinux.bin not available in environment).

## 7. UEFI Boot Result

Not tested (no ISO to boot; OVMF and grub-efi-amd64-bin not available in environment).

## 8. Live Desktop Result

Not tested (no bootable ISO).

## 9. Installer Result

Installer configuration verified statically:
- All 24 Calamares YAML files parse correctly
- Module sequence is correct (partition → mount → unpackfs → packages → luksbootkeyfile → initramfscfg → initramfs → grubcfg → bootloader → shellprocess-post → umount)
- Branding set to `bright-os`
- Required space: 16 GB; required RAM: 2048 MB
- LUKS cryptodisk enabled
- Cancel disabled during exec
- 227 installer tests pass

Live installer testing (Calamares launch, partitioning, user creation, bootloader install, reboot) requires a bootable ISO and cannot be performed.

## 10. Installed-System Boot Result

Not tested (no installed system to boot).

## 11. AURA Runtime and Polkit Results

AURA was verified in headless mode during Phase 3.2:
- Headless start/stop/mode-switch PASSED
- 233 Python unit tests including Polkit regression tests PASSED

Live-system D-Bus/Polkit verification (service starts as `aura` user, D-Bus registers, Shutdown requires admin, GrantCloudConsent requires admin, revoke requires no elevation) requires a booted system with dbus-daemon and polkitd running, which cannot be done without a bootable ISO. The documented `VM_RUNTIME_PROCEDURE` in `aura/tests/test_phase32_runtime.py` provides the 8-step verification process to run on a booted system.

## 12. Outstanding Defects and Blockers

### Hard Blocker: Network Restrictions Prevent ISO Build
The sandbox environment has outbound internet access only to:
- github.com, codeload.github.com, api.github.com
- registry.npmjs.org
- pypi.org, files.pythonhosted.org

Debian mirrors (deb.debian.org, security.debian.org, and all alternative mirrors tested) are unreachable:
- TCP connections to port 80 get empty replies
- TLS connections to port 443 are reset
- apt-get update fails completely

This prevents:
1. Installing build dependencies (live-build, mksquashfs, xorriso, syslinux, grub, mtools, dosfstools, qemu, ovmf) via apt
2. Running debootstrap to download ~2–4 GB of Debian Trixie packages
3. Any genuine Debian ISO build

Note: debootstrap and live-build were installed from GitHub source clones during this assessment, but debootstrap still needs to download packages from Debian mirrors to create the chroot.

### Environment Resource Constraints
- RAM: 3.8 GB (below 8 GB recommended; no swap)
- Disk: 19 GB available (meets minimum but close)
- No KVM acceleration (QEMU would use slow TCG emulation)
- No /dev/kvm, no OVMF firmware, no QEMU binary

### Pre-existing Non-Blocking Issues
- 14 Calamares YAML test "failures" were a test-harness bug (PyYAML not installed), fixed in this PR
- tests/test-installer.sh module ordering check also needed the yaml module; wrapped to skip gracefully

### Not Defects (Verified)
- Calamares YAML files are all valid
- Installer module ordering is correct (packages before initramfscfg, umount last)
- AURA service configuration is correct (233 unit tests passing)
- All 1167 shell tests pass across 15 suites

## Tools Installed During Assessment

| Tool | Source | Version |
|------|--------|---------|
| debootstrap | github.com/aburch/debootstrap | 1.0.85 |
| live-build | github.com/debian-live/live-build | 5.0~a11-1 |
| pyyaml | pypi.org (pip3) | 6.0.4 |
| pycdlib | pypi.org (pip3) | 1.22.0 (provides pycdlib-genisoimage) |
| zlib (static) | github.com/madler/zlib (compiled) | 1.3.1 |

## Recommendation

The codebase is READY for the first Lite ISO build (all tests pass, installer config valid, AURA verified headless). The build must be performed on a properly provisioned Debian system with network access to Debian mirrors:

```bash
# On a Debian 12 Bookworm or Debian 13 Trixie machine with >=8 GB RAM, >=25 GB disk:
sudo apt-get update
sudo apt-get install -y \
    live-build debootstrap squashfs-tools xorriso \
    isolinux syslinux-common syslinux-efi mtools dosfstools genisoimage \
    grub-pc-bin grub-efi-amd64-bin shim-signed grub-efi-amd64-signed \
    qemu-system-x86 qemu-utils ovmf file python3-yaml
pip3 install pyyaml   # if python3-yaml apt package is not available

# Run the build:
./build/scripts/build-first-iso.sh

# Expected output:
#   build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
#   build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso.sha256
#   build/output/lite/BUILD-INFO.txt
```

Then follow the VM_RUNTIME_PROCEDURE for BIOS/UEFI boot testing, installer testing, and AURA Polkit verification.
