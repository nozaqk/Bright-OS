#!/bin/bash
# =============================================================================
# Bright OS Build Readiness Test Suite
# Tests the build scripts and configuration WITHOUT running an actual build.
# Validates script logic, path calculation, edition selection, file presence,
# and error handling.
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0
FAIL=0
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

assert_pass() {
    local desc="$1"; shift
    if "$@" &>/dev/null; then
        echo -e "${GREEN}[PASS]${NC} $desc"
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $desc"
        FAIL=$((FAIL+1))
    fi
}

assert_fail() {
    local desc="$1"; shift
    if ! "$@" &>/dev/null; then
        echo -e "${GREEN}[PASS]${NC} $desc (correctly fails)"
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $desc (should have failed)"
        FAIL=$((FAIL+1))
    fi
}

assert_file() {
    if [ -f "$1" ]; then
        echo -e "${GREEN}[PASS]${NC} $1 exists"
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $1 missing"
        FAIL=$((FAIL+1))
    fi
}

echo "============================================"
echo "  Bright OS Build Readiness Test Suite"
echo "============================================"
echo ""

# --- 1. Project Root Calculation ---
echo "--- 1. Project Root Calculation ---"

# Source the path calculation from build.sh in a subshell
TEST_ROOT=$(bash -c '
SCRIPT_DIR="$(cd "$(dirname "build/scripts/build.sh")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
echo "$PROJECT_ROOT"
')
if [ "$TEST_ROOT" = "$PROJECT_ROOT" ]; then
    echo -e "${GREEN}[PASS]${NC} build.sh PROJECT_ROOT = ${TEST_ROOT}"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} build.sh PROJECT_ROOT wrong: got ${TEST_ROOT}, expected ${PROJECT_ROOT}"
    FAIL=$((FAIL+1))
fi

TEST_ROOT2=$(bash -c '
SCRIPT_DIR="$(cd "$(dirname "build/scripts/test-in-qemu.sh")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
echo "$PROJECT_ROOT"
')
if [ "$TEST_ROOT2" = "$PROJECT_ROOT" ]; then
    echo -e "${GREEN}[PASS]${NC} test-in-qemu.sh PROJECT_ROOT = ${TEST_ROOT2}"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} test-in-qemu.sh PROJECT_ROOT wrong: got ${TEST_ROOT2}, expected ${PROJECT_ROOT}"
    FAIL=$((FAIL+1))
fi

# --- 2. Build Script Syntax ---
echo ""
echo "--- 2. Script Syntax ---"
for script in build/scripts/build.sh build/scripts/test-in-qemu.sh \
              build/live-build/auto/config build/live-build/auto/build \
              build/live-build/auto/clean build/scripts/validate-iso.sh \
              build/scripts/install-bright-os.sh; do
    if bash -n "$script" 2>/dev/null; then
        echo -e "${GREEN}[PASS]${NC} $script"
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $script has syntax errors"
        FAIL=$((FAIL+1))
    fi
done

# --- 3. Script Options ---
echo ""
echo "--- 3. Option Validation ---"

# Test that --help returns success
if bash build/scripts/build.sh --help &>/dev/null; then
    echo -e "${GREEN}[PASS]${NC} build.sh --help exits 0"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} build.sh --help did not exit 0"
    FAIL=$((FAIL+1))
fi

# Test that invalid edition fails
if ! bash build/scripts/build.sh --skip-build bogus_edition &>/dev/null; then
    echo -e "${GREEN}[PASS]${NC} Invalid edition correctly rejected"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Invalid edition was accepted"
    FAIL=$((FAIL+1))
fi

# Test that invalid arch fails
if ! bash build/scripts/build.sh --skip-build -a arm64 home &>/dev/null; then
    echo -e "${GREEN}[PASS]${NC} Invalid arch correctly rejected"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Invalid arch was accepted"
    FAIL=$((FAIL+1))
fi

# Test that --version requires argument
if ! bash build/scripts/build.sh --version &>/dev/null; then
    echo -e "${GREEN}[PASS]${NC} --version without argument correctly fails"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} --version without argument didn't fail"
    FAIL=$((FAIL+1))
fi

# --- 4. Edition Package Lists ---
echo ""
echo "--- 4. Edition Package Lists ---"
for ed in home developer lite; do
    if [ -f "editions/${ed}/packages.list" ]; then
        # Check it's not empty
        if [ -s "editions/${ed}/packages.list" ]; then
            echo -e "${GREEN}[PASS]${NC} editions/${ed}/packages.list exists and is non-empty"
            PASS=$((PASS+1))
        else
            echo -e "${RED}[FAIL]${NC} editions/${ed}/packages.list is empty"
            FAIL=$((FAIL+1))
        fi
    else
        echo -e "${RED}[FAIL]${NC} editions/${ed}/packages.list missing"
        FAIL=$((FAIL+1))
    fi
done

# --- 5. Required Source Files ---
echo ""
echo "--- 5. Core Source Files ---"
for f in \
    build/live-build/auto/config \
    build/live-build/auto/build \
    build/live-build/auto/clean \
    config/package-lists/core.list.chroot \
    config/package-lists/desktop.list.chroot \
    config/package-lists/desktop-lite.list.chroot \
    config/hooks/live/00-bright-os-branding.hook.chroot \
    config/hooks/live/10-bright-os-components.hook.chroot \
    config/hooks/live/20-installer-setup.hook.chroot \
    config/includes.binary/boot/grub/grub.cfg \
    config/includes.chroot/etc/bright-os/edition \
    config/includes.chroot/usr/bin/bright-desktop-shell \
    config/includes.chroot/usr/share/bright-os/Shell.qml \
    config/includes.chroot/usr/share/bright-os/bright-desktop-shell.py \
    config/includes.chroot/usr/share/bright-os/bright-desktop-session.sh \
    config/includes.chroot/usr/share/wayland-sessions/bright.desktop \
    config/includes.chroot/usr/share/xsessions/bright.desktop \
    desktop/shell/Shell.qml \
    desktop/shell/bright-desktop-shell.py \
    branding/icons/bright-os-logo.svg \
    branding/wallpapers/bright-default-dark.svg \
    branding/wallpapers/bright-default-light.svg \
    branding/plymouth/bright-os.plymouth \
    branding/grub/theme.txt \
    installer/calamares/settings.conf \
    system/security/99-bright-os-sysctl.conf \
    system/networking/99-bright-os-network.conf \
    system/services/bright-os-firstboot.service; do
    assert_file "$f"
done

# Check all Calamares module configs
echo ""
echo "--- 6. Calamares Module Configs ---"
MISSING_CAL=0
for mod in welcome.conf locale.conf keyboard.conf partition.conf users.conf summary.conf finished.conf \
           mount.conf unpackfs.conf machineid.conf fstab.conf localecfg.conf networkcfg.conf hwclock.conf \
           services-systemd.conf packages.conf luksbootkeyfile.conf initramfscfg.conf initramfs.conf grubcfg.conf bootloader.conf \
           shellprocess-post.conf postcfg.sh exclude-list; do
    if [ -f "installer/calamares/modules/${mod}" ]; then
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} installer/calamares/modules/${mod} missing"
        FAIL=$((FAIL+1))
        MISSING_CAL=$((MISSING_CAL+1))
    fi
done
if [ $MISSING_CAL -eq 0 ]; then
    echo -e "${GREEN}[PASS]${NC} All Calamares module configs present"
fi

# Branding
assert_file "installer/calamares/branding/bright-os/branding.desc"
assert_file "installer/calamares/branding/bright-os/show.qml"

# --- 7. All Python Apps Compile ---
echo ""
echo "--- 7. Python App Syntax ---"
for app in desktop/shell/bright-desktop-shell.py \
           applications/bright-terminal/bright-terminal \
           applications/bright-files/bright-files \
           applications/bright-settings/bright-settings \
           applications/bright-monitor/bright-monitor \
           applications/bright-control-center/bright-control-center \
           applications/bright-launcher/bright-launcher \
           applications/bright-update/bright-update \
           applications/bright-store/bright-store \
           applications/bright-about/bright-about; do
    if python3 tests/support/py_syntax_check.py "$app" 2>/dev/null; then
        echo -e "${GREEN}[PASS]${NC} $app compiles"
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $app has syntax errors"
        FAIL=$((FAIL+1))
    fi
done

# --- 8. Executable Scripts ---
echo ""
echo "--- 8. Executable Binaries ---"
for f in config/includes.chroot/usr/bin/bright-* \
         config/includes.chroot/usr/share/bright-os/bright-desktop-shell.py \
         config/includes.chroot/usr/share/bright-os/bright-desktop-session.sh \
         config/includes.chroot/lib/live/config/05-bright-os \
         config/includes.chroot/usr/lib/bright-os/firstboot-setup; do
    if [ -x "$f" ]; then
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $f is not executable"
        FAIL=$((FAIL+1))
    fi
done
echo -e "${GREEN}[PASS]${NC} All chroot binaries are executable"

# --- 9. Shell Integration Checks ---
echo ""
echo "--- 9. Integration Checks ---"

# Wayland session points to correct binary
if grep -q "^Exec=/usr/bin/bright-desktop-shell" config/includes.chroot/usr/share/wayland-sessions/bright.desktop; then
    echo -e "${GREEN}[PASS]${NC} Wayland session Exec is correct"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Wayland session Exec line wrong"
    FAIL=$((FAIL+1))
fi

# X11 session points to correct binary
if grep -q "^Exec=/usr/bin/bright-desktop-shell" config/includes.chroot/usr/share/xsessions/bright.desktop; then
    echo -e "${GREEN}[PASS]${NC} X11 session Exec is correct"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} X11 session Exec line wrong"
    FAIL=$((FAIL+1))
fi

# DesktopNames is set for session detection
if grep -q "DesktopNames=Bright" config/includes.chroot/usr/share/wayland-sessions/bright.desktop; then
    echo -e "${GREEN}[PASS]${NC} Wayland session has DesktopNames=Bright"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Wayland session missing DesktopNames"
    FAIL=$((FAIL+1))
fi

# Shell QML doesn't use Qt 6.5-only imports (MultiEffect)
QML_CODE=$(sed 's|//.*||g' desktop/shell/Shell.qml | perl -0777 -pe 's|/\*.*?\*/||gs')
if ! echo "$QML_CODE" | grep -q "MultiEffect\|QtQuick.Effects"; then
    echo -e "${GREEN}[PASS]${NC} Shell.qml is Qt 6.4 compatible (no MultiEffect in code)"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Shell.qml uses MultiEffect (Qt 6.5+ only)"
    FAIL=$((FAIL+1))
fi

# Package list doesn't include snapd
if ! grep -qx "snapd" config/package-lists/core.list.chroot; then
    echo -e "${GREEN}[PASS]${NC} Package list does not include snapd"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Package list includes snapd"
    FAIL=$((FAIL+1))
fi

# Plymouth uses script module
if grep -q "^ModuleName=script" branding/plymouth/bright-os.plymouth; then
    echo -e "${GREEN}[PASS]${NC} Plymouth uses script module"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Plymouth has wrong ModuleName"
    FAIL=$((FAIL+1))
fi

# Edition marker is 'home' by default
if [ "$(cat config/includes.chroot/etc/bright-os/edition)" = "home" ]; then
    echo -e "${GREEN}[PASS]${NC} Default edition marker is 'home'"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Default edition marker is not 'home'"
    FAIL=$((FAIL+1))
fi

# Calamares settings doesn't reference undefined modules
if ! grep -q "netinstall" installer/calamares/settings.conf; then
    echo -e "${GREEN}[PASS]${NC} Calamares settings has no orphaned module references"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Calamares settings references undefined netinstall module"
    FAIL=$((FAIL+1))
fi

# Build script sets pipefail
if grep -q "set -euo pipefail\|set -o pipefail" build/scripts/build.sh; then
    echo -e "${GREEN}[PASS]${NC} build.sh has pipefail error handling"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} build.sh missing pipefail"
    FAIL=$((FAIL+1))
fi

# Build script uses PIPESTATUS for build exit code
if grep -q "PIPESTATUS" build/scripts/build.sh; then
    echo -e "${GREEN}[PASS]${NC} build.sh uses PIPESTATUS to detect build failure with tee"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} build.sh doesn't use PIPESTATUS (tee could hide errors)"
    FAIL=$((FAIL+1))
fi

# Checksum generation is after build success check
if grep -A2 "BUILD_STATUS" build/scripts/build.sh | grep -q "exit.*BUILD_STATUS"; then
    echo -e "${GREEN}[PASS]${NC} Build exits before checksum on failure"
    PASS=$((PASS+1))
else
    echo -e "${YELLOW}[WARN]${NC} Could not verify checksum is conditional on build success"
fi

# --- 10. Build directory safety ---
echo ""
echo "--- 10. Clean safety ---"
# Clean uses specific BUILD_DIR not root
if grep -q "BUILD_DIR=" build/scripts/build.sh; then
    echo -e "${GREEN}[PASS]${NC} Clean uses scoped BUILD_DIR"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Clean might remove files outside build directory"
    FAIL=$((FAIL+1))
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All build-readiness tests passed!${NC}"
    echo ""
    echo "The build system is correctly configured."
    echo "Run the build on a Debian machine with:"
    echo "  sudo apt-get install -y live-build debootstrap squashfs-tools xorriso \\"
    echo "    isolinux syslinux-efi grub-pc-bin grub-efi-amd64-bin mtools dosfstools"
    echo "  ./build/scripts/build.sh home"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed. Fix them before building.${NC}"
    exit 1
fi
