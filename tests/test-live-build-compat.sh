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
    
    case "$version" in
        modern)
            # Debian Trixie/Sid live-build 1:2025xxxx
            bootloader_help="--bootloaders grub-legacy|grub-pc|syslinux|grub-efi"
            secureboot_help="--uefi-secure-boot auto|enable|disable"
            ;;
        legacy)
            # Ubuntu 24.04 live-build 3.0~a57
            bootloader_help="--bootloader grub|syslinux|yaboot"
            arch_opt="--architectures"
            binary_opt="--binary-images"
            has_parent_areas="no"
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
# Should NOT use legacy options
if echo "$ARGS" | grep -q -- "--bootloader " && ! echo "$ARGS" | grep -q -- "--bootloaders"; then
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
# Should NOT include --parent-archive-areas (not supported in legacy)
if echo "$ARGS" | grep -q -- "--parent-archive-areas"; then
    fail "Legacy: should NOT include --parent-archive-areas (not supported)"
else
    pass "Legacy: correctly omits --parent-archive-areas"
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
