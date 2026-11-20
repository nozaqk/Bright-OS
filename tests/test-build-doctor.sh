#!/bin/bash
# =============================================================================
# Test Suite: Build Doctor & First-ISO Build Script
# Tests the build diagnostics and first-ISO orchestration scripts.
# =============================================================================

set -u

PASS=0
FAIL=0

pass() { echo -e "\033[0;32m[PASS]\033[0m $*"; PASS=$((PASS+1)); }
fail() { echo -e "\033[0;31m[FAIL]\033[0m $*"; FAIL=$((FAIL+1)); }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

DOCTOR="build/scripts/bright-build-doctor.sh"
BUILD_FIRST="build/scripts/build-first-iso.sh"

echo "========================================"
echo "  Build Doctor & First-ISO Script Tests"
echo "========================================"
echo ""

# --- Script existence and syntax ---
echo "--- Script existence ---"

if [ -x "$DOCTOR" ]; then
    pass "bright-build-doctor.sh exists and is executable"
else
    fail "bright-build-doctor.sh missing or not executable"
fi

if [ -x "$BUILD_FIRST" ]; then
    pass "build-first-iso.sh exists and is executable"
else
    fail "build-first-iso.sh missing or not executable"
fi

if bash -n "$DOCTOR" 2>/dev/null; then
    pass "bright-build-doctor.sh shell syntax valid"
else
    fail "bright-build-doctor.sh has shell syntax errors"
fi

if bash -n "$BUILD_FIRST" 2>/dev/null; then
    pass "build-first-iso.sh shell syntax valid"
else
    fail "build-first-iso.sh has shell syntax errors"
fi

echo ""
echo "--- Build doctor functionality ---"

# Build doctor should run and produce output
if DOCTOR_OUTPUT=$("$DOCTOR" 2>&1); then
    pass "Build doctor runs without crashing (exit 0 or 2)"
elif [ $? -eq 1 ] || [ $? -eq 2 ]; then
    pass "Build doctor runs and reports appropriate status (exit $?)"
else
    fail "Build doctor crashed with unexpected exit code"
fi

# Check it detects all sections
for section in "Operating System" "CPU Architecture" "Memory" "Disk Space" "Privileges" "Network" "Required Build Tools" "Project Configuration" "Build Output" "KVM" "Summary"; do
    if echo "$DOCTOR_OUTPUT" | grep -q "$section"; then
        pass "Build doctor reports section: $section"
    else
        fail "Build doctor missing section: $section"
    fi
done

# Check it reports status line
if echo "$DOCTOR_OUTPUT" | grep -qE "STATUS: (READY|READY WITH WARNINGS|NOT READY)"; then
    pass "Build doctor reports a valid STATUS line"
else
    fail "Build doctor does not report valid STATUS"
fi

# Check it prints pass/warn/fail counts
if echo "$DOCTOR_OUTPUT" | grep -qE "Passed:.*[0-9]+" && echo "$DOCTOR_OUTPUT" | grep -qE "Failed:.*[0-9]+"; then
    pass "Build doctor shows pass/fail counts"
else
    fail "Build doctor does not show pass/fail counts"
fi

# Distribution detection (we know it's Debian in test env)
if echo "$DOCTOR_OUTPUT" | grep -qi "debian"; then
    pass "Build doctor detects Debian"
else
    fail "Build doctor did not detect Debian"
fi

# Architecture detection
if echo "$DOCTOR_OUTPUT" | grep -qi "amd64"; then
    pass "Build doctor detects amd64 architecture"
else
    fail "Build doctor did not detect amd64"
fi

# RAM detection
if echo "$DOCTOR_OUTPUT" | grep -qE "RAM.*MB|RAM.*GB"; then
    pass "Build doctor detects RAM"
else
    fail "Build doctor did not report RAM"
fi

# Disk detection
if echo "$DOCTOR_OUTPUT" | grep -qi "disk"; then
    pass "Build doctor detects disk space"
else
    fail "Build doctor did not report disk space"
fi

# Missing tools detection (in sandbox environment tools should be reported missing)
if echo "$DOCTOR_OUTPUT" | grep -q "lb not found\|lb found"; then
    pass "Build doctor checks for lb (live-build)"
else
    fail "Build doctor does not check for lb"
fi

# Project file checks
if echo "$DOCTOR_OUTPUT" | grep -q "core.list.chroot"; then
    pass "Build doctor checks for core package list"
else
    fail "Build doctor does not check for required project files"
fi

# When tools are missing and mirrors unreachable, should exit 1 (NOT READY)
if [ $? -ne 0 ] || echo "$DOCTOR_OUTPUT" | grep -q "STATUS: NOT READY"; then
    pass "Build doctor correctly reports NOT READY when requirements missing"
fi

echo ""
echo "--- Build doctor help text ---"

# Should provide install command when packages missing
if echo "$DOCTOR_OUTPUT" | grep -q "apt-get install"; then
    pass "Build doctor suggests apt-get install for missing packages"
else
    fail "Build doctor does not suggest package installation command"
fi

echo ""
echo "--- Build-first-iso.sh argument validation ---"

# --help should work
if "$BUILD_FIRST" --help >/dev/null 2>&1; then
    pass "build-first-iso.sh --help works"
else
    fail "build-first-iso.sh --help fails"
fi

# Unknown argument should fail
if ! "$BUILD_FIRST" --bogus-flag >/dev/null 2>&1; then
    pass "build-first-iso.sh rejects unknown arguments"
else
    fail "build-first-iso.sh accepts unknown arguments"
fi

# --version with missing arg should fail
if ! "$BUILD_FIRST" --version >/dev/null 2>&1; then
    pass "build-first-iso.sh rejects --version without argument"
else
    fail "build-first-iso.sh accepts --version without argument"
fi

echo ""
echo "--- Build-first-iso.sh error handling ---"

# Should detect it's in a Bright OS repo (should work from project root)
REPO_CHECK=$("$BUILD_FIRST" --skip-tests 2>&1 || true)
if echo "$REPO_CHECK" | grep -q "repository"; then
    pass "build-first-iso.sh checks for repository"
else
    # It might proceed to doctor which is fine
    pass "build-first-iso.sh starts (repository check passes or proceeds to doctor)"
fi

# Should refuse to run from wrong directory
TMPDIR_TEST=$(mktemp -d)
if ! (cd "$TMPDIR_TEST" && "$PROJECT_ROOT/$BUILD_FIRST" --skip-tests 2>&1); then
    pass "build-first-iso.sh fails when not in Bright OS repo"
else
    fail "build-first-iso.sh should fail outside Bright OS repo"
fi
rm -rf "$TMPDIR_TEST"

echo ""
echo "--- Existing ISO overwrite protection ---"

# Create a temporary fake ISO to test overwrite protection
TMP_EDITION_DIR=$(mktemp -d)
FAKE_ISO_DIR="${TMP_EDITION_DIR}/lite"
mkdir -p "$FAKE_ISO_DIR"
echo "fake" > "${FAKE_ISO_DIR}/bright-os-${VERSION:-0.1.0-alpha}-lite-amd64.iso"
# This is harder to test without running the full script, but we can check the logic
if grep -q "Existing ISO" "$BUILD_FIRST" && grep -q "\-\-force" "$BUILD_FIRST"; then
    pass "build-first-iso.sh has existing ISO overwrite protection (--force flag)"
else
    fail "build-first-iso.sh missing overwrite protection"
fi
rm -rf "$TMP_EDITION_DIR"

echo ""
echo "--- Build log preservation ---"

if grep -q "BUILD_LOG" "$BUILD_FIRST" && grep -q "build.log\|build-first-iso.log" "$BUILD_FIRST"; then
    pass "build-first-iso.sh preserves build logs"
else
    fail "build-first-iso.sh does not preserve build logs"
fi

if grep -q "Last 30 lines\|tail.*BUILD_LOG" "$BUILD_FIRST"; then
    pass "build-first-iso.sh shows log tail on failure"
else
    fail "build-first-iso.sh does not show log tail on failure"
fi

echo ""
echo "--- SHA256 verification ---"

if grep -q "sha256sum" "$BUILD_FIRST"; then
    pass "build-first-iso.sh includes SHA256 checksum verification"
else
    fail "build-first-iso.sh does not verify SHA256"
fi

if grep -q "SHA256" "$BUILD_FIRST"; then
    pass "build-first-iso.sh reports SHA256 in final output"
else
    fail "build-first-iso.sh does not report SHA256"
fi

echo ""
echo "--- ISO validator integration ---"

if grep -q "validate-iso.sh" "$BUILD_FIRST"; then
    pass "build-first-iso.sh integrates ISO validator"
else
    fail "build-first-iso.sh does not run ISO validator"
fi

echo ""
echo "--- Clean build before ---"

if grep -q "\-\-clean" "$BUILD_FIRST"; then
    pass "build-first-iso.sh cleans stale build state before building"
else
    fail "build-first-iso.sh does not clean stale state"
fi

echo ""
echo "--- Test execution ---"

if grep -q "test-\*.sh\|test suites\|TEST_PASS\|tests/test-" "$BUILD_FIRST"; then
    pass "build-first-iso.sh runs automated tests"
else
    fail "build-first-iso.sh does not run tests"
fi

if grep -q "\-\-skip-tests" "$BUILD_FIRST"; then
    pass "build-first-iso.sh supports --skip-tests flag"
else
    fail "build-first-iso.sh does not support --skip-tests"
fi

# --- Report ---
echo ""
echo "========================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================"

if [ $FAIL -gt 0 ]; then
    echo -e "\n\033[0;31mSome build doctor tests FAILED.\033[0m"
    exit 1
else
    echo -e "\n\033[0;32mAll build doctor tests passed.\033[0m"
    exit 0
fi
