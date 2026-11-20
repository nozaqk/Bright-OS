#!/bin/bash
# =============================================================================
# Phase 11: Build Pipeline Reliability Tests
# Tests build.sh failure propagation, argument validation, error handling,
# and safe file operations using a mocked environment (no real lb build).
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0
FAIL=0
RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }

# Set up a temporary test directory
TEST_DIR=$(mktemp -d)
cleanup() {
    rm -rf "$TEST_DIR"
}
trap cleanup EXIT

echo "============================================"
echo "  Build Pipeline Reliability Tests"
echo "  Test dir: $TEST_DIR"
echo "============================================"

# Copy the repository to test dir
TEST_REPO="${TEST_DIR}/Bright-OS"
cp -a . "${TEST_REPO}/"

# Create mock bin directory - only mock lb and dpkg-query; everything else is real
MOCK_BIN="${TEST_DIR}/mock-bin"
mkdir -p "$MOCK_BIN"

# Mock dpkg-query: returns "install ok installed" for any package
cat > "${MOCK_BIN}/dpkg-query" << 'MOCKEOF'
#!/bin/bash
# dpkg-query -W -f='${Status}' <pkg>
# Just output installed status for any package
if [ "$1" = "-W" ]; then
    echo "install ok installed"
    exit 0
fi
exit 1
MOCKEOF
chmod +x "${MOCK_BIN}/dpkg-query"

# Mock lb: controlled by MOCK_LB_BUILD_EXIT and optionally creates ISO
cat > "${MOCK_BIN}/lb" << 'MOCKEOF'
#!/bin/bash
LOG="${MOCK_LB_LOG:-/tmp/mock-lb.log}"
echo "[mock-lb $USER] $*" >> "$LOG"

if [ "$1" = "config" ]; then
    echo "P: Configuring live-build"
    exit 0
fi
if [ "$1" = "clean" ]; then
    exit 0
fi
if [ "$1" = "build" ]; then
    echo "P: Starting build"
    echo "I: Setting up chroot"
    echo "P: Downloading packages"
    echo "I: Installing packages"
    echo "P: Building squashfs"
    echo "P: Generating ISO"
    EXIT_CODE="${MOCK_LB_BUILD_EXIT:-0}"
    if [ "$EXIT_CODE" = "0" ] && [ "${MOCK_LB_CREATE_ISO:-1}" = "1" ]; then
        # Create a 10MB dummy hybrid ISO (not a real ISO, but a file for testing)
        dd if=/dev/zero of=live-image-amd64.hybrid.iso bs=1M count=10 2>/dev/null
        echo "I: ISO created"
    fi
    exit "$EXIT_CODE"
fi
echo "[mock-lb] unknown command: $1" >> "$LOG"
exit 1
MOCKEOF
chmod +x "${MOCK_BIN}/lb"

# Create stub mocks for other build dependencies (command -v checks)
for cmd in debootstrap mksquashfs xorriso; do
    cat > "${MOCK_BIN}/${cmd}" << MOCKEOF
#!/bin/bash
echo "[mock ${cmd}] \$@" >> "\$MOCK_LB_LOG"
exit 0
MOCKEOF
    chmod +x "${MOCK_BIN}/${cmd}"
done

# Mock df to report plenty of disk space (the test runs on tmpfs which may be small)
cat > "${MOCK_BIN}/df" << 'MOCKEOF'
#!/bin/bash
# Handle --output=avail <path>: just output enough available KB
echo "Available"
echo "188743680"
MOCKEOF
chmod +x "${MOCK_BIN}/df"

BUILD_SCRIPT="${TEST_REPO}/build/scripts/build.sh"

# Helper: run build with mock PATH (mock-bin prepended, rest of PATH intact)
run_build() {
    # Ensure /usr/bin and /bin are in PATH for coreutils
    PATH="${MOCK_BIN}:/usr/bin:/bin:${PATH}" \
    MOCK_LB_LOG="${TEST_DIR}/lb.log" \
    MOCK_LB_BUILD_EXIT="${MOCK_LB_BUILD_EXIT:-0}" \
    MOCK_LB_CREATE_ISO="${MOCK_LB_CREATE_ISO:-1}" \
        bash "${BUILD_SCRIPT}" "$@"
}

# =============================================================================
echo ""
echo "--- 1. Argument Validation ---"
# =============================================================================

# Invalid edition
if ! bash "${BUILD_SCRIPT}" bogus_edition --skip-build 2>/dev/null; then
    pass "Invalid edition rejected"
else
    fail "Invalid edition accepted"
fi

# Invalid arch
if ! bash "${BUILD_SCRIPT}" home -a arm64 --skip-build 2>/dev/null; then
    pass "Invalid arch rejected"
else
    fail "Invalid arch accepted"
fi

# Invalid version (contains slash)
if ! bash "${BUILD_SCRIPT}" home -v "bad/version" --skip-build 2>/dev/null; then
    pass "Invalid version (with slash) rejected"
else
    fail "Invalid version accepted"
fi

# Invalid codename
if ! bash "${BUILD_SCRIPT}" home -d sid --skip-build 2>/dev/null; then
    pass "Invalid codename 'sid' rejected"
else
    fail "Invalid codename accepted"
fi

# Duplicate edition
if ! bash "${BUILD_SCRIPT}" home developer --skip-build 2>/dev/null; then
    pass "Duplicate editions rejected"
else
    fail "Duplicate editions accepted"
fi

# Unknown option
if ! bash "${BUILD_SCRIPT}" home --bogus-flag --skip-build 2>/dev/null; then
    pass "Unknown option --bogus-flag rejected"
else
    fail "Unknown option accepted"
fi

# Unknown short option
if ! bash "${BUILD_SCRIPT}" home -x --skip-build 2>/dev/null; then
    pass "Unknown short option -x rejected"
else
    fail "Unknown short option accepted"
fi

# --help succeeds
if bash "${BUILD_SCRIPT}" --help &>/dev/null; then
    pass "--help exits 0"
else
    fail "--help did not exit 0"
fi

# =============================================================================
echo ""
echo "--- 2. Clean Mode ---"
# =============================================================================

# Create build dir with artifacts and a dummy ISO
mkdir -p "${TEST_REPO}/build/output/home/config"
mkdir -p "${TEST_REPO}/build/output/home/chroot"
mkdir -p "${TEST_REPO}/build/output/home/binary"
touch "${TEST_REPO}/build/output/home/config/testfile"
touch "${TEST_REPO}/build/output/home/chroot/testfile"
touch "${TEST_REPO}/build/output/home/bright-os-test.iso"

# Clean should work without any mocks (no dependency checks)
if bash "${BUILD_SCRIPT}" --clean home 2>/dev/null; then
    pass "--clean exits 0"
else
    fail "--clean did not exit 0"
fi

# Verify artifacts removed, ISO preserved
if [ ! -d "${TEST_REPO}/build/output/home/config" ] && [ ! -d "${TEST_REPO}/build/output/home/chroot" ]; then
    pass "--clean removes build artifacts"
else
    fail "--clean did not remove build artifacts"
fi
if [ -f "${TEST_REPO}/build/output/home/bright-os-test.iso" ]; then
    pass "--clean preserves ISO files"
else
    fail "--clean removed ISO files"
fi

# =============================================================================
echo ""
echo "--- 3. Build Failure Propagation ---"
# =============================================================================

rm -rf "${TEST_REPO}/build/output/home"

# Test specific exit codes are correctly captured
echo ""
echo "--- 3b. Exit Code Capture Precision ---"
for test_code in 1 2 42 127; do
    rm -rf "${TEST_REPO}/build/output/home"
    MOCK_LB_BUILD_EXIT=$test_code MOCK_LB_CREATE_ISO=0
    set +e
    run_build home >"${TEST_DIR}/ecode.out" 2>"${TEST_DIR}/ecode.err"
    actual_exit=$?
    set -e
    if [ "$actual_exit" = "$test_code" ]; then
        pass "Build exit code ${test_code} correctly propagates (got ${actual_exit})"
    else
        fail "Build exit code ${test_code} was mangled (got ${actual_exit})"
    fi
    # Verify no checksum on failure
    if [ ! -f "${TEST_REPO}/build/output/home/bright-os-0.1.0-alpha-home-amd64.iso.sha256" ]; then
        pass "  No checksum generated on exit ${test_code}"
    else
        fail "  Checksum incorrectly generated on exit ${test_code}"
    fi
done

# Verify exit code 0 (success) propagates correctly with grep filtering
rm -rf "${TEST_REPO}/build/output/home"
MOCK_LB_BUILD_EXIT=0 MOCK_LB_CREATE_ISO=0
set +e
run_build home 2>/dev/null
exit0_rc=$?
set -e
# This should FAIL because exit 0 but no ISO - but exit code should still be from build
# Actually without ISO it fails later; let's just verify the build part returned 0
# We test the "no ISO" case separately below

# Build with mock lb that exits with error code 1 (typical error)
rm -rf "${TEST_REPO}/build/output/home"
MOCK_LB_BUILD_EXIT=1 MOCK_LB_CREATE_ISO=0
if ! run_build home >"${TEST_DIR}/fail.out" 2>"${TEST_DIR}/fail.err"; then
    pass "Build exit code 1 correctly propagates as failure"
else
    fail "Build exit code 1 was treated as success"
fi

# Verify no checksum on failure
if [ ! -f "${TEST_REPO}/build/output/home/bright-os-0.1.0-alpha-home-amd64.iso.sha256" ]; then
    pass "No checksum generated on failed build"
else
    fail "Checksum generated despite build failure"
fi

if ! grep -q "BUILD SUCCESSFUL" "${TEST_DIR}/fail.out" 2>/dev/null; then
    pass "No BUILD SUCCESSFUL message on failure"
else
    fail "BUILD SUCCESSFUL appeared despite failure"
fi

# Build that succeeds but produces NO ISO (lb says 0 but no file)
rm -rf "${TEST_REPO}/build/output/home"
MOCK_LB_BUILD_EXIT=0 MOCK_LB_CREATE_ISO=0
if ! run_build home 2>"${TEST_DIR}/noiso.err"; then
    pass "Build exit 0 with no ISO correctly fails"
else
    fail "Build without ISO output was treated as success"
fi

# =============================================================================
echo ""
echo "--- 4. Successful Mock Build and Overwrite Protection ---"
# =============================================================================

rm -rf "${TEST_REPO}/build/output/home"
MOCK_LB_BUILD_EXIT=0 MOCK_LB_CREATE_ISO=1
if run_build home >"${TEST_DIR}/success.out" 2>"${TEST_DIR}/success.err"; then
    pass "Successful mock build exits 0"
else
    fail "Successful build did not exit 0"
    tail -20 "${TEST_DIR}/success.err"
fi

# Check ISO and checksum
if [ -f "${TEST_REPO}/build/output/home/bright-os-0.1.0-alpha-home-amd64.iso" ]; then
    pass "ISO correctly renamed to bright-os-0.1.0-alpha-home-amd64.iso"
else
    fail "ISO not found with expected name"
    ls "${TEST_REPO}/build/output/home/" 2>/dev/null || true
fi

if [ -f "${TEST_REPO}/build/output/home/bright-os-0.1.0-alpha-home-amd64.iso.sha256" ]; then
    pass "SHA256 checksum generated after success"
else
    fail "Checksum not generated"
fi

if grep -q "BUILD SUCCESSFUL" "${TEST_DIR}/success.out" 2>/dev/null; then
    pass "BUILD SUCCESSFUL message shown"
else
    fail "BUILD SUCCESSFUL message missing"
fi

# Second build with same version should refuse to overwrite
if ! run_build home 2>"${TEST_DIR}/overwrite.err"; then
    pass "Second build refuses to overwrite existing ISO"
else
    fail "Second build silently overwrote existing ISO"
fi

# =============================================================================
echo ""
echo "--- 5. --skip-build Configuration ---"
# =============================================================================

rm -rf "${TEST_REPO}/build/output/home"
if run_build home --skip-build 2>/dev/null; then
    pass "--skip-build exits 0"
else
    fail "--skip-build did not exit 0"
fi

if [ -d "${TEST_REPO}/build/output/home/config" ]; then
    pass "--skip-build creates config directory"
else
    fail "--skip-build did not create config directory"
fi

if [ "$(cat "${TEST_REPO}/build/output/home/config/includes.chroot/etc/bright-os/edition" 2>/dev/null)" = "home" ]; then
    pass "--skip-build writes correct edition marker (home)"
else
    val=$(cat "${TEST_REPO}/build/output/home/config/includes.chroot/etc/bright-os/edition" 2>/dev/null || echo "MISSING")
    fail "--skip-build edition marker is '$val' (expected 'home')"
fi

# =============================================================================
echo ""
echo "--- 6. Edition-specific package selection ---"
# =============================================================================

# Lite
rm -rf "${TEST_REPO}/build/output/lite"
if run_build lite --skip-build 2>/dev/null; then
    pass "--skip-build works for lite edition"
else
    fail "--skip-build failed for lite"
fi

DESKTOP_PKGS="${TEST_REPO}/build/output/lite/config/package-lists/desktop-packages.list.chroot"
if [ -f "$DESKTOP_PKGS" ] && grep -q "lxqt-core" "$DESKTOP_PKGS"; then
    pass "Lite uses desktop-lite.list.chroot (lxqt-core found)"
else
    fail "Lite desktop packages incorrect"
fi

if [ "$(cat "${TEST_REPO}/build/output/lite/config/includes.chroot/etc/bright-os/edition" 2>/dev/null)" = "lite" ]; then
    pass "Lite edition marker is 'lite'"
else
    fail "Lite edition marker incorrect"
fi

# Developer
rm -rf "${TEST_REPO}/build/output/developer"
if run_build developer --skip-build 2>/dev/null; then
    pass "--skip-build works for developer edition"
else
    fail "--skip-build failed for developer"
fi

DESKTOP_PKGS="${TEST_REPO}/build/output/developer/config/package-lists/desktop-packages.list.chroot"
if [ -f "$DESKTOP_PKGS" ] && grep -q "plasma-workspace" "$DESKTOP_PKGS"; then
    pass "Developer uses full Plasma desktop (plasma-workspace found)"
else
    fail "Developer desktop packages don't include plasma-workspace"
fi

if [ "$(cat "${TEST_REPO}/build/output/developer/config/includes.chroot/etc/bright-os/edition" 2>/dev/null)" = "developer" ]; then
    pass "Developer edition marker is 'developer'"
else
    fail "Developer edition marker incorrect"
fi

# Home
rm -rf "${TEST_REPO}/build/output/home"
if run_build home --skip-build 2>/dev/null; then
    pass "--skip-build works for home edition"
else
    fail "--skip-build failed for home"
fi
DESKTOP_PKGS="${TEST_REPO}/build/output/home/config/package-lists/desktop-packages.list.chroot"
if [ -f "$DESKTOP_PKGS" ] && grep -q "plasma-desktop" "$DESKTOP_PKGS"; then
    pass "Home uses full Plasma desktop (plasma-desktop found)"
else
    fail "Home desktop packages incorrect"
fi

# =============================================================================
echo ""
echo "--- 7. Build Directory Safety ---"
# =============================================================================

if grep -q 'BUILD_DIR.*outside project build' "${BUILD_SCRIPT}"; then
    pass "Build script has BUILD_DIR safety guard"
else
    fail "Build script missing BUILD_DIR safety guard"
fi

# Verify --clean only removes specific subdirs (not ISO)
if grep -q 'rm -rf.*config/.*local/.*\.build/' "${BUILD_SCRIPT}"; then
    pass "Clean uses specific rm targets (not rm -rf *)"
else
    fail "Clean may use unsafe rm"
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All build pipeline tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
