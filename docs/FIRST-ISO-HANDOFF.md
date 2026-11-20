# First ISO Handoff — Building Bright OS Lite on Your Computer

This document is the step-by-step guide to producing the **first genuine Bright OS Lite ISO**
on your own Debian machine. It is designed to be foolproof: follow the commands in order, and
you will end up with a bootable, validated ISO.

---

## What You Need

### Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores x86_64 | 4+ cores |
| RAM | 3 GB | 8 GB+ |
| Disk free space | 20 GB | 30 GB+ |
| Swap (if RAM < 8 GB) | 4 GB | 8 GB |
| Network | HTTP access to deb.debian.org | Same |
| USB drive (for hardware test) | 8 GB | 16 GB+ |

### Operating System

- **Debian 13 Trixie** (recommended — includes modern live-build with full BIOS+UEFI+Secure Boot support)
- **Debian 12 Bookworm** (works — live-build will bootstrap a Trixie chroot)
- **Ubuntu 24.04 LTS** (works with automatic capability detection; see note below)
- Windows, macOS, WSL, and Docker are not supported — use a Debian VM instead

#### Live-build Version Compatibility

Bright OS automatically detects the installed live-build version and adapts:

| Build Host | live-build version | BIOS boot | UEFI boot | Secure Boot |
|---|---|---|---|---|
| Debian 13 Trixie | 1:2025xxxx (modern) | ✅ Full | ✅ Full | ✅ `--uefi-secure-boot auto` |
| Debian 12 Bookworm | 1:2023xxxx | ✅ Full | ✅ Full | ⚠️ Depends on shim packages |
| Ubuntu 24.04 | 3.0~a57-1ubuntuXX (legacy) | ✅ Full | ⚠️ See note | ❌ Not configurable |

**Ubuntu 24.04 note**: Ubuntu ships an older fork of live-build (3.0~a57) that lacks
the `--bootloaders` and `--uefi-secure-boot` options. Bright OS detects this and:
- Uses only supported options (no unrecognized option errors)
- Provides BIOS boot via isolinux (auto-detected)
- Attempts UEFI boot setup via a binary hook (requires `grub-efi-amd64-bin` and `mtools` packages)
- Reports Secure Boot as unavailable (shim-signed is installed but not integrated)
- Fails with a clear error if UEFI cannot be configured (set `BRIGHT_REQUIRE_UEFI=0` to override)

For best results (especially UEFI Secure Boot), build on Debian 13 Trixie.

### Virtual Machine Notes

If using a VM (VirtualBox, GNOME Boxes, virt-manager, VMware):
- Allocate at least 4 GB RAM (8 GB recommended)
- Allocate at least 30 GB virtual disk
- Use NAT or bridged networking
- Enable EFI if you want to test UEFI boot (not required for the build itself)
- KVM acceleration on Linux hosts dramatically speeds up QEMU testing

---

## Step 1: Install Debian

If you don't already have a Debian system:

1. Download Debian 13 Trixie (preferred): https://www.debian.org/devel/debian-installer/
2. Or Debian 12 Bookworm: https://www.debian.org/distrib/
3. Install with default options; ensure "SSH server" and "standard system utilities" are selected.
4. After reboot, log in and open a terminal.

---

## Step 2: Clone Bright OS

```bash
# Install git if not present
sudo apt-get update
sudo apt-get install -y git

# Clone the repository
git clone https://github.com/nozaqk/Bright-OS.git
cd Bright-OS

# Check out the Phase 17/18 integration branch (if not yet merged to main)
# If this PR is already merged, skip this checkout
git checkout arena/phase-18-first-iso-handoff

# Verify you're in the right place
ls build/scripts/bright-build-doctor.sh
# Should show: build/scripts/bright-build-doctor.sh
```

---

## Step 3: Run the Build Doctor

```bash
./build/scripts/bright-build-doctor.sh
```

This will check your system and print one of three results:
- **READY** — All critical checks pass; proceed to Step 5.
- **READY WITH WARNINGS** — Build should work but note the warnings (low RAM, missing KVM, etc.).
- **NOT READY** — Critical issues found; proceed to Step 4.

---

## Step 4: Install Missing Dependencies

If the doctor reports NOT READY, it will print an `apt-get install` command with exactly
the packages you need. The full command is:

```bash
sudo apt-get update
sudo apt-get install -y live-build debootstrap squashfs-tools xorriso \
    isolinux syslinux-common syslinux-efi mtools dosfstools genisoimage \
    grub-pc-bin grub-efi-amd64-bin shim-signed grub-efi-amd64-signed \
    qemu-system-x86 qemu-utils ovmf file
```

Or use the automated setup script:
```bash
./build/scripts/setup-build-env.sh
```

After installing, re-run the doctor to confirm:
```bash
./build/scripts/bright-build-doctor.sh
```

You should see **STATUS: READY** or **STATUS: READY WITH WARNINGS** (warnings about KVM or
number of CPU cores are acceptable).

---

## Step 5: Build the Lite ISO

```bash
./build/scripts/build-first-iso.sh
```

This script will:
1. Verify you're in the Bright OS repository
2. Run the build doctor again (stops if critical issues remain)
3. Run all 916 automated configuration tests
4. Clean stale build artifacts from previous attempts
5. Build the Bright OS Lite edition (~30–90 minutes)
6. Validate the ISO structure (kernel, initrd, squashfs, boot signatures)
7. Generate and verify SHA256 checksum
8. Save build metadata to `BUILD-INFO.txt`

Do not interrupt the build. If you lose your terminal connection, the build log is
preserved at `build/output/lite/build-first-iso.log`.

### Build Options

```bash
./build/scripts/build-first-iso.sh --version 0.1.0-beta1   # Custom version string
./build/scripts/build-first-iso.sh --skip-tests            # Skip tests (not recommended)
./build/scripts/build-first-iso.sh --force                 # Overwrite existing ISO
```

---

## Step 6: Locate Your ISO

After a successful build you will see:

```
============================================================
  FIRST ISO BUILD SUCCESSFUL
============================================================

  Edition:     Bright OS Lite
  Version:     0.1.0-alpha
  ISO:         /path/to/Bright-OS/build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
  Size:        1.8G
  SHA256:      a1b2c3d4...
  Build time:  42m 18s
  Log:         build/output/lite/build-first-iso.log
  Metadata:    build/output/lite/BUILD-INFO.txt
```

### Output Files

```
build/output/lite/
├── bright-os-0.1.0-alpha-lite-amd64.iso         ← The bootable ISO
├── bright-os-0.1.0-alpha-lite-amd64.iso.sha256  ← SHA256 checksum
├── BUILD-INFO.txt                                ← Build metadata
└── build-first-iso.log                           ← Complete build log
```

---

## Step 7: Validate the ISO

Validation runs automatically during the build. To re-run manually:

```bash
./build/scripts/validate-iso.sh build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

Expected passing checks:
- ISO 9660 filesystem valid
- File size > 100 MB
- MBR boot signature 0x55AA present (BIOS bootable)
- Kernel (`/live/vmlinuz`) found
- Initrd (`/live/initrd.img`) found
- SquashFS (`/live/filesystem.squashfs`) found
- EFI boot files detected
- GRUB bootloader present
- SHA256 checksum verified

---

## Step 8: Test BIOS Boot in QEMU

```bash
./build/scripts/test-in-qemu.sh --bios -m 4096 \
    build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

You should see:
1. A QEMU window opens
2. GRUB boot menu appears with "Start Bright OS Live (Default)"
3. Kernel boot messages scroll by
4. Eventually the SDDM login screen or (if autologin works) the Bright Desktop appears
5. Default live user: `user` / password: `live`

If the desktop loads, **BIOS boot works**. Close the QEMU window.

**If KVM is not available:** Boot will be very slow (5–15 minutes to desktop). Be patient.
You can reduce memory to 2048 MB with `-m 2048` if needed.

---

## Step 9: Test UEFI Boot in QEMU

```bash
./build/scripts/test-in-qemu.sh --uefi -m 4096 \
    build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

This requires the `ovmf` package (installed in Step 4). You should see:
1. OVMF logo briefly
2. GRUB boot menu
3. Same boot sequence as BIOS
4. Desktop loads

If the desktop loads, **UEFI boot works**.

---

## Step 10: Test Installation on a Virtual Disk

```bash
./build/scripts/test-in-qemu.sh --bios --disk 20 -m 4096 \
    build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

This creates a 20 GB virtual disk. In the live desktop:
1. Double-click "Install Bright OS" on the desktop
2. Follow the Calamares wizard:
   - Select language, timezone, keyboard
   - Partitioning: choose "Erase disk" (this only affects the virtual disk!)
   - Create a user account
   - Click Install and wait for completion
3. When finished, close QEMU
4. Boot from the virtual disk (not the CD-ROM):

```bash
# Boot the installed system (remove -cdrom, use the disk)
qemu-system-x86_64 -m 4096 -smp 2 \
    -drive file=/tmp/bright-disk-*.qcow2,format=qcow2,if=virtio \
    -vga virtio -display gtk -netdev user,id=net0 -device e1000,netdev=net0
```

> **Note:** `build-first-iso.sh` creates disposable disks in `/tmp/` with the
> `bright-disk-` prefix. If you want a persistent test disk, create one with
> `qemu-img create -f qcow2 bright-test-disk.qcow2 20G` and use `--disk-file`.

---

## Step 11: Write to USB (for hardware testing)

After QEMU testing passes, write to a USB drive:

```bash
# FIRST, identify your USB device:
lsblk

# Make sure you get the RIGHT device (e.g., /dev/sdb, NOT /dev/sda which is your system disk!)
# The following command WILL DESTROY ALL DATA on the target device.

sudo dd if=build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso \
    of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

Then boot your computer from the USB and test on real hardware.
See [HARDWARE-TESTING.md](HARDWARE-TESTING.md) for the complete hardware test checklist.

---

## Troubleshooting

### Build doctor says NOT READY

Run it and read the output carefully:
- **Missing packages?** Copy the `sudo apt-get install` command exactly.
- **Cannot reach deb.debian.org?** Check network, proxy settings (`http_proxy`/`https_proxy`), and firewall.
- **Insufficient RAM?** Close applications or add swap: `sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile`
- **Insufficient disk?** Free space or build on a larger disk.

### Build fails during package download/extraction

- **Network interruption:** Re-run `./build/scripts/build-first-iso.sh`. It will resume where possible.
- **OOM kill (exit code 137):** Add RAM or swap. Close other applications.
- **Disk full:** Free space and re-run. Clean old builds with `./build/scripts/build.sh --clean lite`.

### Build fails with package errors

Check the build log:
```bash
tail -100 build/output/lite/build-first-iso.log
```

Common causes:
- Package name changed in Trixie (check package lists in `config/package-lists/`)
- Repository inconsistency (wait a few hours and retry, or try a different mirror)
- Missing firmware packages (check `firmware-*` packages are in core.list.chroot)

### ISO validation fails

- **No kernel/initrd/squashfs:** Build likely failed partway through; check build log.
- **No EFI boot files:** Ensure `grub-efi-amd64-bin` and `shim-signed` were installed BEFORE building.
- **MBR signature missing:** Rebuild; ensure `isolinux` and `syslinux-common` are installed.

### QEMU shows black screen / hangs

- Without KVM, TCG emulation is very slow — wait 5–15 minutes.
- Try "Safe Graphics" from GRUB menu (press E, add `nomodeset` to linux line).
- Try reducing to `-m 2048 -c 2`.

### GRUB menu appears but kernel panics

- Try different boot options from GRUB (Safe Graphics, Recovery Mode).
- Note the exact error message and check the build log for missing firmware.

### Installer fails during installation

- Ensure virtual disk is at least 16 GB.
- Check `/var/log/calamares/` inside the live environment.
- See [INSTALLER.md](INSTALLER.md) for detailed Calamares troubleshooting.

### Installed system doesn't boot

- Check GRUB was installed to the correct disk/partition.
- For BIOS: ensure MBR boot flag is set on boot partition.
- For UEFI: ensure EFI System Partition is FAT32 and has boot/esp flags.

---

## Reporting Results

After building and testing, please report results at:
https://github.com/nozaqk/Bright-OS/issues

Include:
- Whether the build succeeded
- ISO size and SHA256 checksum
- Whether BIOS boot worked
- Whether UEFI boot worked
- Whether installation succeeded
- Whether installed system booted to login
- Whether Bright Desktop loaded with correct edition
- Your hardware specs (CPU, RAM, GPU, storage)
- Any errors encountered

---

## Quick Reference Card

```bash
# One-time setup
git clone https://github.com/nozaqk/Bright-OS.git && cd Bright-OS
./build/scripts/bright-build-doctor.sh
sudo apt-get install -y live-build debootstrap squashfs-tools xorriso \
    isolinux syslinux-common syslinux-efi mtools dosfstools genisoimage \
    grub-pc-bin grub-efi-amd64-bin shim-signed grub-efi-amd64-signed \
    qemu-system-x86 qemu-utils ovmf file

# Build Lite ISO
./build/scripts/build-first-iso.sh

# Validate
./build/scripts/validate-iso.sh build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# Test boot
./build/scripts/test-in-qemu.sh --bios build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
./build/scripts/test-in-qemu.sh --uefi build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
./build/scripts/test-in-qemu.sh --bios --disk 20 -m 4096 build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# Write to USB (CAREFUL with /dev/sdX!)
sudo dd if=build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```
