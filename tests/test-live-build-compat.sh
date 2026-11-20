#!/bin/bash
# =============================================================================
# Live-build version compatibility tests
#
# Tests that auto/config correctly detects live-build capabilities and uses
# appropriate options for:
#   - Modern Debian live-build (Trixie/Sid): --bootloaders, --uefi-secure-boot
#   - Legacy live-build (Ubuntu 24.04 3.0~a57): --bootloader, no --uefi-secure-boot
#   - Partial support scenarios
#   - BIOS/UEFI preservation
#   - Clear error/warning handling
#
# Uses mock lb binaries simulating different versions; does NOT run real lb build.
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0; FAIL=0
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "============================================"
echo "  Live-build Version Compatibility Tests"
echo "============================================"

echo ""
echo "--- Syntax check ---"
bash -n build/live-build/auto/config && pass "auto/config syntax valid" || fail "auto/config has syntax errors"
bash -n config/hooks/live/30-efi-boot-setup.hook.binary && pass "EFI boot hook syntax valid" || fail "EFI hook has syntax errors"

# ---------------------------------------------------------------------------
# Helper: create a mock lb that simulates a specific live-build version
# ---------------------------------------------------------------------------
# Arguments:
#   $1 = mock bin directory
#   $2 = version name (modern, legacy, partial-bootloaders, partial-secureboot, no-bootloader)
create_mock_lb() {
    local mockdir="$1"
    local version="$2"
    mkdir -p "$mockdir"
    
    # Build the help text based on version
    local bootloader_help=""
    local secureboot_help=""
    local arch_opt="--architecture"
    local binary_opt="--binary-image"
    local has_parent_areas="yes"
    local has_mode="yes"
    local has_keyring="yes"
    local mode_opt="--mode debian"
    local keyring_opt="--keyring-packages"
    
    case "$version" in
        modern)
            # Debian Trixie/Sid live-build 1:2025xxxx
            bootloader_help="--bootloaders grub-legacy|grub-pc|syslinux|grub-efi"
            secureboot_help="--uefi-secure-boot auto|enable|disable"
            ;;
        legacy)
            # Ubuntu 24.04 live-build 3.0~a57-1ubuntuXX (confirmed real help format)
            bootloader_help="--bootloader grub|syslinux|yaboot"
            arch_opt="--architectures"
            binary_opt="--binary-images"
            mode_opt="--mode debian|emdebian|ubuntu|kubuntu"
            # Ubuntu legacy DOES support --parent-archive-areas (confirmed from manpage)
            has_parent_areas="yes"
            ;;
        partial-bootloaders)
            # Has modern bootloaders but no secure boot
            bootloader_help="--bootloaders grub-legacy|grub-pc|syslinux|grub-efi"
            ;;
        partial-secureboot)
            # Has secure boot but only legacy bootloader option
            bootloader_help="--bootloader grub|syslinux"
            secureboot_help="--uefi-secure-boot auto|enable|disable"
            ;;
        no-bootloader)
            # Neither option - should fail
            ;;
        no-mode)
            # Has bootloaders but no --mode option (very old version)
            bootloader_help="--bootloaders grub-legacy|grub-pc|syslinux|grub-efi"
            secureboot_help="--uefi-secure-boot auto|enable|disable"
            has_mode="no"
            ;;
        singular-arch)
            # Modern bootloaders but uses --architectures (plural)
            bootloader_help="--bootloaders grub-legacy|grub-pc|syslinux|grub-efi"
            secureboot_help="--uefi-secure-boot auto|enable|disable"
            arch_opt="--architectures"
            ;;
    esac
    
    cat > "$mockdir/lb" << MOCKEOF
#!/bin/bash
# Mock lb for version: $version
if [ "\$1" = "config" ] && [ "\$2" = "--help" ]; then
    echo "Usage: lb config [options]"
    echo "  -a|${arch_opt} ARCHITECTURE"
    echo "  -b|${binary_opt} iso|iso-hybrid|netboot|tar|hdd"
    echo "  --archive-areas AREAS"
    [ -n "$bootloader_help" ] && echo "  $bootloader_help"
    [ -n "$secureboot_help" ] && echo "  $secureboot_help"
    [ "$has_parent_areas" = "yes" ] && echo "  --parent-archive-areas AREAS"
    [ "$has_mode" = "yes" ] && echo "  $mode_opt"
    [ "$has_keyring" = "yes" ] && echo "  $keyring_opt PACKAGE"
    echo "  --debian-installer cdrom|netinst|netboot|live|none|false"
    echo "  --distribution CODENAME"
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
# Record lb config arguments
if [ "\$1" = "config" ]; then
    echo "LB_ARGS:\$@" >> "\$LB_CAPTURE_FILE"
    # Create minimal config structure
    mkdir -p config/bootloaders 2>/dev/null || true
    exit 0
fi
echo "Mock lb: unrecognized command: \$@" >&2
exit 1
MOCKEOF
    chmod +x "$mockdir/lb"
}

# Helper: run auto/config in a test directory with a specific mock lb version
run_config_test() {
    local version="$1"
    local testdir="$TMPDIR/build-$version"
    
    rm -rf "$testdir"
    mkdir -p "$testdir"
    cd "$testdir"
    
    # Copy auto scripts
    mkdir -p auto
    cp "$PROJECT_ROOT/build/live-build/auto/config" auto/config
    cp "$PROJECT_ROOT/build/live-build/auto/build" auto/build
    cp "$PROJECT_ROOT/build/live-build/auto/clean" auto/clean
    chmod +x auto/*
    
    # Create minimal config skeleton
    mkdir -p config/package-lists config/includes.chroot/etc/bright-os
    echo "home" > config/includes.chroot/etc/bright-os/edition
    cp -r "$PROJECT_ROOT/config/package-lists" config/ 2>/dev/null || true
    
    # Create mock lb
    create_mock_lb "$testdir/mock-bin" "$version"
    
    # Run auto/config
    LB_CAPTURE_FILE="$testdir/lb-args.txt"
    rm -f "$LB_CAPTURE_FILE"
    export LB_CAPTURE_FILE
    
    set +e
    PATH="$testdir/mock-bin:$PATH" \
    BRIGHT_EDITION=lite BRIGHT_ARCH=amd64 BRIGHT_VERSION=0.1.0-alpha BRIGHT_DEBIAN_CODENAME=trixie \
        ./auto/config > "$testdir/output.log" 2>&1
    CONFIG_EXIT=$?
    set -e
    
    cd "$PROJECT_ROOT"
    
    echo "$CONFIG_EXIT" > "$testdir/exitcode.txt"
}

# Helper to get captured args for a test version
get_args() {
    local version="$1"
    cat "$TMPDIR/build-$version/lb-args.txt" 2>/dev/null || echo ""
}

get_output() {
    local version="$1"
    cat "$TMPDIR/build-$version/output.log" 2>/dev/null || echo ""
}

get_exit() {
    local version="$1"
    cat "$TMPDIR/build-$version/exitcode.txt" 2>/dev/null || echo "1"
}

echo ""
echo "--- Testing modern live-build (Debian Trixie) ---"
run_config_test "modern"

# Verify modern options are used
ARGS=$(get_args "modern")
EXIT=$(get_exit "modern")

if [ "$EXIT" = "0" ]; then
    pass "Modern live-build: auto/config exits 0"
else
    fail "Modern live-build: auto/config exits $EXIT (expected 0)"
fi
if echo "$ARGS" | grep -q -- "--bootloaders grub-pc,grub-efi"; then
    pass "Modern: uses --bootloaders grub-pc,grub-efi for BIOS+UEFI"
else
    fail "Modern: --bootloaders grub-pc,grub-efi not found in args"
fi
if echo "$ARGS" | grep -q -- "--uefi-secure-boot auto"; then
    pass "Modern: uses --uefi-secure-boot auto"
else
    fail "Modern: --uefi-secure-boot auto not found"
fi
if echo "$ARGS" | grep -q -- "--architecture amd64"; then
    pass "Modern: uses --architecture (singular)"
else
    fail "Modern: --architecture not found"
fi
if echo "$ARGS" | grep -q -- "--binary-image iso-hybrid"; then
    pass "Modern: uses --binary-image (singular)"
else
    fail "Modern: --binary-image not found"
fi
if echo "$ARGS" | grep -q -- "--parent-archive-areas"; then
    pass "Modern: includes --parent-archive-areas"
else
    fail "Modern: --parent-archive-areas missing"
fi
# Must pass --mode debian
if echo "$ARGS" | grep -q -- "--mode debian"; then
    pass "Modern: passes --mode debian"
else
    fail "Modern: --mode debian missing (critical: Ubuntu mode auto-detection risk)"
fi
# Must pass --keyring-packages debian-archive-keyring
if echo "$ARGS" | grep -q -- "--keyring-packages debian-archive-keyring"; then
    pass "Modern: uses --keyring-packages debian-archive-keyring"
else
    fail "Modern: debian-archive-keyring missing"
fi
# Must NOT contain any ubuntu references
if echo "$ARGS" | grep -qi "ubuntu"; then
    fail "Modern: arguments contain 'ubuntu' (would produce Ubuntu derivative)"
else
    pass "Modern: no ubuntu references in arguments"
fi
# Must use plural bootloaders
if echo "$ARGS" | grep -q -- "--bootloaders grub-pc,grub-efi"; then
    pass "Modern: uses --bootloaders grub-pc,grub-efi (BIOS+UEFI)"
else
    fail "Modern: --bootloaders grub-pc,grub-efi missing"
fi
# Should NOT use legacy options
if echo "$ARGS" | grep -q -- "--bootloader grub" && ! echo "$ARGS" | grep -q -- "--bootloaders"; then
    fail "Modern: incorrectly using legacy --bootloader (singular)"
else
    pass "Modern: not using legacy --bootloader"
fi

echo ""
echo "--- Testing legacy live-build (Ubuntu 24.04, 3.0~a57) ---"
run_config_test "legacy"

ARGS=$(get_args "legacy")
EXIT=$(get_exit "legacy")
OUTPUT=$(get_output "legacy")

if [ "$EXIT" = "0" ]; then
    pass "Legacy live-build: auto/config exits 0"
else
    fail "Legacy live-build: auto/config exits $EXIT (expected 0)"
fi
# Should NOT pass --bootloaders (unsupported)
if echo "$ARGS" | grep -q -- "--bootloaders"; then
    fail "Legacy: should NOT use --bootloaders (unsupported option)"
else
    pass "Legacy: correctly omits --bootloaders (unsupported)"
fi
# Should NOT pass --uefi-secure-boot (unsupported)
if echo "$ARGS" | grep -q -- "--uefi-secure-boot"; then
    fail "Legacy: should NOT use --uefi-secure-boot (unsupported)"
else
    pass "Legacy: correctly omits --uefi-secure-boot (unsupported)"
fi
# Should use plural forms for this version
if echo "$ARGS" | grep -q -- "--architectures amd64"; then
    pass "Legacy: uses --architectures (plural, correct for this version)"
else
    fail "Legacy: --architectures not found (expected plural for this version)"
fi
if echo "$ARGS" | grep -q -- "--binary-images iso-hybrid"; then
    pass "Legacy: uses --binary-images (plural, correct for this version)"
else
    fail "Legacy: --binary-images not found"
fi
# Legacy DOES support --parent-archive-areas (confirmed from Ubuntu manpage)
if echo "$ARGS" | grep -q -- "--parent-archive-areas"; then
    pass "Legacy: includes --parent-archive-areas (supported on Ubuntu 24.04)"
else
    fail "Legacy: --parent-archive-areas missing"
fi
# Must pass --mode debian (CRITICAL: prevents Ubuntu mode auto-detection)
if echo "$ARGS" | grep -q -- "--mode debian"; then
    pass "Legacy: passes --mode debian (prevents Ubuntu host auto-detection)"
else
    fail "Legacy: --mode debian MISSING — would default to Ubuntu mode on Ubuntu hosts!"
fi
# Must pass --keyring-packages debian-archive-keyring
if echo "$ARGS" | grep -q -- "--keyring-packages debian-archive-keyring"; then
    pass "Legacy: uses --keyring-packages debian-archive-keyring (not ubuntu-keyring)"
else
    fail "Legacy: debian-archive-keyring missing — would use ubuntu-keyring!"
fi
# Must pass --bootloader grub (verified working for EFI support)
if echo "$ARGS" | grep -q -- "--bootloader grub"; then
    pass "Legacy: passes --bootloader grub (enables GRUB for EFI boot)"
else
    fail "Legacy: --bootloader grub missing"
fi
# Must NOT contain any ubuntu references in the arguments
if echo "$ARGS" | grep -qi "ubuntu"; then
    fail "Legacy: arguments contain 'ubuntu' (would produce Ubuntu derivative)"
else
    pass "Legacy: no ubuntu references in arguments"
fi
# Must keep target distribution as trixie
if echo "$ARGS" | grep -q -- "--distribution trixie"; then
    pass "Legacy: target distribution remains trixie"
else
    fail "Legacy: target distribution not set to trixie"
fi
# Should report the legacy notice
if echo "$OUTPUT" | grep -qi "legacy live-build\|older live-build"; then
    pass "Legacy: reports legacy/older live-build notice"
else
    fail "Legacy: does not report legacy live-build notice"
fi
# Should warn about Secure Boot
if echo "$OUTPUT" | grep -qi "secure boot"; then
    pass "Legacy: reports Secure Boot limitation"
else
    fail "Legacy: does not warn about Secure Boot limitation"
fi

echo ""
echo "--- Testing partial support: bootloaders without secure-boot ---"
run_config_test "partial-bootloaders"

ARGS=$(get_args "partial-bootloaders")
EXIT=$(get_exit "partial-bootloaders")
OUTPUT=$(get_output "partial-bootloaders")

if [ "$EXIT" = "0" ]; then
    pass "Partial (bootloaders only): auto/config exits 0"
else
    fail "Partial (bootloaders only): auto/config exits $EXIT"
fi
if echo "$ARGS" | grep -q -- "--bootloaders grub-pc,grub-efi"; then
    pass "Partial: uses --bootloaders when available"
else
    fail "Partial: --bootloaders not found"
fi
if echo "$ARGS" | grep -q -- "--uefi-secure-boot"; then
    fail "Partial: should NOT use --uefi-secure-boot (not available)"
else
    pass "Partial: correctly omits --uefi-secure-boot when unavailable"
fi

echo ""
echo "--- Testing partial support: secure-boot with legacy bootloader ---"
run_config_test "partial-secureboot"

ARGS=$(get_args "partial-secureboot")
EXIT=$(get_exit "partial-secureboot")

if [ "$EXIT" = "0" ]; then
    pass "Partial (secureboot only): auto/config exits 0"
else
    fail "Partial (secureboot only): auto/config exits $EXIT"
fi
if echo "$ARGS" | grep -q -- "--uefi-secure-boot auto"; then
    pass "Partial (secureboot): uses --uefi-secure-boot when available"
else
    fail "Partial (secureboot): --uefi-secure-boot not found"
fi
if echo "$ARGS" | grep -q -- "--bootloaders"; then
    fail "Partial (secureboot): should NOT use --bootloaders (only --bootloader available)"
else
    pass "Partial (secureboot): correctly omits --bootloaders"
fi

echo ""
echo "--- Testing unsupported version (no bootloader option at all) ---"
run_config_test "no-bootloader"

EXIT=$(get_exit "no-bootloader")
OUTPUT=$(get_output "no-bootloader")

if [ "$EXIT" != "0" ]; then
    pass "No-bootloader: auto/config fails with non-zero exit"
else
    fail "No-bootloader: should fail but exits 0"
fi
if echo "$OUTPUT" | grep -qi "error\|cannot determine"; then
    pass "No-bootloader: reports clear error message"
else
    fail "No-bootloader: should report error about unsupported version"
fi

echo ""
echo "--- Testing singular/plural arch option adaptation ---"
run_config_test "singular-arch"

ARGS=$(get_args "singular-arch")
EXIT=$(get_exit "singular-arch")

if [ "$EXIT" = "0" ]; then
    pass "Singular-arch: auto/config exits 0"
else
    fail "Singular-arch: auto/config exits $EXIT"
fi
# This version reports --architectures (plural) in help, so we should use that
if echo "$ARGS" | grep -q -- "--architectures amd64"; then
    pass "Singular-arch: correctly uses --architectures (per help detection)"
else
    fail "Singular-arch: should use --architectures as detected from help"
fi

echo ""
echo "--- Testing BIOS/UEFI configuration preservation ---"
# Verify both bootloaders are specified on modern
ARGS_MODERN=$(get_args "modern")
if echo "$ARGS_MODERN" | grep -q "grub-pc" && echo "$ARGS_MODERN" | grep -q "grub-efi"; then
    pass "Modern: both grub-pc (BIOS) and grub-efi (UEFI) specified"
else
    fail "Modern: missing grub-pc or grub-efi in bootloaders"
fi
# Verify iso-hybrid image type (required for BIOS+UEFI hybrid)
if echo "$ARGS_MODERN" | grep -q "iso-hybrid"; then
    pass "Modern: iso-hybrid image type preserved"
else
    fail "Modern: iso-hybrid missing"
fi
if echo "$(get_args "legacy")" | grep -q "iso-hybrid"; then
    pass "Legacy: iso-hybrid image type preserved"
else
    fail "Legacy: iso-hybrid missing"
fi

echo ""
echo "--- Testing target distribution preserved (not downgraded) ---"
for version in modern legacy partial-bootloaders; do
    if echo "$(get_args "$version")" | grep -q -- "--distribution trixie"; then
        pass "$version: target distribution remains trixie"
    else
        fail "$version: target distribution not set to trixie"
    fi
done

echo ""
echo "--- Testing required options always present ---"
for version in modern legacy partial-bootloaders partial-secureboot singular-arch; do
    ARGS_V=$(get_args "$version")
    OK=true
    for opt in "--distribution" "--checksums sha256" "--firmware-binary true" \
               "--firmware-chroot true" "--debian-installer false" "--memtest none" \
               "--win32-loader false" "--apt-recommends true"; do
        if ! echo "$ARGS_V" | grep -q -- "$opt"; then
            fail "$version: missing required option: $opt"
            OK=false
        fi
    done
    if [ "$OK" = true ]; then
        pass "$version: all common required options present"
    fi
done

echo ""
echo "--- Testing EFI boot hook exists ---"
if [ -x config/hooks/live/30-efi-boot-setup.hook.binary ]; then
    pass "EFI boot verification hook exists and is executable"
else
    fail "EFI boot hook missing or not executable"
fi
if grep -q "BRIGHT_REQUIRE_UEFI" config/hooks/live/30-efi-boot-setup.hook.binary; then
    pass "EFI hook respects BRIGHT_REQUIRE_UEFI environment variable"
else
    fail "EFI hook does not check BRIGHT_REQUIRE_UEFI"
fi
if grep -q "BIOS.*UEFI\|UEFI.*BIOS" config/hooks/live/30-efi-boot-setup.hook.binary; then
    pass "EFI hook checks both BIOS and UEFI boot structures"
else
    fail "EFI hook does not verify both BIOS and UEFI"
fi

echo ""
echo "--- Testing no-mode live-build (very old, no --mode option) ---"
run_config_test "no-mode"

ARGS=$(get_args "no-mode")
EXIT=$(get_exit "no-mode")

if [ "$EXIT" = "0" ]; then
    pass "No-mode: auto/config exits 0 (graceful fallback)"
else
    fail "No-mode: auto/config exits $EXIT (should succeed, just skip --mode)"
fi
if echo "$ARGS" | grep -q -- "--mode"; then
    fail "No-mode: should NOT pass --mode (unsupported in this version)"
else
    pass "No-mode: correctly omits --mode when not supported"
fi
# Even without --mode, should NOT contain any ubuntu references
if echo "$ARGS" | grep -qi "ubuntu"; then
    fail "No-mode: arguments contain 'ubuntu'"
else
    pass "No-mode: no ubuntu references"
fi

echo ""
echo "--- Integration test: legacy Ubuntu host scenario ---"
# Simulate a realistic Ubuntu 24.04 host where lb writes config/bootstrap
# We extend the legacy mock to write a config/bootstrap file that mimics
# what live-build actually does: defaults to LB_MODE based on /etc/os-release
# unless --mode is explicitly passed.
UBUNTU_HOST_TEST="$TMPDIR/ubuntu-host-realistic"
rm -rf "$UBUNTU_HOST_TEST"
mkdir -p "$UBUNTU_HOST_TEST"
cd "$UBUNTU_HOST_TEST"

mkdir -p auto
cp "$PROJECT_ROOT/build/live-build/auto/config" auto/config
chmod +x auto/config

mkdir -p config/package-lists config/includes.chroot/etc/bright-os
echo "home" > config/includes.chroot/etc/bright-os/edition
cp -r "$PROJECT_ROOT/config/package-lists" config/ 2>/dev/null || true

# Realistic Ubuntu 24.04 lb mock that writes config/bootstrap and respects --mode
mkdir -p mock-bin
cat > mock-bin/lb << 'MOCKEOF'
#!/bin/bash
# Realistic Ubuntu 24.04 live-build 3.0~a57 simulation
# Defaults to UBUNTU mode based on host /etc/os-release unless --mode debian
if [ "$1" = "config" ] && [ "$2" = "--help" ]; then
cat << 'HELP'
Usage: lb config [options]
  -a|--architectures ARCHITECTURE
  -b|--binary-images iso|iso-hybrid|netboot|tar|hdd
  --archive-areas AREAS
  --parent-archive-areas AREAS
  --bootloader grub|syslinux|yaboot
  --bootstrap cdebootstrap|debootstrap
  --bootstrap-keyring PACKAGE
  --distribution CODENAME
  --mode debian|emdebian|ubuntu|kubuntu
  --keyring-packages PACKAGE | "PACKAGES"
  --mirror-bootstrap URL
  --mirror-binary URL
  --mirror-chroot URL
  --debian-installer cdrom|netinst|netboot|live|none|false
  --checksums md5|sha1|sha256|none
  --iso-application NAME
  --iso-publisher NAME
  --iso-volume NAME
  --iso-preparer NAME
  --memtest memtest86+|memtest86|none
  --firmware-binary true|false
  --firmware-chroot true|false
  --win32-loader true|false
  --zsync true|false
  --initsystem sysvinit|systemd|none
  --apt-recommends true|false
  --apt-options OPTIONS
  --syslinux-theme THEME_SUFFIX
HELP
    exit 0
fi
if [ "$1" = "config" ]; then
    shift
    # Parse arguments and simulate live-build's default behavior
    MODE="ubuntu"        # DEFAULT on Ubuntu hosts (from /etc/os-release detection)
    DIST=""
    KEYRING="ubuntu-keyring"  # DEFAULT on Ubuntu
    ARCH=""
    BOOTLOADER=""
    while [ $# -gt 0 ]; do
        case "$1" in
            noauto) ;;
            --mode) shift; MODE="$1" ;;
            --distribution) shift; DIST="$1" ;;
            --keyring-packages) shift; KEYRING="$1" ;;
            --architectures) shift; ARCH="$1" ;;
            --bootloader) shift; BOOTLOADER="$1" ;;
        esac
        shift
    done
    mkdir -p config
    cat > config/bootstrap << EOBT
LB_MODE="${MODE}"
LB_DISTRIBUTION="${DIST}"
LB_KEYRING_PACKAGES="${KEYRING}"
LB_ARCHITECTURES="${ARCH}"
LB_BOOTLOADER="${BOOTLOADER}"
LB_HDD_LABEL="$( [ "$MODE" = "ubuntu" ] && echo "UBUNTU" || echo "DEBIAN_LIVE" )"
LB_SYSLINUX_THEME="$( [ "$MODE" = "ubuntu" ] && echo "ubuntu-oneiric" || echo "live-build" )"
EOBT
    echo "LB_ARGS written to config/bootstrap (MODE=$MODE, KEYRING=$KEYRING)"
    exit 0
fi
exit 1
MOCKEOF
chmod +x mock-bin/lb

PATH="$UBUNTU_HOST_TEST/mock-bin:$PATH" \
BRIGHT_EDITION=home BRIGHT_ARCH=amd64 BRIGHT_VERSION=0.1.0-alpha BRIGHT_DEBIAN_CODENAME=trixie \
    ./auto/config > "$UBUNTU_HOST_TEST/output.log" 2>&1

INTEGRATION_EXIT=$?
if [ "$INTEGRATION_EXIT" = "0" ]; then
    pass "Integration (Ubuntu host): auto/config exits 0"
else
    fail "Integration (Ubuntu host): auto/config exits $INTEGRATION_EXIT"
fi

# Now examine the generated config/bootstrap file
if [ -f config/bootstrap ]; then
    pass "Integration (Ubuntu host): config/bootstrap generated"
else
    fail "Integration (Ubuntu host): config/bootstrap not created"
fi

# Check LB_MODE must be "debian", NOT "ubuntu"
if grep -q 'LB_MODE="debian"' config/bootstrap; then
    pass "Integration (Ubuntu host): LB_MODE=debian (correct Debian target)"
else
    MODE_VAL=$(grep LB_MODE config/bootstrap || echo "not found")
    fail "Integration (Ubuntu host): LB_MODE is NOT debian — got: $MODE_VAL"
fi

# Check LB_DISTRIBUTION must be "trixie"
if grep -q 'LB_DISTRIBUTION="trixie"' config/bootstrap; then
    pass "Integration (Ubuntu host): LB_DISTRIBUTION=trixie (correct target)"
else
    DIST_VAL=$(grep LB_DISTRIBUTION config/bootstrap || echo "not found")
    fail "Integration (Ubuntu host): LB_DISTRIBUTION not trixie — got: $DIST_VAL"
fi

# Check LB_KEYRING_PACKAGES must be "debian-archive-keyring"
if grep -q 'LB_KEYRING_PACKAGES="debian-archive-keyring"' config/bootstrap; then
    pass "Integration (Ubuntu host): LB_KEYRING_PACKAGES=debian-archive-keyring"
else
    KEYRING_VAL=$(grep LB_KEYRING_PACKAGES config/bootstrap || echo "not found")
    fail "Integration (Ubuntu host): keyring not debian-archive-keyring — got: $KEYRING_VAL"
fi

# Check NO ubuntu-keyring
if grep -q 'ubuntu-keyring' config/bootstrap; then
    fail "Integration (Ubuntu host): ubuntu-keyring found in generated config!"
else
    pass "Integration (Ubuntu host): no ubuntu-keyring in generated config"
fi

# Check HDD label not UBUNTU
if grep -q 'UBUNTU' config/bootstrap; then
    fail "Integration (Ubuntu host): UBUNTU HDD label present (branding leak)"
else
    pass "Integration (Ubuntu host): HDD label is not UBUNTU"
fi

# Check syslinux theme not ubuntu-oneiric
if grep -q 'ubuntu-oneiric' config/bootstrap; then
    fail "Integration (Ubuntu host): ubuntu-oneiric syslinux theme present"
else
    pass "Integration (Ubuntu host): syslinux theme is not ubuntu-oneiric"
fi

cd "$PROJECT_ROOT"

echo ""
echo "--- Testing build doctor capability checks ---"
if grep -q "live-build capability detection" build/scripts/bright-build-doctor.sh; then
    pass "Build doctor includes live-build capability detection"
else
    fail "Build doctor missing live-build capability detection"
fi
if grep -q "\-\-bootloaders\|\-\-uefi-secure-boot" build/scripts/bright-build-doctor.sh; then
    pass "Build doctor checks for --bootloaders and --uefi-secure-boot support"
else
    fail "Build doctor does not check bootloader/SecureBoot options"
fi
if grep -q "\-\-mode.*debian\|debian.*mode" build/scripts/bright-build-doctor.sh; then
    pass "Build doctor checks for --mode debian support"
else
    fail "Build doctor missing --mode debian check"
fi
if grep -q "debian-archive-keyring\|keyring-packages" build/scripts/bright-build-doctor.sh; then
    pass "Build doctor checks for debian-archive-keyring"
else
    fail "Build doctor missing keyring/debian-archive-keyring check"
fi
if grep -q "ubuntu" build/scripts/bright-build-doctor.sh; then
    pass "Build doctor warns about Ubuntu host/mode risk"
else
    fail "Build doctor does not warn about Ubuntu host auto-detection risk"
fi
if grep -q "30-efi-boot-setup.hook.binary" build/scripts/bright-build-doctor.sh; then
    pass "Build doctor checks for EFI boot hook file"
else
    fail "Build doctor missing EFI hook in required files"
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All live-build compatibility tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
