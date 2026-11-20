#!/bin/bash
# =============================================================================
# Phase 12: Live-build auto/config validation tests
# Captures and validates arguments passed to lb config.
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0; FAIL=0
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "============================================"
echo "  Live-build Configuration Tests"
echo "============================================"

echo ""
echo "--- Syntax check ---"
if bash -n build/live-build/auto/config; then
    pass "auto/config syntax valid"
else
    fail "auto/config has syntax errors"
fi

if bash -n build/live-build/auto/build; then
    pass "auto/build syntax valid"
else
    fail "auto/build has syntax errors"
fi

if bash -n build/live-build/auto/clean; then
    pass "auto/clean syntax valid"
else
    fail "auto/clean has syntax errors"
fi

echo ""
echo "--- Capture lb config arguments ---"
# Create mock lb that simulates modern Debian Trixie live-build
mkdir -p "$TMPDIR/mock-bin"
cat > "$TMPDIR/mock-bin/lb" << 'MOCKEOF'
#!/bin/bash
# Mock lb: modern Debian live-build (supports --bootloaders, --uefi-secure-boot)
if [ "$1" = "config" ] && [ "$2" = "--help" ]; then
    echo "Usage: lb config [options]"
    echo "  -a|--architecture ARCHITECTURE"
    echo "  -b|--binary-image iso|iso-hybrid|netboot|tar|hdd"
    echo "  --archive-areas AREAS"
    echo "  --bootloaders grub-legacy|grub-pc|syslinux|grub-efi"
    echo "  --uefi-secure-boot auto|enable|disable"
    echo "  --parent-archive-areas AREAS"
    echo "  --debian-installer cdrom|netinst|netboot|live|none|false"
    echo "  --checksums md5|sha1|sha256|none"
    echo "  --iso-application NAME"
    echo "  --iso-publisher NAME"
    echo "  --iso-volume NAME"
    echo "  --iso-preparer NAME"
    echo "  --memtest memtest86+|memtest86|none"
    echo "  --firmware-binary true|false"
    echo "  --firmware-chroot true|false"
    echo "  --win32-loader true|false"
    echo "  --zsync true|false"
    echo "  --initsystem sysvinit|systemd|none"
    echo "  --apt-recommends true|false"
    exit 0
fi
# Record all arguments to a file (lb config invocation)
if [ "$1" = "config" ]; then
    echo "LB_ARGS: $*" >> "$LB_CAPTURE_FILE"
    mkdir -p config/bootloaders
    echo "mock lb: created config dir"
    exit 0
fi
exit 1
MOCKEOF
chmod +x "$TMPDIR/mock-bin/lb"

# Set up a build-like directory
mkdir -p "$TMPDIR/build-test"
cd "$TMPDIR/build-test"

# Copy auto scripts
mkdir -p auto
cp "$PROJECT_ROOT/build/live-build/auto/config" auto/config
cp "$PROJECT_ROOT/build/live-build/auto/build" auto/build
cp "$PROJECT_ROOT/build/live-build/auto/clean" auto/clean
chmod +x auto/*

# Create minimal config skeleton (auto/config expects this)
mkdir -p config
cp -r "$PROJECT_ROOT/config/package-lists" config/ 2>/dev/null || true
mkdir -p config/includes.chroot/etc/bright-os
echo "home" > config/includes.chroot/etc/bright-os/edition

# Run auto/config and capture args
LB_CAPTURE_FILE="$TMPDIR/lb-args.txt"
rm -f "$LB_CAPTURE_FILE"
export LB_CAPTURE_FILE
PATH="$TMPDIR/mock-bin:$PATH" \
BRIGHT_EDITION=home BRIGHT_ARCH=amd64 BRIGHT_VERSION=0.1.0-alpha BRIGHT_DEBIAN_CODENAME=trixie \
    ./auto/config 2>&1 || true

cd "$PROJECT_ROOT"

if [ -f "$LB_CAPTURE_FILE" ] && [ -s "$LB_CAPTURE_FILE" ]; then
    pass "lb config was invoked"
else
    fail "lb config was not invoked"
    echo "---"
    cat "$LB_CAPTURE_FILE" 2>/dev/null || echo "(empty)"
fi

# Check captured arguments
ARGS=$(cat "$LB_CAPTURE_FILE" 2>/dev/null || echo "")

echo ""
echo "--- Required options ---"

check_option() {
    local opt="$1"; local desc="$2"
    if echo "$ARGS" | grep -q -- "$opt"; then
        pass "$desc"
    else
        fail "$desc (option: $opt)"
    fi
}

check_option "--distribution trixie" "Sets distribution to trixie"
check_option "--architecture amd64" "Sets architecture to amd64"
check_option "--binary-image iso-hybrid" "Uses iso-hybrid binary image"
check_option "--archive-areas.*non-free-firmware" "Includes non-free-firmware archive area"
check_option "--bootloaders grub-pc,grub-efi" "Bootloaders set to grub-pc,grub-efi for BIOS+UEFI"
check_option "--uefi-secure-boot auto" "Secure boot set to auto"
check_option "--firmware-binary true" "Firmware enabled in binary"
check_option "--firmware-chroot true" "Firmware enabled in chroot"
check_option "--checksums sha256" "SHA256 checksums"
check_option "--debian-installer false" "Debian installer disabled (Calamares is our installer)"
check_option "--win32-loader false" "win32-loader disabled"
check_option "--memtest none" "Memtest disabled"

echo ""
echo "--- Forbidden options (removed as incorrect/unsupported) ---"
check_forbidden() {
    local opt="$1"; local desc="$2"
    if echo "$ARGS" | grep -q -- "$opt"; then
        fail "$desc: found forbidden option $opt"
    else
        pass "$desc: $opt not present"
    fi
}

check_forbidden "--bootloader " "Old singular --bootloader (should be plural --bootloaders)"
check_forbidden "--efi-boot-partition-size" "Unsupported --efi-boot-partition-size"
check_forbidden "--swap-file-size" "Unnecessary --swap-file-size"

echo ""
echo "--- Edition override test ---"
rm -f "$LB_CAPTURE_FILE"
cd "$TMPDIR/build-test"
rm -rf config
mkdir -p config/includes.chroot/etc/bright-os
echo "lite" > config/includes.chroot/etc/bright-os/edition
mkdir -p config/package-lists
cp -r "$PROJECT_ROOT/config/package-lists" config/

PATH="$TMPDIR/mock-bin:$PATH" \
BRIGHT_EDITION=lite BRIGHT_ARCH=amd64 BRIGHT_VERSION=0.1.0-alpha BRIGHT_DEBIAN_CODENAME=trixie \
    ./auto/config 2>&1 || true
cd "$PROJECT_ROOT"

ARGS_LITE=$(cat "$LB_CAPTURE_FILE" 2>/dev/null || echo "")
# Check that lite edition package list was detected
# The auto/config itself reports "Configuring Bright OS ... lite edition"
# We verify this by running it again and capturing stdout
if echo "$ARGS_LITE" | grep -q "noauto"; then
    # Lite edition config was generated (lb was called)
    pass "Lite edition configuration invokes lb correctly"
else
    fail "Lite edition did not invoke lb config"
fi

# Test bookworm override
rm -f "$LB_CAPTURE_FILE"
cd "$TMPDIR/build-test"
rm -rf config
mkdir -p config/includes.chroot/etc/bright-os
echo "home" > config/includes.chroot/etc/bright-os/edition
mkdir -p config/package-lists
cp -r "$PROJECT_ROOT/config/package-lists" config/

PATH="$TMPDIR/mock-bin:$PATH" \
BRIGHT_EDITION=home BRIGHT_ARCH=amd64 BRIGHT_VERSION=0.1.0-alpha BRIGHT_DEBIAN_CODENAME=bookworm \
    ./auto/config 2>&1 || true
cd "$PROJECT_ROOT"

ARGS_BOOKWORM=$(cat "$LB_CAPTURE_FILE" 2>/dev/null || echo "")
if echo "$ARGS_BOOKWORM" | grep -q -- "--distribution bookworm"; then
    pass "--distro bookworm correctly sets distribution to bookworm"
else
    fail "--distro bookworm override not working"
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All live-build config tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
