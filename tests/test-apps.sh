#!/bin/bash
# Quick syntax/import test for Bright OS Python applications
# Runs without GUI - checks for import errors and basic syntax

set -e
PASS=0
FAIL=0

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

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

echo ""
echo "--- Shell scripts ---"
for script in build/scripts/build.sh build/scripts/install-bright-os.sh build/scripts/validate-iso.sh \
              system/services/firstboot-setup.sh compatibility/wine/wine-prefix-setup.sh \
              build/live-build/auto/config build/live-build/auto/build build/live-build/auto/clean; do
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
         build/live-build/auto/config build/scripts/build.sh; do
    if [ -f "$f" ]; then
        echo -e "${GREEN}[PASS]${NC} $f exists"
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
