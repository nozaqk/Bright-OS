# Phase 19 — First Genuine Lite ISO Build: Completion Report

**Branch:** `arena/0d381bb4-bright-os`
**Base commit:** `825e90528cd9364e903fce95a607a8074801173c` (main, includes Phase 18 fixes via PR #33)
**Date:** 2026-11-23

---

## Executive Summary

**Phase 19 cannot be completed in this sandbox environment.** The codebase is ready (all tests pass, installer configs valid, AURA verified headless), but the sandbox's network firewall prevents access to Debian package mirrors (deb.debian.org, security.debian.org, and all tested alternative mirrors). Without the ability to download Debian packages, no genuine Debian-based ISO can be produced.

---

## 1. Exact Main Commit Used

`825e90528cd9364e903fce95a607a8074801173c` (merge of PR #33, which includes Phase 18 test harness fixes).

## 2. Build Machine Specifications

| Resource | Value | Requirement | Status |
|----------|-------|-------------|--------|
| OS | Debian GNU/Linux 12 (Bookworm) | Debian 12/13 | ✅ Meets |
| Architecture | amd64 (x86_64) | amd64 | ✅ Meets |
| CPU | 2 cores (Intel Xeon @ 2.6 GHz) | ≥2 cores | ⚠️ Minimum (slow) |
| RAM | 3.8 GiB | ≥8 GiB recommended | ❌ Below minimum (with 2 GiB swap added) |
| Swap | 2 GiB (created during this session) | ≥4 GiB recommended | ⚠️ Partial |
| Disk | 21 GB total, 18 GB available | ≥30 GB recommended | ❌ Below recommended |
| Network to Debian mirrors | **BLOCKED** | Required | ❌ **Hard Blocker** |
| Network to github.com/pypi.org | Works | — | ✅ |
| KVM acceleration | Not available | Recommended | ⚠️ TCG emulation only |
| sudo | Available (passwordless) | Required | ✅ |

## 3. Build Doctor Results

```
Passed:   41
Warnings: 17
Failed:   14
STATUS: NOT READY
```

### Passed (41)
- Debian OS detected (Bookworm, can cross-build Trixie)
- amd64 architecture supported
- sudo available (passwordless)
- Basic internet connectivity (ping/DNS)
- sha256sum found
- **lb (live-build) 5.0~a11-1** — installed from github.com/debian-live/live-build
- **debootstrap 1.0.85** — installed from github.com/aburch/debootstrap
- **python3-yaml** — installed from PyPI
- All 28 project configuration files present
- No existing Lite ISO (clean start)
- live-build supports --mode, --keyring-packages
- Swap space available (2 GiB)

### Warnings (17)
- Debian 12 Bookworm (Trixie native recommended)
- 2 CPU cores (build will be slow)
- 3.8 GB RAM (may OOM)
- 18 GB disk (meets minimum, below recommended)
- shim-signed not installed (Secure Boot limited)
- grub-efi-amd64-signed not installed
- ovmf not installed
- qemu-system-x86 not installed
- qemu-utils not installed
- file not installed
- /dev/kvm not available
- live-build is legacy fork version (not native Trixie)
- EFI boot creation tools not fully available

### Failed (14) — All due to network restrictions

| Failure | Root Cause |
|---------|-----------|
| Cannot reach deb.debian.org | Network firewall blocks all HTTP/HTTPS to Debian mirrors |
| Cannot reach security.debian.org | Same firewall restriction |
| mksquashfs not found | Package requires apt install (squashfs-tools) |
| xorriso not found | Package requires apt install |
| isolinux not installed | Package requires apt install |
| syslinux-common not installed | Package requires apt install |
| syslinux-efi not installed | Package requires apt install |
| mtools not installed | Package requires apt install |
| dosfstools not installed | Package requires apt install |
| genisoimage not found | Package requires apt install (genisoimage) |
| grub-pc-bin not installed | Package requires apt install |
| grub-efi-amd64-bin not installed | Package requires apt install |
| isoinfo not found | Package requires apt install (genisoimage) |
| Insufficient disk space at initial check | Resolved by adding swap and cleaning temp files (now 18 GB) |

### Network Verification
All attempts to reach Debian mirrors fail:
- **deb.debian.org** (port 80): Connection established but empty reply
- **deb.debian.org** (port 443): TLS handshake fails (SSL_ERROR_SYSCALL)
- **security.debian.org**: Same failure
- All tested alternative mirrors (cdn-fastly, ftp.debian.org, debian.csail.mit.edu, mirrors.kernel.org, mirror.math.princeton.edu, cloudfront.debian.net): All fail with connection errors
- **GitHub release assets** (releases.githubusercontent.com): TLS blocked — cannot download pre-built static binaries
- **Allowed hosts only**: github.com (git clone), codeload.github.com (tarballs), api.github.com (API), pypi.org, files.pythonhosted.org, registry.npmjs.org

### Tools Successfully Installed From Allowed Sources
- **debootstrap 1.0.85** (from github.com/aburch/debootstrap, with trixie symlink)
- **live-build 5.0~a11-1** (from github.com/debian-live/live-build)
- **pyyaml 6.0.4** (from PyPI)
- **pycdlib 1.22.0** (from PyPI — provides pycdlib-genisoimage, a pure-Python ISO9660 tool)

## 4. Automated Test Results

### Python Tests
```
$ python3 -m compileall -q aura
OK

$ python3 -m unittest discover aura
Ran 233 tests in 7.1s
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
| tests/test-installer.sh | 227 | 0 |
| tests/test-iso-validator.sh | 18 | 0 |
| tests/test-live-boot.sh | 78 | 0 |
| tests/test-live-build-compat.sh | 82 | 0 |
| tests/test-local-build.sh | 64 | 0 |
| tests/test-qemu-script.sh | 17 | 0 |
| **Total** | **1167** | **0** |

No skipped tests presented as passing. No false YAML failures (PyYAML installed and all Calamares configs validated).

## 5. ISO Location and Size

**NOT PRODUCED.** Build terminates at dependency check with:
```
[ERROR] Missing dependencies: mksquashfs xorriso isolinux syslinux-common
        syslinux-efi mtools dosfstools genisoimage grub-pc-bin grub-efi-amd64-bin
```

Even if these tools were available, debootstrap would fail immediately because it cannot download packages from `http://deb.debian.org/debian`.

Expected path (on a properly provisioned system):
```
build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

## 6. SHA256 Checksum

Not applicable — no ISO produced.

## 7. BIOS Boot Result

Not tested — no ISO produced.

## 8. UEFI Boot Result

Not tested — no ISO produced. OVMF firmware also not installed in the environment.

## 9. Live Desktop Result

Not tested — no bootable ISO.

## 10. Installer Result

Installer configuration verified statically (all 227 installer tests pass; all 24 Calamares YAML files valid; module ordering correct; LUKS, displaymanager, packages, initramfs, bootloader, umount all present). Live Calamares launch, partitioning, and installation testing cannot proceed without a bootable ISO.

## 11. Installed-System Result

Not tested — no installed system.

## 12. AURA Runtime Results

AURA verified in headless mode:
- 233 Python unit tests pass including Polkit regression tests
- Service starts, intelligence reaches RUNNING, mode switch to offline disables network, shutdown clean
- Source/packaged sync verified byte-identical
- Systemd hardening verified (unprivileged user, caps dropped, ProtectSystem=strict)

Live D-Bus/Polkit verification (service registration, Shutdown auth, GrantCloudConsent auth, consent revocation, Polkit dialogs) requires a booted system with dbus-daemon and polkitd. The `VM_RUNTIME_PROCEDURE` in `aura/tests/test_phase32_runtime.py` provides the 8-step verification procedure.

## 13. Remaining Defects and Blockers

### Hard Blocker: Network Firewall Prevents Debian Package Access
The sandbox's network policy only allows outbound connections to:
- github.com, codeload.github.com, api.github.com
- registry.npmjs.org
- pypi.org, files.pythonhosted.org

All HTTP/HTTPS connections to Debian mirrors (deb.debian.org, security.debian.org, and 7 tested alternative mirrors) are blocked at the network level (empty replies on HTTP, TLS reset on HTTPS). This prevents:
1. Installing build dependencies via apt (mksquashfs, xorriso, isolinux, syslinux, grub, mtools, dosfstools, QEMU, OVMF)
2. Running debootstrap to download ~2-4 GB of Debian Trixie packages for the live filesystem chroot
3. Downloading pre-built static binaries from GitHub releases (releases.githubusercontent.com is also blocked)

This is not a configuration issue that can be resolved within the sandbox — it is a network-level restriction on the environment.

### Secondary Issues (Would Still Apply Even With Network)
- **RAM**: 3.8 GiB is below the 4 GB threshold; 2 GiB swap added but 8+ GiB recommended for reliable builds
- **Disk**: 18 GB available meets the 18 GB minimum but is below the 25 GB recommended
- **CPU**: 2 cores will make the build very slow (estimated 60-120 minutes)
- **No KVM**: QEMU testing would use slow TCG software emulation
- **Host lacks X11/desktop packages**: The container is headless; the build process itself doesn't need X11 but testing does

### Code Status
- **All code tests pass**: 233 Python + 1167 shell = 1400 total, 0 failures
- **Calamares YAML configs**: All valid (previous false failures fixed in Phase 18)
- **AURA security**: Polkit fail-closed, unprivileged user, systemd hardening intact
- **Build scripts**: Present and syntactically valid

## Build Instructions for a Properly Provisioned System

The codebase is ready for ISO build. Run on a Debian 12 Bookworm or Debian 13 Trixie machine/vm with:
- 8+ GB RAM, 4+ GB swap, 30+ GB disk
- Outbound HTTPS to deb.debian.org
- Root/sudo access

```bash
# Install dependencies
sudo apt-get update
sudo apt-get install -y \
    live-build debootstrap squashfs-tools xorriso \
    isolinux syslinux-common syslinux-efi mtools dosfstools genisoimage \
    grub-pc-bin grub-efi-amd64-bin shim-signed grub-efi-amd64-signed \
    qemu-system-x86 qemu-utils ovmf file python3-yaml

# Verify environment
./build/scripts/bright-build-doctor.sh

# Build Lite ISO (will run tests first)
./build/scripts/build-first-iso.sh

# Expected output:
#   build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
#   build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso.sha256
#   build/output/lite/BUILD-INFO.txt
#   build/output/lite/build-first-iso.log

# Test BIOS boot
./build/scripts/test-in-qemu.sh --bios build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# Test UEFI boot
./build/scripts/test-in-qemu.sh --uefi build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# Test installation (20 GB virtual disk)
./build/scripts/test-in-qemu.sh --disk 20 -m 4096 build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

Then on the booted system, run the AURA verification procedure from `aura/tests/test_phase32_runtime.py` (VM_RUNTIME_PROCEDURE section).
