#!/bin/bash
# Bright OS comprehensive test suite
# Checks syntax, file existence, and integration correctness
set -e
PASS=0
FAIL=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo "=== Bright OS Test Suite ==="

# Portable syntax check: uses a helper that compiles the Python source to
# bytecode in a temp location so the test does not require write access to
# the source tree. This works correctly when running as a non-root user
# (e.g. "nobody") against a read-only / protected checkout.
test_py() {
    local name="$1"; local path="$2"
    if python3 tests/support/py_syntax_check.py "$path" 2>/dev/null; then
        echo -e "${GREEN}[PASS]${NC} $name"; PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $name (syntax error)"; FAIL=$((FAIL+1))
    fi
}

test_sh() {
    local name="$1"; local path="$2"
    if bash -n "$path" 2>/dev/null; then
        echo -e "${GREEN}[PASS]${NC} $name"; PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $name (syntax error)"; FAIL=$((FAIL+1))
    fi
}

test_file() {
    local path="$1"
    if [ -f "$path" ]; then
        echo -e "${GREEN}[PASS]${NC} $path"; PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $path missing"; FAIL=$((FAIL+1))
    fi
}

# ---- Python app syntax ----
echo ""
echo "--- Python Application Syntax ---"
test_py "bright-desktop-shell.py" desktop/shell/bright-desktop-shell.py
for app in bright-terminal bright-files bright-settings bright-monitor \
           bright-control-center bright-launcher bright-update bright-store bright-about; do
    test_py "$app" "applications/${app}/${app}"
done

# ---- Shell script syntax ----
echo ""
echo "--- Shell Script Syntax ---"
for script in build/scripts/build.sh build/scripts/install-bright-os.sh \
              build/scripts/validate-iso.sh build/scripts/test-in-qemu.sh \
              system/services/firstboot-setup.sh compatibility/wine/wine-prefix-setup.sh \
              system/security/firewall-defaults.sh desktop/shell/bright-desktop-session.sh \
              build/live-build/auto/config build/live-build/auto/build build/live-build/auto/clean \
              config/hooks/live/00-bright-os-branding.hook.chroot \
              config/hooks/live/10-bright-os-components.hook.chroot \
              config/hooks/live/20-installer-setup.hook.chroot \
              config/includes.chroot/lib/live/config/05-bright-os \
              installer/calamares/modules/postcfg.sh; do
    test_sh "$(basename $script)" "$script"
done

# ---- Core files ----
echo ""
echo "--- Core Files ---"
for f in README.md LICENSE docs/BUILDING.md docs/HARDWARE-TESTING.md .gitignore; do
    test_file "$f"
done

# ---- Branding ----
echo ""
echo "--- Branding Assets ---"
for f in branding/icons/bright-os-logo.svg \
         branding/wallpapers/bright-default-dark.svg \
         branding/wallpapers/bright-default-light.svg \
         branding/plymouth/bright-os.plymouth \
         branding/plymouth/bright-os.script \
         branding/grub/theme.txt; do
    test_file "$f"
done

# ---- Themes ----
echo ""
echo "--- Desktop Themes ---"
for f in desktop/themes/dark/qt6ct.conf desktop/themes/dark/colors.conf desktop/themes/light/qt6ct.conf; do
    test_file "$f"
done

# ---- Desktop shell ----
echo ""
echo "--- Desktop Shell ---"
for f in desktop/shell/Shell.qml desktop/shell/bright-desktop-shell.py desktop/shell/bright-desktop-session.sh; do
    test_file "$f"
done

# ---- Build system ----
echo ""
echo "--- Build System ---"
for f in build/live-build/auto/config build/scripts/build.sh config/package-lists/core.list.chroot; do
    test_file "$f"
done

# ---- Editions ----
echo ""
echo "--- Editions ---"
for ed in home developer lite; do
    test_file "editions/${ed}/packages.list"
done

# ---- Calamares modules ----
echo ""
echo "--- Calamares Installer Modules ---"
test_file "installer/calamares/settings.conf"
for mod in welcome.conf locale.conf keyboard.conf partition.conf users.conf \
           summary.conf finished.conf mount.conf unpackfs.conf machineid.conf fstab.conf \
           localecfg.conf networkcfg.conf hwclock.conf services-systemd.conf bootloader.conf \
           luksbootkeyfile.conf initramfscfg.conf initramfs.conf grubcfg.conf \
           shellprocess-post.conf postcfg.sh exclude-list; do
    test_file "installer/calamares/modules/${mod}"
done
test_file "installer/calamares/branding/bright-os/branding.desc"
test_file "installer/calamares/branding/bright-os/show.qml"

# ---- Chroot includes ----
echo ""
echo "--- Live System Includes ---"
for f in config/includes.binary/boot/grub/grub.cfg \
         config/includes.chroot/etc/bright-os/edition \
         config/includes.chroot/etc/skel/Desktop/install-bright-os.desktop \
         config/includes.chroot/etc/sysctl.d/99-bright-os-sysctl.conf \
         config/includes.chroot/etc/NetworkManager/conf.d/99-bright-os-network.conf \
         config/includes.chroot/etc/systemd/system/bright-os-firstboot.service \
         config/includes.chroot/etc/default/grub.d/bright-os.cfg \
         config/includes.chroot/usr/share/wayland-sessions/bright.desktop \
         config/includes.chroot/usr/share/xsessions/bright.desktop \
         config/includes.chroot/usr/share/bright-os/Shell.qml \
         config/includes.chroot/usr/share/bright-os/bright-desktop-shell.py \
         config/includes.chroot/usr/share/bright-os/wallpapers/bright-default-dark.svg \
         config/includes.chroot/usr/share/bright-os/wallpapers/bright-default-light.svg \
         config/includes.chroot/usr/share/bright-os/icons/bright-os-logo.svg \
         config/includes.chroot/usr/lib/bright-os/firstboot-setup; do
    test_file "$f"
done

# Check all bright-* binaries are present
for app in bright-about bright-control-center bright-desktop-shell bright-files \
           bright-launcher bright-monitor bright-settings bright-store \
           bright-terminal bright-update wine-prefix-setup; do
    test_file "config/includes.chroot/usr/bin/${app}"
done

# ---- System services/security ----
echo ""
echo "--- System Configuration ---"
test_file "system/security/99-bright-os-sysctl.conf"
test_file "system/networking/99-bright-os-network.conf"
test_file "system/services/bright-os-firstboot.service"

# ---- Integration checks ----
echo ""
echo "--- Integration Validation ---"

# Check shell QML doesn't use MultiEffect in actual code (comments are ok)
# Strip both // line comments and /* */ block comments
QML_CODE=$(sed 's|//.*||g' desktop/shell/Shell.qml | perl -0777 -pe 's|/\*.*?\*/||gs')
if echo "$QML_CODE" | grep -q "QtQuick\.Effects\|MultiEffect"; then
    echo -e "${RED}[FAIL]${NC} Shell.qml uses QtQuick.Effects/MultiEffect (requires Qt 6.5+, Bookworm has 6.4)"
    FAIL=$((FAIL+1))
else
    echo -e "${GREEN}[PASS]${NC} Shell.qml is Qt 6.4 compatible (no MultiEffect in code)"
    PASS=$((PASS+1))
fi

# Check Wayland session Exec line points to correct binary
if grep -q "^Exec=/usr/bin/bright-desktop-shell" config/includes.chroot/usr/share/wayland-sessions/bright.desktop; then
    echo -e "${GREEN}[PASS]${NC} Wayland session Exec is correct"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Wayland session Exec line is wrong"
    FAIL=$((FAIL+1))
fi

# Check wrapper script exists and is executable
if [ -x config/includes.chroot/usr/bin/bright-desktop-shell ]; then
    echo -e "${GREEN}[PASS]${NC} bright-desktop-shell wrapper is executable"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} bright-desktop-shell wrapper not executable"
    FAIL=$((FAIL+1))
fi

# Check package list doesn't have snapd (bloat)
if grep -q "^snapd" config/package-lists/core.list.chroot; then
    echo -e "${RED}[FAIL]${NC} Package list still includes snapd"
    FAIL=$((FAIL+1))
else
    echo -e "${GREEN}[PASS]${NC} Package list doesn't include snapd"
    PASS=$((PASS+1))
fi

# Check Plymouth uses script module (not spinner)
if grep -q "^ModuleName=script" branding/plymouth/bright-os.plymouth; then
    echo -e "${GREEN}[PASS]${NC} Plymouth theme uses script module"
    PASS=$((PASS+1))
else
    echo -e "${RED}[FAIL]${NC} Plymouth theme doesn't use script module"
    FAIL=$((FAIL+1))
fi

# Check Calamares settings doesn't reference netinstall instance
if grep -q "netinstall" installer/calamares/settings.conf; then
    echo -e "${RED}[FAIL]${NC} Calamares settings.conf references undefined netinstall"
    FAIL=$((FAIL+1))
else
    echo -e "${GREEN}[PASS]${NC} Calamares settings.conf doesn't reference undefined modules"
    PASS=$((PASS+1))
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
