#!/bin/bash
# =============================================================================
# Test Suite: Live Boot Media Configuration
# Validates that the live ISO boot configuration (GRUB, live-build, hooks)
# is correct for Debian Trixie and will produce a bootable ISO.
# =============================================================================

set -u

PASS=0
FAIL=0
WARN=0

pass() { echo -e "\033[0;32m[PASS]\033[0m $*"; PASS=$((PASS+1)); }
fail() { echo -e "\033[0;31m[FAIL]\033[0m $*"; FAIL=$((FAIL+1)); }
warn() { echo -e "\033[1;33m[WARN]\033[0m $*"; WARN=$((WARN+1)); }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "========================================"
echo "  Bright OS Live Boot Media Tests"
echo "========================================"
echo ""

# --- 1. GRUB configuration ---
echo "--- GRUB boot menu configuration ---"

GRUB_CFG="config/includes.binary/boot/grub/grub.cfg"

if [ -f "$GRUB_CFG" ]; then
    pass "GRUB grub.cfg exists for live media"
else
    fail "GRUB grub.cfg missing"
fi

# Memtest entry must NOT be present (we set --memtest none)
if grep -q "memtest" "$GRUB_CFG"; then
    fail "grub.cfg contains memtest entry (--memtest none is set; entry will fail at boot)"
else
    pass "grub.cfg does not reference memtest (consistent with --memtest none)"
fi

# Must have boot=live parameter
if grep -q "boot=live" "$GRUB_CFG"; then
    pass "GRUB entries use 'boot=live' parameter (live-boot)"
else
    fail "GRUB entries missing 'boot=live' parameter"
fi

# Must have linux/initrd lines
if grep -q "linux /live/vmlinuz" "$GRUB_CFG" && grep -q "initrd /live/initrd" "$GRUB_CFG"; then
    pass "GRUB entries reference /live/vmlinuz and /live/initrd.img"
else
    fail "GRUB entries missing correct kernel/initrd paths"
fi

# No invalid GRUB variables
if grep -q "menu_color_normal_highlight" "$GRUB_CFG"; then
    fail "grub.cfg uses invalid GRUB variable 'menu_color_normal_highlight'"
else
    pass "grub.cfg does not use invalid GRUB variables"
fi

# Default boot entry exists
if grep -q "set default=0" "$GRUB_CFG"; then
    pass "Default boot entry set (default=0)"
else
    warn "grub.cfg may not have default boot entry"
fi

echo ""
echo "--- GRUB theme ---"

GRUB_THEME="config/includes.binary/boot/grub/themes/bright-os/theme.txt"
if [ -f "$GRUB_THEME" ]; then
    pass "GRUB theme exists in includes.binary for live media"
    # Must NOT reference missing PNG images
    if grep -qE '\.png' "$GRUB_THEME"; then
        fail "GRUB theme references PNG images that may not exist"
    else
        pass "GRUB theme uses colors/fonts only (no missing PNG assets)"
    fi
else
    fail "GRUB theme not found in includes.binary"
fi

echo ""
echo "--- live-build configuration ---"

AUTO_CONFIG="build/live-build/auto/config"
if [ -f "$AUTO_CONFIG" ]; then
    pass "auto/config exists"
else
    fail "auto/config missing"
fi

# Check distribution is trixie
if grep -q 'trixie' "$AUTO_CONFIG"; then
    pass "auto/config uses Debian trixie as default codename"
else
    fail "auto/config may not use trixie as default"
fi

# Check iso-hybrid binary image type (required for USB bootable ISO)
if grep -q "iso-hybrid" "$AUTO_CONFIG"; then
    pass "auto/config uses iso-hybrid binary image type (USB-bootable)"
else
    fail "auto/config may use wrong binary image type (expected iso-hybrid)"
fi

# Check capability detection and BIOS+UEFI boot support
if grep -q "has_option.*bootloaders\|LB_HAS_MODERN_BOOTLOADERS\|Detecting live-build" "$AUTO_CONFIG"; then
    pass "auto/config includes live-build capability detection"
else
    fail "auto/config missing live-build capability detection"
fi

# Check that grub-pc,grub-efi is configured for modern live-build
if grep -q "grub-pc,grub-efi" "$AUTO_CONFIG"; then
    pass "auto/config configures grub-pc,grub-efi for BIOS+UEFI dual boot (modern live-build)"
else
    fail "auto/config bootloader configuration missing grub-pc,grub-efi"
fi

# Check that unsupported options are NOT passed blindly
if grep -q "LB_HELP=\$(lb config --help)\|has_option" "$AUTO_CONFIG"; then
    pass "auto/config detects capabilities before passing options to lb"
else
    fail "auto/config does not detect lb capabilities (may pass unsupported options)"
fi

# Check memtest none
if grep -q "\-\-memtest none" "$AUTO_CONFIG"; then
    pass "auto/config sets --memtest none"
else
    warn "auto/config does not set --memtest none"
fi

# Check checksums sha256
if grep -q "\-\-checksums sha256" "$AUTO_CONFIG"; then
    pass "auto/config enables SHA256 checksums"
else
    fail "auto/config does not enable SHA256 checksums"
fi

# Check no invalid flags in active (non-comment) lb config arguments
# Look for these flags only in lines that are part of the actual lb config command
# (not in comments documenting that they were removed)
if grep -v "^[[:space:]]*#" "$AUTO_CONFIG" | grep -q "\-\-efi-boot-partition-size"; then
    fail "auto/config uses invalid --efi-boot-partition-size flag"
else
    pass "auto/config does not use invalid --efi-boot-partition-size flag"
fi

if grep -v "^[[:space:]]*#" "$AUTO_CONFIG" | grep -q "\-\-swap-file-size"; then
    fail "auto/config uses invalid --swap-file-size flag"
else
    pass "auto/config does not use invalid --swap-file-size flag"
fi

echo ""
echo "--- Build hooks ---"

# Hooks must not call update-initramfs during build (live-build handles this)
INITRAMFS_HOOKS=0
for h in config/hooks/live/*.hook.chroot; do
    # Check for update-initramfs calls in non-comment lines
    if grep -v "^[[:space:]]*#" "$h" | grep -q "update-initramfs"; then
        fail "$h calls update-initramfs during build (live-build handles initramfs after hooks)"
        INITRAMFS_HOOKS=$((INITRAMFS_HOOKS+1))
    fi
done
if [ $INITRAMFS_HOOKS -eq 0 ]; then
    pass "No build hooks call update-initramfs prematurely"
fi

# Hook 00 must not fail if plymouth theme doesn't exist yet
if grep -q "plymouth-set-default-theme.*-R" config/hooks/live/00-bright-os-branding.hook.chroot 2>/dev/null; then
    fail "Hook 00 calls plymouth-set-default-theme -R (may fail before theme is installed)"
else
    pass "Hook 00 does not prematurely call plymouth-set-default-theme -R"
fi

echo ""
echo "--- Package list consistency ---"

# Check critical packages exist in core list (Phase 6.3: labwc + greetd)
CORE="config/package-lists/core.list.chroot"
for pkg in calamares cryptsetup-initramfs grub-pc-bin grub-efi-amd64-bin cryptsetup keyutils python3-pyqt6 qt6ct pipewire wireplumber network-manager flatpak initramfs-tools labwc greetd cage xdg-desktop-portal-wlr layer-shell-qt mako-notifier; do
    if grep -q "^${pkg}$" "$CORE"; then
        pass "Core package list includes $pkg"
    else
        fail "Core package list missing $pkg"
    fi
done

# shim-signed moved to optional-secureboot in Phase 6.3 (unsigned boot works on non-SB systems)
if grep -q "^shim-signed$" config/package-lists/optional-secureboot.list.chroot; then
    pass "shim-signed available in optional-secureboot profile"
else
    fail "shim-signed missing from optional-secureboot profile"
fi

# KWin + SDDM moved to optional-recovery-kwin in Phase 6.3
RECOVERY="config/package-lists/optional-recovery-kwin.list.chroot"
for pkg in sddm kwin-wayland; do
    if grep -q "^${pkg}$" "$RECOVERY"; then
        pass "Recovery profile includes $pkg"
    else
        fail "Recovery profile missing $pkg"
    fi
done

# Check Lite does not include Plasma/KWin/SDDM
for pkg in plasma-desktop plasma-workspace kwin-wayland sddm; do
    if grep -q "^${pkg}$" config/package-lists/desktop-lite.list.chroot; then
        fail "Lite desktop list unexpectedly includes $pkg"
    fi
done
pass "Lite desktop list does not include KDE Plasma components (Phase 6.3)"

# Check Home/Developer desktop list does NOT pull in full Plasma stack
# (Phase 6.3: desktop.list.chroot is now slim user apps, not Plasma)
if grep -q "^plasma-workspace$" config/package-lists/desktop.list.chroot; then
    fail "Default desktop list still pulls in full Plasma stack"
else
    pass "Default desktop list is lightweight (no full Plasma stack, Phase 6.3)"
fi

# Check essential user apps present in default desktop list
for pkg in firefox-esr mpv; do
    if grep -q "^${pkg}$" config/package-lists/desktop.list.chroot; then
        pass "Default desktop list includes $pkg"
    else
        fail "Default desktop list missing $pkg"
    fi
done

# Check for non-existent packages (common Trixie package naming issues)
# breeze-gtk-theme is correct in Trixie (the breeze-gtk package is GTK2/3 theme engine)
if grep -q "^breeze-gtk-theme$" "$CORE"; then
    fail "Package list uses wrong name 'breeze-gtk-theme' (package is 'breeze-gtk-theme' in Trixie)"
else
    pass "No invalid breeze-gtk-theme/breeze-gtk confusion"
fi

# Non-existent 'bluetooth' meta-package (bluez provides bluetoothd)
if grep -q "^bluetooth$" "$CORE" || grep -q "^bluetooth$" config/package-lists/desktop.list.chroot; then
    fail "Package list uses 'bluetooth' package (does not exist as a standalone package; use 'bluez')"
else
    pass "No invalid 'bluetooth' package (bluez provides bluetooth stack)"
fi

echo ""
echo "--- Edition package lists ---"
for ed in home developer lite; do
    if [ -f "editions/$ed/packages.list" ]; then
        pass "Edition packages.list for $ed exists"
    else
        fail "Edition packages.list for $ed missing"
    fi
done

echo ""
echo "--- Include files ---"
for f in \
    config/includes.chroot/usr/share/wayland-sessions/bright.desktop \
    config/includes.chroot/usr/share/xsessions/bright.desktop \
    config/includes.chroot/lib/live/config/05-bright-os \
    config/includes.chroot/etc/bright-os/edition \
    config/includes.chroot/usr/bin/bright-desktop-shell \
    config/includes.chroot/usr/share/bright-os/Shell.qml \
    config/includes.chroot/usr/share/bright-os/bright-desktop-shell.py \
    config/includes.chroot/usr/share/bright-os/installer/settings.conf \
    config/includes.chroot/etc/systemd/system/bright-os-firstboot.service \
    config/includes.chroot/usr/lib/bright-os/firstboot-setup \
    config/includes.chroot/usr/share/bright-os/plymouth/bright-os.plymouth \
    config/includes.chroot/usr/share/bright-os/plymouth/bright-os.script; do
    if [ -f "$f" ]; then
        pass "$(echo $f | sed 's|config/includes.chroot||') present"
    else
        fail "Missing include file: $f"
    fi
done

echo ""
echo "--- Shell script syntax (build-critical) ---"
for f in \
    build/scripts/build.sh \
    build/scripts/build-all.sh \
    build/scripts/setup-build-env.sh \
    build/scripts/validate-iso.sh \
    build/scripts/test-in-qemu.sh \
    build/live-build/auto/config \
    build/live-build/auto/build \
    build/live-build/auto/clean \
    config/hooks/live/00-bright-os-branding.hook.chroot \
    config/hooks/live/10-bright-os-components.hook.chroot \
    config/hooks/live/20-installer-setup.hook.chroot \
    config/includes.chroot/lib/live/config/05-bright-os \
    installer/calamares/modules/postcfg.sh \
    config/includes.chroot/usr/lib/bright-os/firstboot-setup; do
    if bash -n "$f" 2>/dev/null; then
        pass "Shell syntax: $(basename $f)"
    else
        fail "Shell syntax error in $f"
    fi
done

# --- Report ---
echo ""
echo "========================================"
echo "  Results: $PASS passed, $WARN warnings, $FAIL failed"
echo "========================================"

if [ $FAIL -gt 0 ]; then
    echo -e "\n\033[0;31mSome live boot media tests FAILED.\033[0m"
    exit 1
else
    echo -e "\n\033[0;32mAll live boot media tests passed.\033[0m"
    echo ""
    echo "NOTE: These tests validate configuration correctness only."
    echo "      Actual ISO build and boot testing are required to confirm a working ISO."
    exit 0
fi
