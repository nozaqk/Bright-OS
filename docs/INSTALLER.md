# Bright OS Installer Guide

## Overview

Bright OS uses **Calamares** (version 3.3.x for Debian Trixie) as its graphical installer. The installer supports:

- **UEFI with GPT** (modern systems)
- **Legacy BIOS with MBR** (older systems)
- **Dual-boot** installations alongside existing operating systems (when using manual partitioning)
- **Manual partitioning** for advanced users
- **Automatic disk installation** with explicit user confirmation
- **LUKS full-disk encryption**
- **Reusing existing EFI System Partitions**

## Installation Steps

1. **Boot the Bright OS live environment** from USB/DVD.
2. **Start the installer** by double-clicking "Install Bright OS" on the desktop (runs via `pkexec calamares`).
3. **Select language** on the welcome screen.
4. **Select your location and timezone** (auto-detected via geolocation when online).
5. **Configure keyboard layout**.
6. **Choose partitioning**:
   - **Erase disk**: Automatically partitions the disk with EFI + root (and LUKS if encryption is enabled).
   - **Replace partition**: Replace an existing partition.
   - **Alongside**: Install alongside another OS (if detected).
   - **Manual partitioning**: Create your own partition layout.
7. **Set up disk encryption** (optional): If enabled, you will be asked for a passphrase that unlocks the disk at boot.
8. **Create your user account** (name, username, password, hostname).
9. **Review the summary** and click "Install" (you will be asked to confirm).
10. Wait for installation to complete, then **reboot**.
11. On first boot, the system runs **first-boot setup** (Flathub initialization, font caches, SSD TRIM) and then presents the SDDM login screen.

## Partitioning Requirements

| Mount Point | Minimum Size | Filesystem | Notes |
|-------------|-------------|------------|-------|
| `/boot/efi` | 300MB (512MB recommended) | FAT32 | Required for UEFI boot |
| `/` (root) | 8GB minimum, 16GB+ recommended | ext4, btrfs, xfs, f2fs | Main system partition |
| swap | Optional (2–16GB based on RAM) | swap | Hibernation requires swap ≥ RAM |

### LUKS Encryption Notes

- LUKS2 is supported out of the box on both UEFI and BIOS systems.
- GRUB uses `GRUB_ENABLE_CRYPTODISK=y` to unlock the encrypted partition before booting.
- A keyfile is installed in initramfs to avoid entering the passphrase twice (once for GRUB, once for systemd-cryptsetup).
- The deprecated `keyscript=` option in crypttab is **not used** (incompatible with cryptsetup-initramfs 2.7+ in Debian Trixie).

## Post-Installation

After installation completes and you reboot:

1. SDDM presents the login screen.
2. Log in with the user account you created during installation.
3. Bright Desktop starts with the correct edition profile (Home/Developer/Lite).
4. First-boot setup runs automatically (it is safe if re-run).

### What the installer does after copying files

- Removes live-system packages (`live-boot`, `live-config`, etc.)
- Regenerates initramfs with LUKS keyfile support (if encryption enabled)
- Installs GRUB bootloader (UEFI NVRAM entry or BIOS MBR)
- Configures SDDM display manager with Bright Desktop as default session
- Enables system services (NetworkManager, SDDM, firewalld, fstrim.timer for SSDs)
- Writes `/etc/os-release` with the correct edition name
- Removes live user and live autologin configuration
- Cleans up temporary files and regenerates caches

## Troubleshooting

### Installer does not start from desktop icon
Run `pkexec calamares` from a terminal. If `pkexec` is not available, use `sudo calamares`.

### Installation fails at "Creating initramfs"
This is usually caused by live-boot packages not being removed before initramfs generation. Check `/var/log/bright-postcfg.log` in the installed system (or in the live environment at `/tmp/calamares-root-*/var/log/bright-postcfg.log`).

### GRUB does not appear after reboot (UEFI)
- Ensure your system boots in UEFI mode (not Legacy/CSM).
- Verify the EFI System Partition is correctly formatted as FAT32 and flagged as boot/ESP.
- Try booting from the Bright OS USB and running `grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=BrightOS` from a chroot.

### Encrypted system asks for password twice
If you are prompted for a password at the GRUB prompt *and* again at the system prompt, the initramfs update may not have included the keyfile. This can happen if `live-boot-initramfs-tools` was not removed before `update-initramfs` ran. Boot from the live medium, mount the system, and run:
```
cryptsetup luksAddKey /dev/sdX3 /crypto_keyfile.bin
update-initramfs -u -k all
```

### Bright Desktop does not start after login
- Check that `bright-desktop-shell` is present and executable (`which bright-desktop-shell`).
- Verify `/etc/bright-os/edition` contains a valid edition (`home`, `developer`, or `lite`).
- Check `~/.config/bright-os/shell.conf` for valid values.
- If using Lite edition, ensure `qterminal` and `pcmanfm-qt` are installed.

### No network after installation
NetworkManager should start automatically. If not:
```
sudo systemctl enable --now NetworkManager.service
```

## Automated Configuration Tests vs Real Installation

The automated tests (`tests/test-installer.sh`, `tests/test-calamares.sh`) validate:
- YAML syntax of all Calamares configuration files
- Correct module ordering (required for LUKS/bootloader)
- Presence of required configuration options
- Absence of deprecated/breaking options (e.g., `keyscript=` on Trixie)
- First-boot service configuration
- Edition detection and profile loading

These tests **do not** perform an actual installation. To validate a real install, build the ISO (see [BUILDING.md](BUILDING.md)) and test in a virtual machine:
1. Boot in QEMU/KVM with at least 4GB RAM and a 20GB+ virtual disk.
2. Run the installer.
3. Reboot and verify the installed system boots to SDDM.
4. Log in and verify Bright Desktop loads the correct edition profile.

## Installer Configuration Files

All Calamares configuration is in `installer/calamares/`:

| File | Purpose |
|------|---------|
| `settings.conf` | Module sequence, window settings, requirements |
| `branding/bright-os/branding.desc` | Installer branding (colors, names, logos) |
| `branding/bright-os/show.qml` | Installation slideshow |
| `modules/welcome.conf` | Welcome screen and system requirements |
| `modules/locale.conf` | Locale, timezone, language generation |
| `modules/keyboard.conf` | Keyboard layout configuration |
| `modules/partition.conf` | Partitioning options, filesystems, LUKS, swap |
| `modules/users.conf` | User account creation and default groups |
| `modules/mount.conf` | Mount point configuration |
| `modules/unpackfs.conf` | Filesystem copy (rsync from live system) |
| `modules/exclude-list` | Files excluded during rsync copy |
| `modules/fstab.conf` | /etc/fstab generation (no deprecated keyscript) |
| `modules/bootloader.conf` | GRUB installation (UEFI + BIOS) |
| `modules/grubcfg.conf` | GRUB defaults (cryptodisk, timeout, theme) |
| `modules/displaymanager.conf` | SDDM configuration (default session: bright.desktop) |
| `modules/networkcfg.conf` | Hostname configuration |
| `modules/services-systemd.conf` | Systemd services to enable (NetworkManager, SDDM, fstrim) |
| `modules/packages.conf` | Live package removal (required before initramfs) |
| `modules/luksbootkeyfile.conf` | LUKS keyfile for single-password unlock |
| `modules/initramfscfg.conf` | initramfs-tools hooks for LUKS |
| `modules/initramfs.conf` | Initramfs generation |
| `modules/hwclock.conf` | Hardware clock (UTC) |
| `modules/machineid.conf` | Machine ID generation |
| `modules/shellprocess-post.conf` | Custom post-install script |
| `modules/postcfg.sh` | Post-installation customization script |
| `modules/summary.conf` | Pre-install summary screen |
| `modules/finished.conf` | Post-install reboot screen |
