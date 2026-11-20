# Building Bright OS

This document describes how to build bootable Bright OS ISO images from source.

## Build Status Summary

| Edition     | Status             | Last Built | ISO Size | SHA256 |
|-------------|--------------------|------------|----------|--------|
| Lite        | NOT BUILT          | —          | —        | —      |
| Home        | NOT BUILT          | —          | —        | —      |
| Developer   | NOT BUILT          | —          | —        | —      |

**Status definitions:**
- **NOT BUILT** — ISO has not been built yet in this environment
- **BUILD FAILED** — Build attempted but failed
- **BUILT** — ISO produced but not validated
- **ISO VALIDATED** — ISO passed structural validation (ISO9660, kernel, squashfs, boot structures)
- **BIOS BOOT TESTED** — ISO boots in QEMU BIOS mode to desktop
- **UEFI BOOT TESTED** — ISO boots in QEMU UEFI mode to desktop
- **LIVE DESKTOP TESTED** — Live desktop loads with correct edition
- **INSTALLATION TESTED** — Installer completes successfully on virtual disk
- **INSTALLED SYSTEM BOOT TESTED** — Installed system reboots to login and desktop
- **HARDWARE TESTED** — Booted and used on real hardware

> **Important:** The build configuration has been validated statically (876 automated tests pass),
> but no ISO has been built in this sandbox environment due to restricted network access
> (Debian package repositories are not reachable). See [Reproducing the Build](#reproducing-the-build)
> below for instructions to build on a suitable machine.

## Requirements

### System Requirements

- **Operating System:** Debian 12 (Bookworm) or Debian 13 (Trixie)
- **Architecture:** x86_64 / amd64
- **RAM:** 4 GB minimum, 8 GB recommended (builds may OOM with less than 4 GB)
- **Disk Space:** 20 GB free minimum, 30+ GB recommended for building all three editions
- **Network:** Access to Debian package repositories (deb.debian.org, security.debian.org)
- **Privileges:** Root/sudo access (for installing build dependencies and running debootstrap/live-build)

> **Note:** While Bright OS targets Debian 13 Trixie, you can build on a Debian 12 Bookworm
> system — live-build will bootstrap a Trixie chroot from the network.

### Quick Start

```bash
# Clone the repository
git clone https://github.com/nozaqk/Bright-OS.git
cd Bright-OS

# Install build dependencies
./build/scripts/setup-build-env.sh

# Build one edition
./build/scripts/build.sh lite

# Build all three editions (Lite, Home, Developer)
./build/scripts/build-all.sh
```

## Step-by-Step Build Instructions

### Step 1: Install Build Dependencies

Run the setup script to check your system and install missing packages:

```bash
./build/scripts/setup-build-env.sh
```

Or install dependencies manually:

```bash
sudo apt-get update
sudo apt-get install -y \
    live-build debootstrap squashfs-tools xorriso \
    isolinux syslinux-common syslinux-efi mtools dosfstools genisoimage \
    grub-pc-bin grub-efi-amd64-bin shim-signed grub-efi-amd64-signed \
    qemu-system-x86 qemu-utils ovmf \
    file sha256sum
```

### Step 2: Run the Automated Tests

Before building, verify configuration correctness:

```bash
# Run all tests
for test in tests/test-*.sh; do bash "$test"; done

# Or run specific suites
bash tests/test-installer.sh     # Calamares installer config
bash tests/test-live-boot.sh     # Live boot media config
bash tests/test-calamares.sh     # Calamares consistency
bash tests/test-packages.sh      # Package list checks
```

### Step 3: Build Editions

Build editions in this order (Lite is smallest and catches build errors earliest):

```bash
# Build Lite first (lightweight LXQt edition, smallest)
./build/scripts/build.sh lite

# Then Home (full KDE Plasma, everyday desktop)
./build/scripts/build.sh home

# Then Developer (full Plasma + development tools)
./build/scripts/build.sh developer
```

Or build all three with one command:

```bash
./build/scripts/build-all.sh
```

Build options:

```bash
./build/scripts/build.sh --help
# -v, --version VER    Set version string (default: 0.1.0-alpha)
# -d, --distro CODENAME  Debian codename (default: trixie)
# --clean              Clean build directory
# --skip-build         Configure only, do not build
# --verbose            Verbose build output
```

A typical build takes 30–90 minutes per edition depending on network speed and hardware.

Validation runs automatically after each build. The build script runs ISO structural
validation (ISO9660 filesystem, kernel, initrd, squashfs, BIOS/UEFI boot structures,
SHA256 checksum) before reporting success. If validation fails, the build is marked failed.

### Step 4: Validate the ISO

After building, validate ISO structure:

```bash
./build/scripts/validate-iso.sh build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

This checks:
- ISO 9660 filesystem validity
- MBR boot signature (BIOS boot)
- Kernel and initrd presence
- SquashFS root filesystem
- EFI boot files
- GRUB bootloader
- SHA256 checksum

### Step 5: Test in QEMU

```bash
# BIOS boot (graphical)
./build/scripts/test-in-qemu.sh build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# UEFI boot
./build/scripts/test-in-qemu.sh --uefi build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# Headless serial boot (for servers/CI without display)
./build/scripts/test-in-qemu.sh --display serial -m 2048 build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso

# Boot with a virtual disk for installation testing
./build/scripts/test-in-qemu.sh --disk 20 -m 4096 build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso
```

QEMU options:

| Option | Description |
|--------|-------------|
| `--bios` | BIOS boot mode (default) |
| `--uefi` | UEFI boot mode (requires ovmf package) |
| `-m MB` | Memory in MB (default 4096) |
| `-c N` | Number of CPUs (default 2) |
| `--display MODE` | gtk (default), sdl, curses, none, serial |
| `--serial-log FILE` | Log serial console output to file |
| `--disk SIZE_GB` | Create a temporary virtual disk for installation testing |
| `--disk-file FILE` | Use an existing disk image |
| `--dry-run` | Print QEMU command without executing |

### Step 6: Write to USB and Test on Hardware

```bash
sudo dd if=build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso \
    of=/dev/sdX bs=4M status=progress conv=fsync
```

Replace `/dev/sdX` with your USB device (e.g., `/dev/sdb`).

**Always verify the target device first** — writing to the wrong disk will destroy data.

See [HARDWARE-TESTING.md](HARDWARE-TESTING.md) for the hardware testing checklist.

### Step 7: Publish to GitHub Releases

```bash
./build/scripts/publish-release.sh 0.1.0-alpha
```

This runs ISO validation on all three editions before publishing and creates a GitHub Release with checksums. Publishes only if all ISOs pass validation.

## Build Output Structure

```
build/output/
├── lite/
│   ├── bright-os-0.1.0-alpha-lite-amd64.iso
│   ├── bright-os-0.1.0-alpha-lite-amd64.iso.sha256
│   ├── build.log
│   └── [live-build working directories]
├── home/
│   ├── bright-os-0.1.0-alpha-home-amd64.iso
│   └── ...
└── developer/
    ├── bright-os-0.1.0-alpha-developer-amd64.iso
    └── ...
```

## Build Configuration Details

### live-build Configuration

The build uses Debian's `live-build` system with the following configuration (see `build/live-build/auto/config`):

- **Distribution:** Debian 13 Trixie
- **Architecture:** amd64
- **Image type:** iso-hybrid (USB + DVD bootable)
- **Bootloaders:** GRUB for BIOS (grub-pc) and UEFI (grub-efi)
- **Archive areas:** main, contrib, non-free, non-free-firmware
- **Apt recommends:** enabled (needed for proper desktop functionality)
- **Firmware:** included in both chroot and binary images
- **Secure Boot:** supported via shim-signed
- **Checksums:** SHA256
- **Memtest:** disabled

### Three Editions

| Aspect | Home | Developer | Lite |
|--------|------|-----------|------|
| Desktop | KDE Plasma | KDE Plasma | LXQt + Openbox |
| Compositor | KWin | KWin | Picom (X11) / KWin (Wayland) |
| Browser | Firefox ESR | Firefox ESR | Firefox ESR |
| Office | LibreOffice | LibreOffice | AbiWord, Gnumeric |
| Dev tools | — | gcc, clang, cmake, git, docker, qemu, kicad | — |
| Expected idle RAM | ~800 MB | ~1200 MB | ~500 MB |

### Clean Build

To clean a specific edition's build directory:

```bash
./build/scripts/build.sh --clean lite
```

This removes build artifacts but preserves the ISO and checksum.

## Troubleshooting

### Build fails during package installation

- Check you have at least 4 GB RAM (8 GB recommended)
- Check network connectivity to deb.debian.org
- Check disk space (`df -h`)
- Review the build log: `build/output/<edition>/build.log`
- Try cleaning and rebuilding: `./build/scripts/build.sh --clean <edition>`

### ISO validation fails

- If SHA256 mismatch: re-download or rebuild
- If kernel/initrd/squashfs missing: build likely failed partially; clean and rebuild
- If EFI boot files missing: ensure `grub-efi-amd64-bin` and `shim-signed` are installed

### QEMU boot hangs or is very slow

- Without KVM (`/dev/kvm`), QEMU uses TCG software emulation which is 5-20x slower
- For BIOS boot, add `--bios` explicitly
- For UEFI, ensure `ovmf` package is installed
- Try reducing memory to 2048 and CPUs to 2
- Use `--display serial` to see boot messages without a GUI

### Installer fails during installation

- Check Calamares logs in the live environment (dmesg, `/var/log/calamares/`)
- Ensure the target disk is at least 16 GB
- For LUKS encryption, ensure cryptsetup-initramfs is installed in the live system
- See [INSTALLER.md](INSTALLER.md) for detailed troubleshooting

## Reproducing the Build

The sandbox environment used to prepare this release has network restrictions that prevent
access to Debian package repositories (deb.debian.org). To reproduce a genuine build:

1. Use a Debian 12 Bookworm or Debian 13 Trixie system (bare metal or VM)
2. Install dependencies: `sudo apt-get install -y live-build debootstrap squashfs-tools xorriso isolinux syslinux-common mtools dosfstools genisoimage grub-pc-bin grub-efi-amd64-bin shim-signed grub-efi-amd64-signed qemu-system-x86 qemu-utils ovmf`
3. Clone: `git clone https://github.com/nozaqk/Bright-OS.git && cd Bright-OS`
4. Check out the release branch: `git checkout arena/phase-16-first-iso-validation`
5. Run tests: `for t in tests/test-*.sh; do bash "$t"; done` (expect 876 pass, 0 fail)
6. Build: `./build/scripts/build.sh lite 2>&1 | tee build-lite.log`
7. Validate: `./build/scripts/validate-iso.sh build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso`
8. Boot test: `./build/scripts/test-in-qemu.sh --bios build/output/lite/bright-os-0.1.0-alpha-lite-amd64.iso`
9. Record the SHA256: `sha256sum build/output/lite/*.iso`
10. Repeat for home and developer editions
