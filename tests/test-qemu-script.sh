#!/bin/bash
# =============================================================================
# Phase 11: QEMU Test Script Validation
# Tests argument parsing, validation, and command construction without
# actually running QEMU.
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0; FAIL=0
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }

QEMU_SCRIPT="./build/scripts/test-in-qemu.sh"

echo "============================================"
echo "  QEMU Test Script Validation"
echo "============================================"

# --- Syntax check ---
echo ""
echo "--- Syntax ---"
if bash -n "$QEMU_SCRIPT"; then
    pass "Script syntax valid"
else
    fail "Script has syntax errors"
fi

# --- Help ---
if bash "$QEMU_SCRIPT" --help &>/dev/null; then
    pass "--help exits 0"
else
    fail "--help does not exit 0"
fi

# --- Missing ISO produces error ---
if ! bash "$QEMU_SCRIPT" 2>/dev/null; then
    pass "No arguments (no ISO found) exits non-zero"
else
    fail "No arguments should fail (no ISO)"
fi

# --- Nonexistent ISO ---
if ! bash "$QEMU_SCRIPT" /nonexistent/file.iso 2>/dev/null; then
    pass "Nonexistent ISO path exits non-zero"
else
    fail "Nonexistent ISO path was accepted"
fi

# --- Invalid memory ---
# Create a dummy ISO
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT
touch "${TMPDIR}/test.iso"

if ! bash "$QEMU_SCRIPT" "${TMPDIR}/test.iso" -m abc 2>/dev/null; then
    pass "Non-numeric memory rejected"
else
    fail "Non-numeric memory accepted"
fi

if ! bash "$QEMU_SCRIPT" "${TMPDIR}/test.iso" -m 100 2>/dev/null; then
    pass "Memory below minimum rejected"
else
    fail "Memory below minimum accepted"
fi

if ! bash "$QEMU_SCRIPT" "${TMPDIR}/test.iso" -m 99999 2>/dev/null; then
    pass "Memory above maximum rejected"
else
    fail "Memory above maximum accepted"
fi

if ! bash "$QEMU_SCRIPT" "${TMPDIR}/test.iso" -m 0 2>/dev/null; then
    pass "Memory of 0 rejected"
else
    fail "Memory of 0 accepted"
fi

# --- Invalid CPUs ---
if ! bash "$QEMU_SCRIPT" "${TMPDIR}/test.iso" -c abc 2>/dev/null; then
    pass "Non-numeric CPU count rejected"
else
    fail "Non-numeric CPU count accepted"
fi

if ! bash "$QEMU_SCRIPT" "${TMPDIR}/test.iso" -c 0 2>/dev/null; then
    pass "CPU count of 0 rejected"
else
    fail "CPU count of 0 accepted"
fi

# --- Unknown options ---
if ! bash "$QEMU_SCRIPT" "${TMPDIR}/test.iso" --bogus 2>/dev/null; then
    pass "Unknown option rejected"
else
    fail "Unknown option accepted"
fi

if ! bash "$QEMU_SCRIPT" "${TMPDIR}/test.iso" -x 2>/dev/null; then
    pass "Unknown short option rejected"
else
    fail "Unknown short option accepted"
fi

# --- Verify script uses array for QEMU args (safe passing) ---
if grep -q 'QEMU_ARGS=(' "$QEMU_SCRIPT"; then
    pass "Uses array for QEMU arguments (safe word-splitting)"
else
    fail "Does not use array for QEMU arguments (fragile string splitting)"
fi

# --- Verify script doesn't claim boot success (look for positive claims, not negating comments) ---
# The script may mention "boot success" in comments explaining it does NOT claim success.
# Look for echo/print statements that actually tell the user the boot succeeded.
if ! grep -v '^[[:space:]]*#' "$QEMU_SCRIPT" | grep -qi "echo.*boot.*success\|echo.*successfully booted\|Boot.*successful\|SUCCESS.*boot"; then
    pass "Does not claim boot success just because QEMU launched"
else
    fail "Script incorrectly claims boot success to user"
fi

# --- Verify UEFI checks for OVMF ---
if grep -q "OVMF_CODE\|ovmf" "$QEMU_SCRIPT"; then
    pass "UEFI mode checks for OVMF firmware"
else
    fail "UEFI mode does not check for OVMF"
fi

# --- Verify KVM is auto-detected, not required ---
if grep -q "/dev/kvm" "$QEMU_SCRIPT"; then
    pass "KVM auto-detected (not required)"
else
    fail "KVM detection missing"
fi

# --- Verify BIOS and UEFI modes are supported ---
if grep -q "\-\-bios" "$QEMU_SCRIPT" && grep -q "\-\-uefi" "$QEMU_SCRIPT"; then
    pass "Both --bios and --uefi options supported"
else
    fail "BIOS/UEFI options missing"
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All QEMU script tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
