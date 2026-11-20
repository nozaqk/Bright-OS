# Building Bright OS

This document describes how to build a bootable Bright OS ISO from source.

## Build Requirements

- **Host OS:** Debian 12 (Bookworm) amd64
- **RAM:** Minimum 4 GB, 8 GB recommended
- **Disk:** Minimum 15 GB free space
- **Root:** sudo access required (for chroot operations during build)
- **Network:** Internet connection to download packages

### Install Build Dependencies

```bash
sudo apt-get update
sudo apt-get install -y \
    live-build \
    debootstrap \
    squashfs-tools \
    xorriso \
    isolinux \
    syslinux-efi \
    grub-pc-bin \
    grub-efi-amd64-bin \
    mtools \
    dosfstools \
    coreutils
```

## Quick Build

```bash
# Clone repository
git clone https://github.com/nozaqk/Bright-OS.git
cd Bright-OS

# Build Home edition (default)
./build/scripts/build.sh home

# Build Developer edition
./build/scripts/build.sh developer

# Build Lite edition
./build/scripts/build.sh lite
```

The resulting ISO will be in `build/output/<edition>/bright-os-0.1.0-alpha-<edition>-amd64.iso`.

## Build Options

```bash
./build/scripts/build.sh [edition] [options]

Editions:
  home        Standard desktop edition
  developer   Full development/electronics toolchain
  lite        Minimal edition for older hardware

Options:
  --version VERSION   Set version string (default: 0.1.0-alpha)
  --arch ARCH         Architecture (default: amd64)
  --clean             Clean build directory
  --skip-build        Configure only (don't build)
  --verbose           Verbose build output
```

## Build Outputs

After a successful build, you will find:

- `bright-os-<version>-<edition>-<arch>.iso` — The bootable ISO image
- `bright-os-<version>-<edition>-<arch>.iso.sha256` — SHA256 checksum
- `build.log` — Full build log

## Installation from Build Machine

If you want to install Bright OS components onto your existing Debian system (without building an ISO):

```bash
sudo ./build/scripts/install-bright-os.sh --edition home
```

This will install the Bright Desktop shell, applications, themes, and configuration on top of your current system.

## Testing the ISO in QEMU

After building, test boot in QEMU without writing to USB:

```bash
# UEFI boot (if OVMF available)
qemu-system-x86_64 \
    -cdrom build/output/home/bright-os-0.1.0-alpha-home-amd64.iso \
    -m 4G \
    -enable-kvm \
    -cpu host \
    -smp 4 \
    -vga virtio \
    -bios /usr/share/OVMF/OVMF_CODE.fd

# BIOS boot
qemu-system-x86_64 \
    -cdrom build/output/home/bright-os-0.1.0-alpha-home-amd64.iso \
    -m 4G \
    -enable-kvm \
    -cpu host \
    -smp 4 \
    -vga virtio
```

## Creating a Bootable USB

```bash
# WARNING: This will erase the target drive!
sudo dd if=build/output/home/bright-os-0.1.0-alpha-home-amd64.iso \
    of=/dev/sdX bs=4M status=progress conv=fsync
```

Replace `/dev/sdX` with your USB drive (e.g., `/dev/sdb`). Use `lsblk` to identify it.

## Validating the ISO

```bash
./build/scripts/validate-iso.sh build/output/home/bright-os-0.1.0-alpha-home-amd64.iso
```

This checks ISO integrity, boot signatures, presence of kernel/initrd/squashfs, and EFI support.

## Build Customization

### Adding Packages

Edit `config/package-lists/base.list.chroot` for system-wide packages, or add edition-specific packages to:
- `editions/home/packages.list`
- `editions/developer/packages.list`
- `editions/lite/packages.list`

### Customizing the Live Environment

Files placed in `config/includes.chroot/` are copied into the live system root filesystem. For example:
- `config/includes.chroot/etc/skel/` — Default user home directory contents
- `config/includes.chroot/usr/share/bright-os/` — Bright OS system files
- `config/includes.chroot/lib/live/config/` — Live system boot hooks

### Custom Hooks

Shell scripts in `config/hooks/live/*.hook.chroot` run inside the chroot during the build process. Use these for system configuration.

## Troubleshooting

**Build fails with "no space left on device":**
Ensure you have at least 15 GB free space. The build process creates temporary files in the build directory.

**Package download failures:**
The build requires internet access. If behind a proxy, set `http_proxy` and `https_proxy` environment variables.

**ISO won't boot on some hardware:**
Try the "Safe Graphics" boot option. Some GPUs require nomodeset. Check `build.log` for firmware package inclusion.

**No graphical desktop after boot:**
Check TTY (Ctrl+Alt+F2) and verify SDDM is running: `systemctl status sddm`. Check X/Wayland logs in `~/.local/share/sddm/`.

## Reproducibility

The build is configured for reproducibility where possible:
- Fixed Debian snapshot mirror can be substituted
- Timestamps are normalized where possible
- Package versions are pinned to Debian Bookworm stable

For fully reproducible builds, use a specific Debian snapshot mirror by setting `--mirror-bootstrap` in `build/live-build/auto/config`.
