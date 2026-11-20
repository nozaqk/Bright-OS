#!/bin/bash
# Quick syntax/import test for Bright OS Python applications
# Runs without GUI - checks for import errors and basic syntax

set -e
PASS=0
FAIL=0

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== Bright OS Application Tests ==="

test_py() {
    local name="$1"
    local path="$2"
    if python3 -c "import py_compile; py_compile.compile('${path}', doraise=True)" 2>/dev/null; then
        echo -e "${GREEN}[PASS]${NC} $name"
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $name (syntax error)"
        FAIL=$((FAIL+1))
    fi
}

test_py "bright-desktop-shell.py" desktop/shell/bright-desktop-shell.py
test_py "bright-terminal" applications/bright-terminal/bright-terminal
test_py "bright-files" applications/bright-files/bright-files
test_py "bright-settings" applications/bright-settings/bright-settings
test_py "bright-monitor" applications/bright-monitor/bright-monitor
test_py "bright-control-center" applications/bright-control-center/bright-control-center
test_py "bright-launcher" applications/bright-launcher/bright-launcher
test_py "bright-update" applications/bright-update/bright-update
test_py "bright-store" applications/bright-store/bright-store
test_py "bright-about" applications/bright-about/bright-about

echo ""
echo "--- Shell scripts ---"
for script in build/scripts/build.sh build/scripts/install-bright-os.sh build/scripts/validate-iso.sh \
              system/services/firstboot-setup.sh compatibility/wine/wine-prefix-setup.sh \
              system/security/firewall-defaults.sh \
              desktop/shell/bright-desktop-session.sh \
              build/live-build/auto/config build/live-build/auto/build build/live-build/auto/clean \
              config/hooks/live/00-bright-os-branding.hook.chroot \
              config/hooks/live/10-bright-os-components.hook.chroot \
              config/hooks/live/20-installer-setup.hook.chroot \
              installer/calamares/modules/postcfg.sh; do
    if bash -n "$script" 2>/dev/null; then
        echo -e "${GREEN}[PASS]${NC} $script"
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $script (syntax error)"
        FAIL=$((FAIL+1))
    fi
done

echo ""
echo "--- File existence checks ---"
for f in README.md LICENSE docs/BUILDING.md docs/HARDWARE-TESTING.md \
         branding/icons/bright-os-logo.svg branding/wallpapers/bright-default-dark.svg \
         branding/wallpapers/bright-default-light.svg desktop/shell/Shell.qml \
         build/live-build/auto/config build/scripts/build.sh \
         installer/calamares/settings.conf \
         installer/calamares/modules/welcome.conf \
         installer/calamares/modules/partition.conf \
         installer/calamares/modules/users.conf \
         installer/calamares/modules/bootloader.conf \
         installer/calamares/modules/unpackfs.conf \
         installer/calamares/modules/fstab.conf \
         installer/calamares/modules/services-systemd.conf \
         installer/calamares/modules/shellprocess-post.conf \
         installer/calamares/modules/postcfg.sh \
         installer/calamares/modules/keyboard.conf \
         installer/calamares/modules/locale.conf \
         installer/calamares/modules/finished.conf \
         installer/calamares/modules/networkcfg.conf \
         installer/calamares/modules/summary.conf \
         installer/calamares/modules/exclude-list \
         installer/calamares/branding/bright-os/branding.desc \
         installer/calamares/branding/bright-os/show.qml \
         branding/plymouth/bright-os.plymouth \
         branding/plymouth/bright-os.script \
         branding/grub/theme.txt \
         desktop/themes/dark/qt6ct.conf \
         desktop/themes/dark/colors.conf \
         desktop/themes/light/qt6ct.conf \
         desktop/shell/bright-desktop-session.sh \
         editions/home/packages.list \
         editions/developer/packages.list \
         editions/lite/packages.list \
         config/package-lists/base.list.chroot \
         config/includes.binary/boot/grub/grub.cfg \
         config/includes.chroot/etc/bright-os/edition \
         config/includes.chroot/etc/skel/Desktop/install-bright-os.desktop \
         system/security/99-bright-os-sysctl.conf \
         system/networking/99-bright-os-network.conf \
         system/services/bright-os-firstboot.service; do
    if [ -f "$f" ]; then
        echo -e "${GREEN}[PASS]${NC} $f"
        PASS=$((PASS+1))
    else
        echo -e "${RED}[FAIL]${NC} $f missing"
        FAIL=$((FAIL+1))
    fi
done

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ] && echo -e "${GREEN}All tests passed!${NC}" || echo -e "${RED}Some tests failed.${NC}"
exit $FAIL
