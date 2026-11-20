# Building Bright OS

Bright OS ISOs are built locally on a Debian Linux machine using Debian Live Build.

## Requirements

### Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8 GB+ |
| Disk space | 20 GB per edition | 30 GB+ for all editions |
| Internet | Required (for package downloads) | Broadband |

### Software

- **Operating System:** Debian 12 (Bookworm) or Debian 13 (Trixie). Debian 13 Trixie is recommended for best compatibility.
- **Architecture:** x86_64 / amd64 (only supported architecture for Alpha 0.1)
- **Windows:** Not supported directly. Install Debian in a virtual machine (VMware, VirtualBox, Hyper-V) with sufficient disk and RAM allocated to the VM.
- **macOS:** Not supported directly. Use a Debian Linux virtual machine.

> **Note:** Building inside Docker on non-Debian hosts may work but is untested. A native Debian installation or VM is the most reliable approach.

## Step 1: Clone the Repository

```bash
git clone https://github.com/nozaqk/Bright-OS.git
cd Bright-OS
```

## Step 2: Set Up Build Environment

Run the setup script to check your system and install dependencies:

```bash
./build/scripts/setup-build-env.sh
```

This script:
- Verifies you are running on a compatible Debian system
- Checks architecture (must be amd64)
- Checks available RAM (minimum 4 GB)
- Checks available disk space (minimum 20 GB)
- Installs all required build dependencies via apt-get
- Checks for bootloader packages (GRUB, isolinux, shim)
- Checks for ISO validation tools

To check without installing packages:

```bash
./build/scripts/setup-build-env.sh --check
```

### Manual Dependency Installation

If you prefer to install manually:

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

## Step 3: Build an Edition

### Build a single edition

```bash
./build/scripts/build.sh home         # Home edition (Bright Desktop, everyday layout)
./build/scripts/build.sh developer    # Developer edition (Bright Desktop, developer layout + dev tools)
./build/scripts/build.sh lite         # Lite edition (Bright Desktop, lightweight profile + LXQt)
```

### Build all three editions

```bash
./build/scripts/build-all.sh
```

### Build options

```bash
./build/scripts/build.sh home --version 0.1.0-alpha   # Set version string
./build/scripts/build.sh home --verbose               # Verbose output
./build/scripts/build.sh home --distro bookworm       # Build on Debian Bookworm
./build/scripts/build.sh home --clean                 # Clean build artifacts
```

### Build time

Expect 30-90 minutes per edition depending on your internet speed and CPU. Building all three editions takes 1.5-4 hours sequentially.

## Step 4: Output Files

ISOs and build logs are saved to:

```
build/output/
├── home/
│   ├── bright-os-0.1.0-alpha-home-amd64.iso
│   ├── bright-os-0.1.0-alpha-home-amd64.iso.sha256
│   └── build.log
├── developer/
│   ├── bright-os-0.1.0-alpha-developer-amd64.iso
│   ├── bright-os-0.1.0-alpha-developer-amd64.iso.sha256
│   └── build.log
└── lite/
    ├── bright-os-0.1.0-alpha-lite-amd64.iso
    ├── bright-os-0.1.0-alpha-lite-amd64.iso.sha256
    └── build.log
```

## Step 5: Validate the ISO

Validation runs **automatically** after each edition builds. The build script will:
- Verify the ISO exists and is not empty
- Check ISO9660 filesystem structure
- Verify kernel, initrd, and squashfs are present
- Check BIOS MBR boot signature and UEFI EFI boot image
- Verify GRUB and ISOLINUX bootloaders
- Confirm SHA256 checksum

If validation fails, the build exits with an error and reports the specific issues.
The ISO and build log are preserved for investigation.

To manually re-validate an ISO:

```bash
./build/scripts/validate-iso.sh build/output/home/bright-os-0.1.0-alpha-home-amd64.iso
```

Passing validation means the ISO structure is correct; it does NOT guarantee the OS boots. Always test in QEMU before writing to USB.

Validation checks:
- File is not empty and is >100 MB
- Valid ISO 9660 filesystem
- Hybrid ISO (USB-bootable)
- MBR boot signature (BIOS boot)
- Linux kernel present
- Initrd present
- Squashfs root filesystem present
- EFI boot files (UEFI boot)
- GRUB bootloader present
- ISOLINUX present (BIOS boot)
- SHA256 checksum match (if .sha256 file exists)

Passing validation does **not** guarantee the ISO boots. Always test in QEMU first.

The Calamares installer configuration is validated automatically by `tests/test-installer.sh` (YAML syntax, module ordering, LUKS/GRUB configuration). See [docs/INSTALLER.md](INSTALLER.md) for installation documentation, supported boot modes, and troubleshooting.

## Step 6: Test in QEMU (Optional but Recommended)

```bash
./build/scripts/test-in-qemu.sh build/output/home/bright-os-0.1.0-alpha-home-amd64.iso
```

Or manually:

```bash
# BIOS boot
qemu-system-x86_64 -cdrom build/output/home/bright-os-0.1.0-alpha-home-amd64.iso -m 4G -enable-kvm

# UEFI boot (install ovmf first: sudo apt-get install ovmf)
qemu-system-x86_64 -cdrom build/output/home/bright-os-0.1.0-alpha-home-amd64.iso -m 4G -enable-kvm -bios /usr/share/OVMF/OVMF_CODE.fd
```

## Step 7: Publish to GitHub Releases

After building and validating all three editions, you can publish a release:

```bash
./build/scripts/publish-release.sh 0.1.0-alpha
```

This script:
1. Verifies GitHub CLI (`gh`) is installed and authenticated
2. Checks all three ISOs exist and are non-empty
3. Verifies SHA256 checksums for all three ISOs
4. Runs ISO validation on all three editions (using validate-iso.sh)
5. Checks that no ISO exceeds GitHub's 2 GiB file size limit
6. Refuses to publish if any ISO is missing, invalid, or oversized
7. Asks for explicit confirmation before publishing
8. Creates a GitHub Release with the version tag
9. Uploads the three ISOs and SHA256SUMS file

Prerequisites:
- [GitHub CLI](https://cli.github.com/) installed (`sudo apt-get install gh`)
- Authenticated (`gh auth login`)
- Push access to the repository
- All three editions built successfully

## Common Issues

### "Missing dependencies" error

Run the setup script or install dependencies manually as shown in Step 2.

### "Insufficient disk space" error

Free up space or build on a partition with 20+ GB free. Each edition needs about 8-15 GB during the build process for package caching and the squashfs image.

### Build fails during package installation

- Check your internet connection
- Try running with `--verbose` for detailed output
- Check `build/output/<edition>/build.log` for the full log
- Debian Trixie is a moving target; package names may change. Check for typos in package lists.

### ISO is not bootable in QEMU

- Ensure you built on Debian 13 Trixie with correct bootloader packages
- Run `validate-iso.sh` — if EFI boot files are missing, ensure `grub-efi-amd64-bin` and `shim-signed` are installed
- Try both BIOS and UEFI boot modes

### "Permission denied" errors

The build does not need to run as root. However, setup-build-env.sh needs sudo for apt-get. If you see Docker-related permission errors, you are using an unsupported container-based build approach.

### Clean up build artifacts

To clean a specific edition's build directory (preserves ISOs):

```bash
./build/scripts/build.sh home --clean
```

To completely remove all build output:

```bash
rm -rf build/output/
```

## Writing to USB

```bash
sudo dd if=build/output/home/bright-os-0.1.0-alpha-home-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

Replace `/dev/sdX` with your USB device (e.g., `/dev/sdb`). Use `lsblk` to identify it.
