# Hardware Testing Guide for Bright OS

> **Status as of Phase 17:** Build configuration is complete and statically validated
> (916 automated tests pass, 0 failures across 13 test suites). No genuine ISO has
> been built or boot-tested yet due to sandbox network restrictions.
>
> **Build tools ready:**
> - `./build/scripts/bright-build-doctor.sh` — diagnostics
> - `./build/scripts/build-first-iso.sh` — first Lite ISO build with validation
>
> **How to test:** On a Debian machine with network access:
> 1. `./build/scripts/bright-build-doctor.sh` to verify your system
> 2. Install missing dependencies as directed
> 3. `./build/scripts/build-first-iso.sh` to build Lite ISO
> 4. Follow the checklists below starting with QEMU, then real hardware.
> See [BUILDING.md](BUILDING.md) for complete instructions.

## Pre-Test Checklist

Before building your first ISO:

- [ ] Debian 12 or 13 system with 4+ GB RAM, 20+ GB free disk
- [ ] `./build/scripts/bright-build-doctor.sh` reports READY or READY WITH WARNINGS
- [ ] Network access to deb.debian.org (test with `curl -I http://deb.debian.org/debian/`)

Before testing on real hardware:

- [ ] ISO builds successfully with `./build/scripts/build-first-iso.sh`
- [ ] ISO validates successfully with `./build/scripts/validate-iso.sh`
- [ ] ISO boots in QEMU BIOS mode to desktop
- [ ] ISO boots in QEMU UEFI mode to desktop
- [ ] Live desktop loads successfully
- [ ] Calamares installer launches
- [ ] You have a backup USB drive (8+ GB)
- [ ] Secure Boot: shim-signed is included but Secure Boot testing is incomplete; if boot fails, disable Secure Boot
- [ ] Fast Startup is disabled in Windows (for dual-boot testing)

## Test Matrix

### Boot and Live Desktop

| Test | Expected Result | Lite | Home | Developer |
|------|----------------|------|------|-----------|
| BIOS boot from USB/ISO | GRUB menu appears | NOT TESTED | NOT TESTED | NOT TESTED |
| UEFI boot from USB/ISO | GRUB menu appears | NOT TESTED | NOT TESTED | NOT TESTED |
| Default boot option | Desktop loads | NOT TESTED | NOT TESTED | NOT TESTED |
| Safe graphics mode | Desktop loads with nomodeset | NOT TESTED | NOT TESTED | NOT TESTED |
| Live user autologin | Logged in as 'user' | NOT TESTED | NOT TESTED | NOT TESTED |
| Correct edition identified | About dialog shows correct edition | NOT TESTED | NOT TESTED | NOT TESTED |
| Bright Desktop loads | Panel, dock, wallpaper visible | NOT TESTED | NOT TESTED | NOT TESTED |
| Installer icon on desktop | "Install Bright OS" shortcut present | NOT TESTED | NOT TESTED | NOT TESTED |
| Network connectivity | NetworkManager connects | NOT TESTED | NOT TESTED | NOT TESTED |
| Calamares launches | Installer window opens | NOT TESTED | NOT TESTED | NOT TESTED |

### Installation Testing

| Test | Expected Result | Lite | Home | Developer |
|------|----------------|------|------|-----------|
| Auto partitioning (erase disk) | Partitions created correctly | NOT TESTED | NOT TESTED | NOT TESTED |
| Manual partitioning | Custom layout works | NOT TESTED | NOT TESTED | NOT TESTED |
| LUKS encryption | Encryption setup works | NOT TESTED | NOT TESTED | NOT TESTED |
| User creation | User account created | NOT TESTED | NOT TESTED | NOT TESTED |
| GRUB installation | Bootloader installed | NOT TESTED | NOT TESTED | NOT TESTED |
| Install completes | "Finished" screen appears | NOT TESTED | NOT TESTED | NOT TESTED |

### Post-Install

| Test | Expected Result | Lite | Home | Developer |
|------|----------------|------|------|-----------|
| Reboot after install | System boots to SDDM | NOT TESTED | NOT TESTED | NOT TESTED |
| SDDM login screen | Appears correctly | NOT TESTED | NOT TESTED | NOT TESTED |
| User login | Session starts | NOT TESTED | NOT TESTED | NOT TESTED |
| Bright Desktop session | Shell loads with panel, dock, wallpaper | NOT TESTED | NOT TESTED | NOT TESTED |
| First-boot setup runs | Flathub added, caches updated | NOT TESTED | NOT TESTED | NOT TESTED |
| Network Manager | Wi-Fi/ethernet connects | NOT TESTED | NOT TESTED | NOT TESTED |
| Sound output | Audio works (PipeWire) | NOT TESTED | NOT TESTED | NOT TESTED |
| Edition profile correct | Layout/animations match edition | NOT TESTED | NOT TESTED | NOT TESTED |
| No live user present | 'user' account removed | NOT TESTED | NOT TESTED | NOT TESTED |

### Applications

| Application | Expected Result | Lite | Home | Developer |
|-------------|----------------|------|------|-----------|
| Bright Terminal | Opens, accepts commands | NOT TESTED | NOT TESTED | NOT TESTED |
| Bright Files | File browsing works | NOT TESTED | NOT TESTED | NOT TESTED |
| Bright Settings | Opens, categories load | NOT TESTED | NOT TESTED | NOT TESTED |
| Firefox | Web browsing works | NOT TESTED | NOT TESTED | NOT TESTED |
| VLC / mpv | Video/audio playback | NOT TESTED | NOT TESTED | NOT TESTED |
| Text editor | Opens and edits files | NOT TESTED | NOT TESTED | NOT TESTED |
| Package/software center | Installs packages | NOT TESTED | NOT TESTED | NOT TESTED |

### Memory Targets

| Edition | Target | Measured |
|---------|--------|----------|
| Lite idle | < 500 MB | NOT MEASURED |
| Home idle | < 800 MB | NOT MEASURED |
| Developer idle | < 1200 MB | NOT MEASURED |
| Lite with Firefox | < 1.5 GB | NOT MEASURED |
| Home with Firefox+LibreOffice | < 2.5 GB | NOT MEASURED |

Measure with: `free -h` after 2 minutes idle at desktop.

## How to Run Tests

### QEMU Automated Boot Check

```bash
# BIOS boot to live desktop
./build/scripts/test-in-qemu.sh --bios -m 4096 build/output/lite/bright-os-*-lite-amd64.iso

# UEFI boot
./build/scripts/test-in-qemu.sh --uefi -m 4096 build/output/lite/bright-os-*-lite-amd64.iso

# Installation testing (creates disposable 20GB disk)
./build/scripts/test-in-qemu.sh --bios --disk 20 -m 4096 build/output/lite/bright-os-*-lite-amd64.iso
```

### Headless/Serial Testing (for CI environments)

```bash
# Capture serial output to a log file
./build/scripts/test-in-qemu.sh --display serial --serial-log /tmp/bright-serial.log \
    -m 2048 -c 2 build/output/lite/bright-os-*-lite-amd64.iso
```

Note: GRUB and the Linux kernel need `console=ttyS0` boot parameter to output to serial.
Edit the GRUB menu entry at boot (press E) and add `console=ttyS0,115200` to the linux line.

### Test Procedure (per edition)

1. **Build the ISO:** `./build/scripts/build.sh <edition>`
2. **Validate:** `./build/scripts/validate-iso.sh build/output/<edition>/*.iso`
3. **BIOS boot:** Observe GRUB → kernel boot → desktop. Time it.
4. **UEFI boot:** Same as BIOS but with `--uefi`
5. **Launch installer:** Double-click desktop icon, complete wizard
6. **Install:** Use a disposable 20GB virtual disk
7. **Reboot:** Verify installed system boots to SDDM
8. **Login:** Verify Bright Desktop loads
9. **Check edition:** Run `bright-about` or `cat /etc/bright-os/edition`
10. **Test apps:** Launch terminal, browser, file manager
11. **Measure RAM:** `free -h` after 2 minutes idle
12. **Record results:** Update the test matrix above

## Known Hardware Compatibility Notes

### Expected to Work
- Intel integrated graphics (i915)
- AMD Radeon graphics (amdgpu)
- NVIDIA (with non-free drivers installed post-install; use Safe Graphics for live boot)
- Most Realtek/Intel wired networking
- Most Intel/Qualcomm Atheros Wi-Fi
- USB keyboards/mice
- SATA/NVMe storage

### May Need Additional Firmware
- Broadcom Wi-Fi: requires `broadcom-sta-dkms` or `firmware-brcm80211`
- Some Realtek Wi-Fi: requires `firmware-realtek`
- NVIDIA GPUs: install `nvidia-driver` after installation

### Limitations in Alpha 0.1
- Secure Boot: shim-signed is included but not fully tested; disable Secure Boot if boot fails
- Apple Silicon (ARM): not supported
- Some fingerprint readers: not supported
- NVIDIA Optimus hybrid graphics: limited support

## Reporting Issues

Report hardware compatibility and build issues at:
https://github.com/nozaqk/Bright-OS/issues

Include:
- Full hardware specifications (CPU, GPU, RAM, Wi-Fi chip, storage)
- `lspci -nn` output
- `dmesg` output if errors occur
- Whether you used BIOS or UEFI boot
- Which edition you tested
- Exact steps to reproduce
- Build log (for build failures): `build/output/<edition>/build.log`
