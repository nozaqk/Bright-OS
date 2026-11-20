# Hardware Testing Guide for Bright OS

> **Status as of Phase 12:** No real ISO has been built or boot-tested yet.
> All testing checklists below are prepared for when the first ISO is available.
> Build configuration has been validated (362 automated tests pass) including
> BIOS+UEFI dual-boot configuration and LUKS full-disk encryption setup.

## Pre-Test Checklist

Before testing on real hardware:

- [ ] ISO validates successfully with `validate-iso.sh`
- [ ] ISO boots in QEMU (both BIOS and UEFI)
- [ ] Live desktop loads successfully
- [ ] You have a backup USB drive (8+ GB)
- [ ] Secure Boot: shim-signed included but not fully tested; if boot fails disable Secure Boot
- [ ] Fast Startup is disabled in Windows (for dual-boot)

## Test Matrix

### Boot and Installation

| Test | Expected Result | Actual |
|------|----------------|--------|
| BIOS boot from USB | GRUB menu appears | |
| UEFI boot from USB | GRUB menu appears | |
| Default boot option | Desktop loads in < 60s (SSD) | |
| Safe graphics mode | Desktop loads with software rendering | |
| Calamares installer launches | Installer opens | |
| Installation to disk | System installs successfully | |
| Reboot after install | System boots to SDDM | |

### Basic Functionality

| Test | Expected Result | Actual |
|------|----------------|--------|
| SDDM login screen | Appears correctly | |
| Bright Desktop session | Shell loads with panel, dock, wallpaper | |
| Network Manager | Wi-Fi/ethernet connects | |
| Sound output | Audio plays through speakers/headphones | |
| Brightness control | Screen brightness adjusts | |
| External monitor | Display detected (if applicable) | |
| USB storage | USB drives mount in Bright Files | |
| Shutdown from menu | System powers off cleanly | |
| Reboot from menu | System reboots to GRUB | |

### Applications

| Application | Expected Result | Actual |
|-------------|----------------|--------|
| Bright Terminal | Opens, accepts commands | |
| Bright Files | Browsing files, opening folders | |
| Bright Settings | Opens, categories load | |
| Bright Monitor | Shows processes and resources | |
| Firefox | Web browsing works | |
| VLC | Video/audio playback | |

### Memory Targets

| Edition | Target | Measured |
|---------|--------|----------|
| Lite idle | < 500 MB | |
| Home idle | < 800 MB | |
| Developer idle | < 1200 MB | |
| Lite with Firefox | < 1.5 GB | |
| Home with Firefox+LibreOffice | < 2.5 GB | |

Measure with: `free -h` after 2 minutes idle at desktop.

## Known Hardware Compatibility Notes

### Working (expected)
- Intel integrated graphics (i915)
- AMD Radeon graphics (amdgpu)
- NVIDIA (with non-free drivers installed post-install; use Safe Graphics for live boot)
- Most Realtek/Intel wired networking
- Most Intel/Qualcomm Atheros Wi-Fi
- USB keyboards/mice
- SATA/NVMe storage

### May Need Additional Firmware
- Broadcom Wi-Fi: requires `broadcom-sta-dkms` or firmware-brcm80211
- Some Realtek Wi-Fi: requires firmware-realtek
- NVIDIA GPUs: install nvidia-driver after installation

### Not Yet Supported
- Secure Boot (signing not configured in Alpha)
- Apple Silicon (ARM)
- NVIDIA Optimus hybrid graphics (limited support)
- Some fingerprint readers

## Reporting Hardware Issues

Please report hardware compatibility at:
https://github.com/nozaqk/Bright-OS/issues

Include:
- Full hardware specifications (CPU, GPU, RAM, Wi-Fi chip, storage)
- `lspci -nn` output
- `dmesg` output if errors occur
- Whether you used BIOS or UEFI boot
- Which edition you tested
- Exact steps to reproduce
