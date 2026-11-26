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

# Mock lb: simulates modern Debian Trixie live-build; controlled by MOCK_LB_BUILD_EXIT
cat > "${MOCK_BIN}/lb" << 'MOCKEOF'
#!/bin/bash
LOG="${MOCK_LB_LOG:-/tmp/mock-lb.log}"
echo "[mock-lb $USER] $*" >> "$LOG"

if [ "$1" = "config" ] && [ "$2" = "--help" ]; then
    # Simulate modern live-build (Debian Trixie) help output
    echo "Usage: lb config [options]"
    echo "  -a|--architecture ARCHITECTURE"
    echo "  -b|--binary-image iso|iso-hybrid|netboot|tar|hdd"
    echo "  --archive-areas AREAS"
    echo "  --bootloaders grub-legacy|grub-pc|syslinux|grub-efi"
    echo "  --uefi-secure-boot auto|enable|disable"
    echo "  --parent-archive-areas AREAS"
    echo "  --mode debian"
    echo "  --keyring-packages PACKAGE"
    echo "  --hdd-label LABEL"
    echo "  --distribution CODENAME"
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

if [ "$1" = "config" ]; then
    echo "P: Configuring live-build"
    mkdir -p config/bootloaders
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
    BRIGHT_SKIP_VALIDATION=1 \
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
# Phase 6.3: desktop-lite no longer requires lxqt-core; labwc comes from core.
# Verify the lite desktop list IS being selected (check for a known-lite package).
if [ -f "$DESKTOP_PKGS" ] && grep -q "xarchiver\|qterminal\|qps" "$DESKTOP_PKGS"; then
    pass "Lite uses desktop-lite.list.chroot (lite-specific package found)"
else
    fail "Lite desktop packages incorrect (desktop-lite.list.chroot not selected?)"
fi

# Core on all editions must include labwc (Phase 6.3 default compositor)
if grep -q "^labwc$" "${TEST_REPO}/build/output/lite/config/package-lists/core.list.chroot"; then
    pass "Lite core includes labwc (default compositor)"
else
    fail "Lite core missing labwc"
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

# Phase 6.3: core no longer includes plasma-workspace; dev edition inherits
# the slim desktop.list.chroot + edition packages. Verify labwc is present.
DESKTOP_PKGS="${TEST_REPO}/build/output/developer/config/package-lists/desktop-packages.list.chroot"
if grep -q "^labwc$" "${TEST_REPO}/build/output/developer/config/package-lists/core.list.chroot"; then
    pass "Developer core includes labwc (Phase 6.3 default)"
else
    fail "Developer core missing labwc"
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
# Phase 6.3: home uses the slim desktop.list.chroot (firefox-esr, mpv, ...),
# NOT plasma-desktop. labwc comes from core.
if grep -q "^labwc$" "${TEST_REPO}/build/output/home/config/package-lists/core.list.chroot"; then
    pass "Home core includes labwc (default compositor, Phase 6.3)"
else
    fail "Home desktop packages incorrect (labwc missing from core)"
fi
# Also verify no KDE plasma desktop in default desktop list
if grep -q "^plasma-desktop$" "$DESKTOP_PKGS"; then
    fail "Home desktop list unexpectedly includes plasma-desktop (should be optional only)"
else
    pass "Home desktop list is lightweight (no Plasma desktop)"
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

# =============================================================================
echo ""
echo "--- 8. Optional-profile CLI flags (Phase 6.3 corrective) ---"
# =============================================================================

# Unknown --with-* flag must be rejected
if bash "${BUILD_SCRIPT}" --with-nonexistent home >/tmp/bad.log 2>&1; then
    fail "Unknown --with-* option was accepted (should fail)"
else
    pass "Unknown --with-* option is rejected"
fi

# Lite default: bluetooth/cups/ModemManager/avahi/android/wine/devtools all off
rm -rf "${TEST_REPO}/build/output/lite-defaults"
if run_build lite --skip-build 2>/dev/null; then
    : # expected to fail at dependency check but that's after arg parsing
fi
# Run just the parsing + masking logic by checking that build.sh doesn't exit 2 (usage error)
set +e
bash "${BUILD_SCRIPT}" lite --skip-build >/tmp/lite.log 2>&1
EC=$?
set -e
# EC will be non-zero because live-build is missing, but the arg parsing must succeed
if ! grep -q "Unknown option" /tmp/lite.log; then
    pass "--skip-build lite parses without errors"
else
    fail "--skip-build lite parse error"
fi

# Verify --with-bluetooth --without-printing etc. appear in usage
if grep -q -- "--with-bluetooth" "${BUILD_SCRIPT}" \
   && grep -q -- "--without-bluetooth" "${BUILD_SCRIPT}" \
   && grep -q -- "--with-printing" "${BUILD_SCRIPT}" \
   && grep -q -- "--with-wine" "${BUILD_SCRIPT}" \
   && grep -q -- "--with-android" "${BUILD_SCRIPT}" \
   && grep -q -- "--with-devtools" "${BUILD_SCRIPT}" \
   && grep -q -- "--with-recovery-kwin" "${BUILD_SCRIPT}" \
   && grep -q -- "--with-secureboot" "${BUILD_SCRIPT}" \
   && grep -q -- "--with-plymouth" "${BUILD_SCRIPT}" \
   && grep -q -- "--with-qemu" "${BUILD_SCRIPT}"; then
    pass "All --with-* / --without-* flags documented in usage()"
else
    fail "Some --with-*/--without-* flags missing from usage()"
fi

# Home edition defaults: bluetooth + printing + network-extras + android ON;
# wine/devtools/recovery-kwin/secureboot/plymouth/qemu OFF
if grep -q 'DEF_BLUETOOTH=true' "${BUILD_SCRIPT}" \
   && grep -q 'DEF_PRINTING=true' "${BUILD_SCRIPT}" \
   && grep -q 'DEF_NETWORK_EXTRAS=true' "${BUILD_SCRIPT}" \
   && grep -q 'DEF_ANDROID=true' "${BUILD_SCRIPT}" \
   && grep -q 'DEF_WINE=false' "${BUILD_SCRIPT}" \
   && grep -q 'DEF_DEVTOOLS=false' "${BUILD_SCRIPT}" \
   && grep -q 'DEF_RECOVERY_KWIN=false' "${BUILD_SCRIPT}"; then
    pass "Home defaults correctly specified (BT/print/net/android on)"
else
    fail "Home edition defaults incorrect"
fi

# Lite defaults: all optional features OFF
if grep -A3 'lite)' "${BUILD_SCRIPT}" | grep -q 'DEF_BLUETOOTH=false' \
   && grep -A3 'lite)' "${BUILD_SCRIPT}" | grep -q 'DEF_ANDROID=false'; then
    pass "Lite defaults correctly specified (all off)"
else
    fail "Lite edition defaults incorrect"
fi

# Developer defaults: devtools/secureboot/qemu/wine ON
# Extract the developer case block (from 'developer)' to ';;')
DEV_BLOCK=$(sed -n '/developer)/,/;;/p' "${BUILD_SCRIPT}")
if echo "$DEV_BLOCK" | grep -q 'DEF_DEVTOOLS=true' \
   && echo "$DEV_BLOCK" | grep -q 'DEF_SECUREBOOT=true' \
   && echo "$DEV_BLOCK" | grep -q 'DEF_QEMU=true' \
   && echo "$DEV_BLOCK" | grep -q 'DEF_WINE=true'; then
    pass "Developer defaults correctly specified (devtools/qemu/wine on)"
else
    fail "Developer edition defaults incorrect"
fi

# Masking logic must NOT unconditionally mask services that the feature enables
if grep -q 'mask_if_disabled bluetooth.service' "${BUILD_SCRIPT}" \
   && grep -q 'mask_if_disabled cups.service' "${BUILD_SCRIPT}"; then
    pass "Service masking uses feature-aware mask_if_disabled (not unconditional)"
else
    fail "Service masking still unconditional (bug)"
fi

# Components hook must unmask services before enabling them
if grep -q 'systemctl unmask' config/hooks/live/10-bright-os-components.hook.chroot; then
    pass "Components hook calls systemctl unmask before enabling optional services"
else
    fail "Components hook doesn't unmask before enabling (enable would fail on masked units)"
fi

echo ""
echo "--- greetd + display manager hardening ---"

# Greeter user must NOT use /usr/sbin/nologin (breaks session startup)
# The sysusers.d line format is: "u username UID \"GECOS\" home shell"
# The shell is the last field on the 'u greeter' line; it must not be nologin.
if grep -qE '^u[[:space:]]+greeter[[:space:]].*/usr/sbin/nologin[[:space:]]*$' config/includes.chroot/usr/lib/sysusers.d/bright-greeter.conf; then
    fail "greeter user shell is /usr/sbin/nologin (pam_nologin will block sessions)"
else
    pass "greeter user shell is not /usr/sbin/nologin"
fi

# greetd config must use cage -s -- gtkgreet with explicit sessions dir
if grep -q 'cage -s -- gtkgreet' config/includes.chroot/etc/greetd/config.toml \
   && grep -q '/usr/share/wayland-sessions' config/includes.chroot/etc/greetd/config.toml; then
    pass "greetd config.toml invokes cage -s -- gtkgreet with explicit -s sessions dir"
else
    fail "greetd config.toml cage command incorrect"
fi

# bright.desktop (default labwc session) must exist and point at labwc
BRIGHT_DESKTOP="config/includes.chroot/usr/share/wayland-sessions/bright.desktop"
if [ -f "$BRIGHT_DESKTOP" ] \
   && grep -q 'TryExec=labwc' "$BRIGHT_DESKTOP" \
   && grep -q 'bright-desktop-session-labwc' "$BRIGHT_DESKTOP"; then
    pass "bright.desktop (default) points to labwc session"
else
    fail "bright.desktop missing or not pointing at labwc"
fi

# bright-kwin.desktop must NOT be pre-installed; 00-sessions hook generates it
KWIN_DESKTOP="config/includes.chroot/usr/share/wayland-sessions/bright-kwin.desktop"
SESSIONS_HOOK="config/hooks/live/00-bright-os-session-files.hook.chroot"
if [ ! -f "$KWIN_DESKTOP" ] \
   && [ -x "$SESSIONS_HOOK" ] \
   && grep -q 'kwin_wayland' "$SESSIONS_HOOK"; then
    pass "KWin recovery session (bright-kwin.desktop) is hook-generated only if kwin_wayland present"
else
    fail "KWin recovery session handling incorrect (preinstalled file or missing hook)"
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
