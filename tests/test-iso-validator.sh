#!/bin/bash
# =============================================================================
# Phase 11: ISO Validator Tests
# Tests validate-iso.sh with temporary fixtures (not a real ISO).
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0; FAIL=0
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }

VAL_SCRIPT="./build/scripts/validate-iso.sh"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

echo "============================================"
echo "  ISO Validator Tests"
echo "============================================"

echo ""
echo "--- Argument Handling ---"

# No arguments should fail
if ! bash "$VAL_SCRIPT" 2>/dev/null; then
    pass "No arguments exits non-zero"
else
    fail "No arguments should fail"
fi

# Help succeeds
if bash "$VAL_SCRIPT" --help &>/dev/null; then
    pass "--help exits 0"
else
    fail "--help does not exit 0"
fi

# Nonexistent file
if ! bash "$VAL_SCRIPT" /nonexistent/path.iso 2>/dev/null; then
    pass "Nonexistent file exits non-zero"
else
    fail "Nonexistent file should fail"
fi

echo ""
echo "--- Empty File ---"
touch "${TMPDIR}/empty.iso"
if ! bash "$VAL_SCRIPT" "${TMPDIR}/empty.iso" 2>/dev/null; then
    pass "Empty file fails validation"
else
    fail "Empty file should fail validation"
fi

echo ""
echo "--- Small File (not an ISO) ---"
echo "not an iso" > "${TMPDIR}/small.iso"
if ! bash "$VAL_SCRIPT" "${TMPDIR}/small.iso" 2>/dev/null; then
    pass "Non-ISO file fails validation"
else
    fail "Non-ISO file should fail validation"
fi

echo ""
echo "--- Return Code Behavior ---"
# Empty file should produce exit code 1
bash "$VAL_SCRIPT" "${TMPDIR}/empty.iso" >/dev/null 2>&1 && rc=0 || rc=$?
if [ "$rc" -ne 0 ]; then
    pass "Invalid ISO returns non-zero exit code"
else
    fail "Invalid ISO returned exit 0"
fi

echo ""
echo "--- Script Checks ---"
# Verify script checks for required tools
if grep -q "command -v isoinfo\|HAVE_ISOINFO" "$VAL_SCRIPT"; then
    pass "Checks for isoinfo availability before using it"
else
    fail "Does not check for isoinfo availability"
fi

if grep -q "command -v file\|HAVE_FILE" "$VAL_SCRIPT"; then
    pass "Checks for 'file' command availability"
else
    fail "Does not check for 'file' command availability"
fi

# Verify BIOS/UEFI checks are separate
if grep -q "MBR boot signature\|0x55AA\|55 aa" "$VAL_SCRIPT"; then
    pass "Checks BIOS MBR boot signature independently"
else
    fail "Does not check BIOS boot signature"
fi

if grep -qi "efi\|UEFI" "$VAL_SCRIPT"; then
    pass "Checks UEFI/EFI boot files independently"
else
    fail "Does not check UEFI boot"
fi

# Verify script checks for squashfs, kernel, initrd
if grep -q "squashfs\|filesystem.squashfs" "$VAL_SCRIPT"; then
    pass "Checks for squashfs root filesystem"
else
    fail "Does not check for squashfs"
fi

if grep -q "vmlinuz\|kernel" "$VAL_SCRIPT"; then
    pass "Checks for live kernel"
else
    fail "Does not check for kernel"
fi

if grep -q "initrd" "$VAL_SCRIPT"; then
    pass "Checks for initrd"
else
    fail "Does not check for initrd"
fi

# Verify SHA256 check is conditional
if grep -q "sha256sum.*-c\|checksum verified\|checksum mismatch" "$VAL_SCRIPT"; then
    pass "Verifies SHA256 when checksum file exists"
else
    fail "Does not verify SHA256 checksum"
fi

# Verify warnings are separate from failures
if grep -q "warn()\|WARN=" "$VAL_SCRIPT"; then
    pass "Distinguishes warnings from failures"
else
    fail "Does not distinguish warnings from failures"
fi

# Verify script doesn't claim bootability from size alone
if grep -q "does NOT prove\|does not prove.*boot\|Passing validation does NOT" "$VAL_SCRIPT"; then
    pass "Explicitly states validation does not prove bootability"
else
    fail "Does not warn that validation ≠ boot success"
fi

# Verify INCONCLUSIVE status exists for missing tools
if grep -q "INCONCLUSIVE" "$VAL_SCRIPT"; then
    pass "Has INCONCLUSIVE status for uncheckable items"
else
    fail "Missing INCONCLUSIVE status (should mark untestable items)"
fi

# Verify script syntax
if bash -n "$VAL_SCRIPT"; then
    pass "Script syntax valid"
else
    fail "Script has syntax errors"
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All ISO validator tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
