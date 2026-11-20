# Building Bright OS

This document describes how to build a bootable Bright OS ISO from source.

> **Status:** All build system bugs have been fixed (326 automated tests pass).
> The three editions (Home, Developer, Lite) are correctly separated with no
> Plasma package leakage into Lite. The ISO has not yet been built due to
> network restrictions in the development sandbox — the first build must be
> performed on a Debian 13 Trixie machine as described below.
> Please report build failures via GitHub Issues.

## Supported Debian Releases

| Debian Version | Codename | Support Status |
|---------------|----------|----------------|
| Debian 13 | **trixie** | ✅ Primary target (current stable) |
| Debian 12 | bookworm | ✅ Should work; use `--distro bookworm` |

The build defaults to Debian 13 Trixie.

## Build Requirements

### Hardware
- **CPU:** x86-64 (amd64) — multi-core recommended
- **RAM:** Minimum 4 GB, 8 GB recommended
- **Disk:** Minimum 20 GB free space
- **Network:** Internet connection to download packages from `deb.debian.org`

### Operating System
You must build on a Debian (or Debian-based) system of the same release as
your target. Building from Ubuntu or other derivatives is not tested and may
fail due to package differences.

### Required Packages

```bash
sudo apt-get update
sudo apt-get install -y \
    live-build \
    debootstrap \
    squashfs-tools \
    xorriso \
    isolinux \
    syslinux-common \
    syslinux-efi \
    grub-pc-bin \
    grub-efi-amd64-bin \
    grub-efi-amd64-signed \
    shim-signed \
    mtools \
    dosfstools \
    genisoimage
```

For UEFI boot testing in QEMU, also install:
```bash
sudo apt-get install -y qemu-system-x86 ovmf
```

## Quick Build

```bash
git clone https://github.com/nozaqk/Bright-OS.git
cd Bright-OS

# Build Home edition (default)
./build/scripts/build.sh home

# Build Developer edition
./build/scripts/build.sh developer

# Build Lite edition
./build/scripts/build.sh lite
```

The resulting ISO will be at:
```
build/output/<edition>/bright-os-0.1.0-alpha-<edition>-amd64.iso
```

## Build Options

```
Usage: ./build/scripts/build.sh [OPTIONS] [EDITION]

Editions:
  home        Bright OS Home edition (default)
  developer   Bright OS Developer edition
  lite        Bright OS Lite edition

Options:
  -h, --help            Show this help
  -v, --version VER     Set version string (default: 0.1.0-alpha)
  -a, --arch ARCH       Set architecture (default: amd64)
  -d, --distro CODENAME Debian codename (default: trixie)
  --clean               Clean build directory only
  --skip-build          Configure only, do not build
  --verbose             Verbose build output
```

### Examples

```bash
# Build Home edition for Debian Bookworm
./build/scripts/build.sh --distro bookworm home

# Configure only (don't build) - useful for debugging config
./build/scripts/build.sh --skip-build home

# Clean a previous build
./build/scripts/build.sh --clean home

# Build with verbose output
./build/scripts/build.sh --verbose developer
```

## What the Build Does

The build script (`build/scripts/build.sh`) performs these steps:

1. **Validates** edition, architecture, dependencies, and source files
2. **Creates** a build directory at `build/output/<edition>/`
3. **Copies** live-build auto scripts (`config`, `build`, `clean`)
4. **Copies** the configuration tree (package lists, hooks, includes.chroot, includes.binary)
5. **Merges** edition-specific packages and hooks
6. **Writes** the edition marker (`home`, `developer`, or `lite`)
7. **Masks services** for Lite edition (bluetooth, cups, ModemManager)
8. **Runs** `lb config` to configure Debian live-build
9. **Runs** `lb build` to download packages, create the chroot, and build the ISO
10. **Renames** the output ISO and generates a SHA256 checksum

### Live-Build Configuration

The `build/live-build/auto/` directory contains the live-build automation:
- `auto/config` — Configures `lb` with distribution, mirrors, bootloader, and ISO metadata
- `auto/build` — Runs `lb build`
- `auto/clean` — Runs `lb clean`

The `config/` directory contains:
- `config/package-lists/base.list.chroot` — Core system packages
- `config/package-lists/edition-packages.list.chroot` — Edition-specific packages (added during build)
- `config/hooks/live/` — Chroot hooks (branding, component installation, Calamares setup)
- `config/includes.chroot/` — Files copied directly into the live system root
- `config/includes.binary/` — Files placed on the ISO filesystem (GRUB config)

## Build Outputs

After a successful build you will find:

| File | Description |
|------|-------------|
| `bright-os-<version>-<edition>-<arch>.iso` | Bootable hybrid ISO |
| `bright-os-<version>-<edition>-<arch>.iso.sha256` | SHA256 checksum |
| `build.log` | Full build log |

## Validating the ISO

After building, validate the ISO:

```bash
./build/scripts/validate-iso.sh build/output/home/bright-os-0.1.0-alpha-home-amd64.iso
```

This checks:
- File size (>100 MB)
- ISO 9660 filesystem validity
- Hybrid ISO status (USB bootable)
- MBR boot signature
- Kernel (`vmlinuz`) presence in `/live/`
- Initrd presence in `/live/`
- Squashfs root filesystem presence
- EFI boot support
- GRUB presence
- SHA256 checksum (if `.sha256` file exists)

## Testing in QEMU

```bash
./build/scripts/test-in-qemu.sh build/output/home/bright-os-0.1.0-alpha-home-amd64.iso
```

Options:
- `--bios` — BIOS boot (default)
- `--uefi` — UEFI boot (requires `ovmf` package)
- Memory size in MB (e.g. `4096`)

Example:
```bash
# UEFI boot with 8 GB RAM
./build/scripts/test-in-qemu.sh build/output/home/bright-os-0.1.0-alpha-home-amd64.iso --uefi 8192
```

## Creating a Bootable USB

**WARNING:** This will erase the target drive! Double-check the device name.

```bash
# Identify your USB drive
lsblk

# Write ISO to USB
sudo dd if=build/output/home/bright-os-0.1.0-alpha-home-amd64.iso \
    of=/dev/sdX bs=4M status=progress conv=fsync
```

Replace `/dev/sdX` with your USB device (e.g., `/dev/sdb`). Do NOT append a partition number.

## Installing onto Existing Debian

If you already run Debian 12 or 13 and want to try Bright Desktop without building an ISO:

```bash
sudo ./build/scripts/install-bright-os.sh --edition home
```

This installs Bright Desktop shell, applications, themes, and configuration on top of your existing system. Then log out and select "Bright Desktop" from your display manager session menu.

## Troubleshooting

### "Missing dependencies" error
Install the packages listed above. The build script tells you which packages are missing.

### Build fails during package download
Check your internet connection. The build downloads ~2-3 GB of packages. Use a mirror closer to you by editing `build/live-build/auto/config` (change `--mirror-bootstrap` and related options).

### "Could not resolve hostname" or network errors
Ensure DNS is working and you have unrestricted internet access. Corporate proxies may cause issues.

### ISO fails to boot in QEMU
- Try BIOS mode first (`--bios`), UEFI requires the `ovmf` package.
- Ensure you allocated enough memory (at least 2048 MB).
- Use `-vga virtio` (default in the test script) rather than emulated cards.

### Desktop doesn't start in live boot
- Switch to TTY with Ctrl+Alt+F2
- Log in as `user`/`live`
- Check logs: `journalctl -u sddm`, `journalctl -t bright-desktop-shell`
- Check that PyQt6 is installed: `python3 -c "from PyQt6.QtQml import QQmlApplicationEngine; print('OK')"`

### Calamares fails to start
Run Calamares from terminal to see errors:
```bash
pkexec calamares -d
```

### chroot or permission errors
The build uses `lb` which handles chroot operations internally. If you see permission errors, ensure you're not running the build script itself as root (live-build uses fakeroot where needed). However, some versions of live-build require running as root — if you get chroot errors, try:
```bash
sudo ./build/scripts/build.sh home
```

## Build Time

Expected build times on typical hardware:
- 4-core CPU, SSD, 100 Mbps internet: **30-45 minutes**
- 8-core CPU, NVMe SSD, 1 Gbps internet: **15-25 minutes**
- Slow internet (<10 Mbps): **1-2 hours**

The build downloads approximately 2-3 GB of packages.

## Reproducibility

To create a reproducible build:
1. Pin to a specific Debian snapshot mirror by adding `--mirror-bootstrap-append` and related snapshot options to `auto/config`
2. Set `SOURCE_DATE_EPOCH` environment variable
3. Use `lb build --cache` to enable caching

Reproducible builds are a future goal, not guaranteed for Alpha 0.1.

## Cleaning

To clean a specific edition's build directory:
```bash
./build/scripts/build.sh --clean home
```

This removes build artifacts (`config/`, `chroot/`, `binary/`, `.build/`, `local/`) but preserves ISO files.
