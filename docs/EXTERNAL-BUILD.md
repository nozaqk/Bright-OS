# External Build Instructions for Bright OS ISO

The sandbox cannot build the ISO because `deb.debian.org` is blocked. These are
exact instructions for building on a real Debian 13 (Trixie) machine or VM.

## Prerequisites

**Must be Debian 13 Trixie amd64** (Bookworm works but targets older packages).
Need ~15 GB free disk space, 4 GB+ RAM. Internet access required for package
download.

## Step 1: Install Build Dependencies

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

Verify live-build version is 1:20230502 or newer (supports `--bootloaders` plural):
```bash
lb --version
```

## Step 2: Clone and Build

```bash
git clone -b arena/ef7727be-bright-os https://github.com/nozaqk/Bright-OS.git
cd Bright-OS

# Build Home edition (target ISO: bright-os-0.1.0-alpha-home-amd64.iso)
./build.sh --edition home --verbose 2>&1 | tee build-home.log
```

Expected output at end:
```
BUILD SUCCESSFUL: /path/to/bright-os-0.1.0-alpha-home-amd64.iso
```

## Step 3: Validate ISO

```bash
./build/scripts/validate-iso.sh build/output/home/bright-os-0.1.0-alpha-home-amd64.iso
```

Expected: all checks PASS (not INCONCLUSIVE, not FAIL). If INCONCLUSIVE, install
the missing tools listed and re-run.

## Step 4: Boot Test in QEMU

```bash
# BIOS boot
./run-qemu.sh --iso build/output/home/bright-os-0.1.0-alpha-home-amd64.iso --bios

# UEFI boot (if ovmf is installed)
sudo apt-get install -y ovmf
./run-qemu.sh --iso build/output/home/bright-os-0.1.0-alpha-home-amd64.iso --uefi
```

Verify:
1. GRUB menu appears within 5 seconds
2. Selecting "Bright OS Live" boots to Plasma desktop
3. Calamares installer icon appears on desktop
4. Installing to a virtual disk completes without errors
5. After reboot, installed system boots to login screen
6. LUKS full-disk encryption works (test with encrypted partition in installer)

## Step 5: Create USB

```bash
sudo dd if=build/output/home/bright-os-0.1.0-alpha-home-amd64.iso \
    of=/dev/sdX bs=4M status=progress conv=fsync
```
Replace `/dev/sdX` with your USB device.

## Build Other Editions

```bash
./build.sh --edition lite     # ~1.0-1.2 GB target
./build.sh --edition developer
./build.sh --edition all      # All four editions
```

## Troubleshooting

- If lb config fails with "unknown option --bootloaders": you have an old
  live-build; upgrade to Debian Trixie.
- If EFI boot files missing: install `grub-efi-amd64-signed shim-signed`.
- If BIOS boot fails: install `isolinux syslinux-common`.
- If chroot fails with debootstrap errors: check internet connectivity and try
  with `--mirror http://deb.debian.org/debian/`.
- Build logs are saved in `build/logs/`.

## Test Results (Pre-Build Validation)

Before building, run the test suite to verify configuration integrity:
```bash
for t in tests/test-*.sh; do bash "$t" || break; done
```
Expected: **362 tests pass, 0 failures**.
