# Building Bright OS

This document describes how to build bootable Bright OS ISO images from source.

## Build Status Summary

| Edition     | Status             | Last Built | ISO Size | SHA256 |
|-------------|--------------------|------------|----------|--------|
| Lite        | NOT BUILT          | —          | —        | —      |
| Home        | NOT BUILT          | —          | —        | —      |
| Developer   | NOT BUILT          | —          | —        | —      |

**Status definitions:**
- **NOT BUILT** — ISO has not been built yet
- **BUILD FAILED** — Build attempted but failed
- **BUILT** — ISO produced but not validated
- **ISO VALIDATED** — ISO passed structural validation (ISO9660, kernel, squashfs, boot structures)
- **BIOS BOOT TESTED** — ISO boots in QEMU BIOS mode to desktop
- **UEFI BOOT TESTED** — ISO boots in QEMU UEFI mode to desktop
- **LIVE DESKTOP TESTED** — Live desktop loads with correct edition
- **INSTALLATION TESTED** — Installer completes successfully on virtual disk
- **INSTALLED SYSTEM BOOT TESTED** — Installed system reboots to login and desktop
- **HARDWARE TESTED** — Booted and used on real hardware

> **Important:** The build configuration is statically validated (**916 automated tests pass, 0 failures**),
> but no ISO has been built in the Arena sandbox due to restricted network access
> (Debian package mirrors are not reachable from the build sandbox).
> To produce a genuine ISO, follow the instructions below on a Debian machine with
> normal internet access.

## Quick Start (First ISO Build)

For a complete step-by-step walkthrough with screenshots, troubleshooting, and
QEMU testing instructions, see **[FIRST-ISO-HANDOFF.md](FIRST-ISO-HANDOFF.md)**.

```bash
# 1. Clone the repository
git clone https://github.com/nozaqk/Bright-OS.git
cd Bright-OS

# 2. Check out main
git checkout main

# 3. Run the build doctor to verify your system
./build/scripts/bright-build-doctor.sh

# 4. If the doctor says NOT READY, install missing dependencies:
sudo apt-get update
sudo apt-get install -y live-build debootstrap squashfs-tools xorriso \
    isolinux syslinux-common syslinux-efi mtools dosfstools genisoimage \
    grub-pc-bin grub-efi-amd64-bin shim-signed grub-efi-amd64-signed \
    qemu-system-x86 qemu-utils ovmf file

# 5. Build your first Lite ISO
./build/scripts/build-first-iso.sh

# 6. The ISO, checksum and build log will be in:
#    build/output/lite/
```

## Requirements

### System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **OS** | Debian 12 Bookworm | Debian 13 Trixie |
| **Architecture** | x86_64 / amd64 | x86_64 / amd64 |
| **RAM** | 3 GB (may OOM) | 8 GB+ |
| **Disk** | 20 GB free | 30+ GB free |
| **Network** | HTTP access to deb.debian.org | Same |
| **Swap** | 4 GB (if RAM < 8 GB) | 8 GB |
| **Privileges** | sudo access | sudo access |

> **Note:** Building on Debian 12 Bookworm works — live-build bootstraps a Trixie chroot
> from the network. Building on Ubuntu or other Debian derivatives may work but is
> not officially supported.

### Unsupported Configurations

- **Windows / WSL:** Not supported. Use a Debian VM or bare metal.
- **macOS:** Not supported. Use a Debian VM.
- **Non-x86_64 architectures** (ARM, RISC-V): Not supported yet.
- **Docker containers:** May work but require `--privileged`; VM is recommended.

## Step-by-Step: Your First Bright OS ISO

### Step 1: Prepare a Debian 13 Build Machine

**Option A: Bare metal or existing Debian install**

Install Debian 13 Trixie (or use Debian 12 Bookworm) on your computer or in a VM.

**Option B: Virtual machine**

Create a VM with:
- 4+ GB RAM (8 GB recommended)
- 4+ CPU cores
- 30+ GB virtual disk
- Network adapter (NAT or bridged)
- Install Debian 13 Trixie from https://www.debian.org/distrib/

### Step 2: Clone Bright OS

```bash
sudo apt-get update
sudo apt-get install -y git
git clone https://github.com/nozaqk/Bright-OS.git
cd Bright-OS
```

### Step 3: Run the Build Doctor

```bash
./build/scripts/bright-build-doctor.sh
```

This will check:
- Linux distribution and version
- CPU architecture
- Available RAM and swap
- Free disk space
- Internet connectivity and Debian mirror access
- Required build tools and packages
- Required project configuration files
- KVM acceleration availability
- Existing build artifacts

The doctor will report one of three statuses:
- **READY** — All critical checks pass
- **READY WITH WARNINGS** — Minor issues (low RAM, missing recommended packages)
- **NOT READY** — Critical failures (missing tools, no network, insufficient disk)

If NOT READY, the doctor prints the exact `apt-get install` command needed.

### Step 4: Install Dependencies

If the doctor reports missing packages:

```bash
sudo apt-get update
sudo apt-get install -y live-build debootstrap squashfs-tools xorriso \
    isolinux syslinux-common mtools dosfstools genisoimage \
    grub-pc-bin grub-efi-amd64-bin shim-signed grub-efi-amd64-signed \
    qemu-system-x86 qemu-utils ovmf file
```

Then re-run the build doctor to confirm:
```bash
./build/scripts/bright-build-doctor.sh
```

### Step 5: Build the Lite ISO

```bash
./build/scripts/build-first-iso.sh
```

This script will:
1. Verify you're in the Bright OS repository
2. Run the build doctor (stops if critical issues)
3. Run all 916 automated configuration tests
4. Clean stale build artifacts
5. Build the Bright OS Lite edition
6. Validate the ISO structure
7. Generate and verify SHA256 checksum
8. Record build metadata (BUILD-INFO.txt)

**Build time:** 30–90 minutes depending on network speed and hardware.

Build options:
```bash
./build/scripts/build-first-iso.sh --version 0.1.0-beta1   # Custom version
./build/scripts/build-first-iso.sh --skip-tests            # Skip tests (not recommended)
./build/scripts/build-first-iso.sh --force                 # Overwrite existing ISO
```

### Step 6: Locate Output Files

After a successful build:

```
build/output/lite/
├── bright-os-0.1.0-alpha-lite-amd64.iso       # The bootable ISO
├── bright-os-0.1.0-alpha-lite-amd64.iso.sha256 # SHA256 checksum
├── BUILD-INFO.txt                              # Build metadata
├── build-first-iso.log                         # Complete build log
└── [build working directories]
```

Example BUILD-INFO.txt:
```
Edition:      lite
Version:      0.1.0-alpha
Build date:   2026-03-15 14:30:00 UTC
Build time:   42m 18s
ISO file:     build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
Size:         1.8G
SHA256:       a1b2c3d4...
Git commit:   f4349cc...
```

### Step 7: Validate the ISO

Validation runs automatically after build, but you can re-run it:

```bash
./build/scripts/validate-iso.sh build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

This checks:
- ISO 9660 filesystem validity
- MBR boot signature (BIOS boot)
- Linux kernel (`/live/vmlinuz`)
- Initramfs (`/live/initrd.img`)
- SquashFS root filesystem
- EFI boot files
- GRUB bootloader
- SHA256 checksum match

### Step 8: Test Boot in QEMU

```bash
# BIOS boot (graphical)
./build/scripts/test-in-qemu.sh --bios build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# UEFI boot (requires ovmf package)
./build/scripts/test-in-qemu.sh --uefi build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# Installation test (20 GB virtual disk)
./build/scripts/test-in-qemu.sh --bios --disk 20 -m 4096 build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# Headless serial boot (for servers without display)
./build/scripts/test-in-qemu.sh --display serial --serial-log /tmp/boot.log \
    -m 4096 build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

See [QEMU Test Options](#qemu-test-options) below for full options.

### Step 9: Write to USB (for hardware testing)

```bash
# CAREFUL: This will DESTROY all data on the target device!
sudo dd if=build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso \
    of=/dev/sdX bs=4M status=progress conv=fsync
```

Replace `/dev/sdX` with your USB device. Verify with `lsblk` first.

See [HARDWARE-TESTING.md](HARDWARE-TESTING.md) for the hardware test checklist.

## Building Other Editions

After Lite builds and boots successfully, build Home and Developer:

```bash
# Clean up Lite build artifacts to free disk space (preserves the ISO)
./build/scripts/build.sh --clean lite

# Build Home edition
./build/scripts/build.sh home

# Build Developer edition
./build/scripts/build.sh --clean home
./build/scripts/build.sh developer
```

Or build all three in sequence:
```bash
./build/scripts/build-all.sh
```

> **Note:** Build all editions on the same machine/VM to ensure consistency.
> Each build takes 30–90 minutes and requires ~8 GB working space.
> Use `./build/scripts/build.sh --clean <edition>` between editions to free space.

### Publishing a Release

After all three editions build and validate, publish-release.sh runs ISO validation on all three editions before creating a GitHub release with checksums. It refuses to publish if validation fails on any edition.

## QEMU Test Options

```
./build/scripts/test-in-qemu.sh [OPTIONS] [ISO_PATH]

Boot modes:
  --bios               BIOS boot (default)
  --uefi               UEFI boot (requires ovmf)

Hardware:
  -m, --memory MB      Memory in MB (default: 4096)
  -c, --cpus N         CPU cores (default: 2)

Display:
  --display gtk        Graphical GTK window (default)
  --display sdl        SDL window
  --display curses     Text mode terminal
  --display none       Headless (no display)
  --display serial     Serial console to stdio
  --serial-log FILE    Log serial output to file

Installation testing:
  --disk SIZE_GB       Create temporary virtual disk (qemu2, disposable)
  --disk-file FILE     Use existing disk image

Other:
  --dry-run            Print QEMU command without running
```

## Cleaning Build Artifacts

```bash
# Clean one edition (preserves ISO and checksum)
./build/scripts/build.sh --clean lite

# Remove all build artifacts except ISOs
for ed in lite home developer; do
    ./build/scripts/build.sh --clean $ed
done

# Remove everything including ISOs
rm -rf build/output/*
```

## Troubleshooting

### Build doctor says "NOT READY"

Run the doctor and read the output carefully:
```bash
./build/scripts/bright-build-doctor.sh
```

Common issues:
- **Missing packages**: Copy the `sudo apt-get install` command printed by the doctor
- **Cannot reach Debian mirror**: Check network, proxy settings, firewall; verify you can `curl http://deb.debian.org/debian/`
- **Insufficient RAM**: Add swap or close other applications; minimum 3 GB, 4+ GB recommended
- **Insufficient disk**: Free space or use `./build/scripts/build.sh --clean <edition>`

### Build fails during package installation

- Check build log: `tail -100 build/output/lite/build-first-iso.log`
- Most common causes:
  - Network interruption during download (re-run build)
  - OOM kill (add RAM or swap, close other apps)
  - Disk full (free space and clean old builds)
  - Package repository inconsistency (wait and retry, or try a different mirror)

### ISO validation fails

- Kernel/initrd/squashfs missing: build likely failed partway through; check build log
- EFI boot files missing: ensure `grub-efi-amd64-bin` and `shim-signed` are installed
- MBR signature missing: rebuild; if persistent, check isolinux/syslinux packages

### QEMU boot hangs or is very slow

- Without KVM, TCG emulation is 5-20x slower; be patient
- For BIOS boot, try `--bios` explicitly
- Reduce memory to 2048 and CPUs to 2 if the host is resource-constrained
- Use `--display serial` for headless testing; add `console=ttyS0,115200` to GRUB boot line for kernel output

### Installer fails during installation

- Ensure target disk is at least 16 GB
- Check Calamares logs in the live environment (`/var/log/calamares/`)
- See [INSTALLER.md](INSTALLER.md) for detailed installer troubleshooting

## Reference: Build Scripts

| Script | Purpose |
|--------|---------|
| `build/scripts/bright-build-doctor.sh` | Diagnose build readiness (no changes to system) |
| `build/scripts/setup-build-env.sh` | Check and install build dependencies |
| `build/scripts/build-first-iso.sh` | Build, validate, and record first Lite ISO |
| `build/scripts/build.sh <edition>` | Build a single edition |
| `build/scripts/build-all.sh` | Build all three editions sequentially |
| `build/scripts/validate-iso.sh <iso>` | Validate ISO structure and checksums |
| `build/scripts/test-in-qemu.sh <iso>` | Boot ISO in QEMU for testing |
| `build/scripts/publish-release.sh` | Create GitHub release with validated ISOs |
