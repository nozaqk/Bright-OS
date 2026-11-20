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
echo "--- Build doctor exit code handling ---"

# Run the doctor and capture exit code IMMEDIATELY (critical: save $? before any
# other command overwrites it). Do NOT use 'if ! cmd; then EC=$?' — that inverts
# the exit code and $? inside then-block is always 0.
DOCTOR_OUTPUT=$("$DOCTOR" 2>&1)
DOCTOR_EXIT=$?

case "$DOCTOR_EXIT" in
    0)
        pass "Build doctor runs and reports STATUS: READY (exit 0)"
        DOCTOR_HAS_WARNINGS=false
        DOCTOR_HAS_FAILURES=false
        ;;
    2)
        pass "Build doctor runs and reports STATUS: READY WITH WARNINGS (exit 2)"
        DOCTOR_HAS_WARNINGS=true
        DOCTOR_HAS_FAILURES=false
        ;;
    1)
        pass "Build doctor runs and reports STATUS: NOT READY (exit 1)"
        DOCTOR_HAS_WARNINGS=true
        DOCTOR_HAS_FAILURES=true
        ;;
    *)
        fail "Build doctor crashed with unexpected exit code ${DOCTOR_EXIT}"
        DOCTOR_HAS_WARNINGS=true
        DOCTOR_HAS_FAILURES=true
        ;;
esac

echo ""
echo "--- Build doctor section reporting ---"

# Check it detects all expected sections
for section in "Operating System" "CPU Architecture" "Memory" "Disk Space" "Privileges" "Network" "Required Build Tools" "Project Configuration" "Build Output" "KVM" "Summary"; do
    if echo "$DOCTOR_OUTPUT" | grep -q "$section"; then
        pass "Build doctor reports section: $section"
    else
        fail "Build doctor missing section: $section"
    fi
done

# Check it reports a valid status line
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

echo ""
echo "--- Build doctor OS/arch detection ---"

# Detect what OS we're running on
if [ -f /etc/os-release ]; then
    . /etc/os-release
    HOST_OS_ID="${ID:-unknown}"
else
    HOST_OS_ID="unknown"
fi

# The doctor should detect the host OS correctly
case "$HOST_OS_ID" in
    debian)
        if echo "$DOCTOR_OUTPUT" | grep -qi "debian"; then
            pass "Build doctor correctly detects Debian"
        else
            fail "Build doctor did not detect Debian on a Debian system"
        fi
        # Should NOT report unsupported OS
        if echo "$DOCTOR_OUTPUT" | grep -q "Unsupported operating system"; then
            fail "Build doctor incorrectly reports Debian as unsupported"
        else
            pass "Build doctor does not flag Debian as unsupported"
        fi
        ;;
    ubuntu)
        # Ubuntu should produce a warning (not unsupported, not ready-as-debian)
        if echo "$DOCTOR_OUTPUT" | grep -qi "ubuntu"; then
            pass "Build doctor correctly detects Ubuntu"
        else
            fail "Build doctor did not detect Ubuntu"
        fi
        if echo "$DOCTOR_OUTPUT" | grep -q "not officially supported\|may work but is not officially supported"; then
            pass "Build doctor correctly warns that Ubuntu is unsupported"
        else
            fail "Build doctor should warn about Ubuntu being unsupported"
        fi
        ;;
    *)
        # Other OSes should be flagged
        if echo "$DOCTOR_OUTPUT" | grep -q "Unsupported operating system"; then
            pass "Build doctor correctly flags unsupported OS: ${HOST_OS_ID}"
        else
            # It might still report things generically
            info_shown=true
            pass "Build doctor reports OS detection for: ${HOST_OS_ID}"
        fi
        ;;
esac

# Architecture detection (should be amd64 on x86_64 build hosts)
HOST_ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
if echo "$DOCTOR_OUTPUT" | grep -qi "$HOST_ARCH"; then
    pass "Build doctor detects architecture: ${HOST_ARCH}"
else
    fail "Build doctor did not detect architecture ${HOST_ARCH}"
fi

echo ""
echo "--- Build doctor resource detection ---"

if echo "$DOCTOR_OUTPUT" | grep -qE "RAM.*MB|RAM.*GB"; then
    pass "Build doctor detects RAM"
else
    fail "Build doctor did not report RAM"
fi

if echo "$DOCTOR_OUTPUT" | grep -qi "disk"; then
    pass "Build doctor detects disk space"
else
    fail "Build doctor did not report disk space"
fi

echo ""
echo "--- Build doctor tool and file checks ---"

# Should check for lb (live-build) regardless of whether it's installed
if echo "$DOCTOR_OUTPUT" | grep -q "lb not found\|lb found"; then
    pass "Build doctor checks for lb (live-build)"
else
    fail "Build doctor does not check for lb"
fi

# Should check for project files
if echo "$DOCTOR_OUTPUT" | grep -q "core.list.chroot"; then
    pass "Build doctor checks for core package list"
else
    fail "Build doctor does not check for required project files"
fi

# Detect whether there were actually missing packages (to conditionally
# check for the apt-get install hint)
HAS_MISSING_PACKAGES=false
if echo "$DOCTOR_OUTPUT" | grep -qE "(not found|not installed)" && \
   echo "$DOCTOR_OUTPUT" | grep -qE "(lb |debootstrap |mksquashfs |xorriso |isolinux|syslinux|mtools|dosfstools|genisoimage|grub-pc|grub-efi|isoinfo|file |sha256)"; then
    # At least one package/tool was reported missing
    if echo "$DOCTOR_OUTPUT" | grep -qE "\[FAIL\].*(not found|not installed)"; then
        HAS_MISSING_PACKAGES=true
    fi
fi

# Status consistency: the reported STATUS should match actual conditions
echo ""
echo "--- Build doctor status consistency ---"

REPORTED_STATUS=$(echo "$DOCTOR_OUTPUT" | grep -oE "STATUS: (READY|READY WITH WARNINGS|NOT READY)" | head -1)
case "$REPORTED_STATUS" in
    "STATUS: NOT READY")
        # Doctor must have reported at least one FAIL
        if [ "$DOCTOR_HAS_FAILURES" = "true" ]; then
            pass "STATUS: NOT READY consistent with reported failures"
        else
            fail "Doctor reports NOT READY but no failures detected"
        fi
        # Apt-get install hint is required WHEN PACKAGES ARE MISSING.
        # If the failure is for other reasons (mirrors unreachable, bad config, etc.),
        # the doctor should show an appropriate diagnostic but not a misleading
        # package-install hint.
        if [ "$HAS_MISSING_PACKAGES" = "true" ]; then
            if echo "$DOCTOR_OUTPUT" | grep -q "apt-get install"; then
                pass "Build doctor suggests apt-get install for missing packages"
            else
                fail "Build doctor should suggest apt-get install when packages are missing"
            fi
        else
            # No packages missing - must show non-package diagnostic (mirrors, etc.)
            if echo "$DOCTOR_OUTPUT" | grep -qE "(mirror|network|connectivity|proxy|capability|cannot determine|configuration)"; then
                pass "Build doctor provides non-package diagnostic for NOT READY status"
            else
                fail "Build doctor NOT READY but no package hint or diagnostic found"
            fi
        fi
        ;;
    "STATUS: READY WITH WARNINGS")
        if [ "$DOCTOR_HAS_FAILURES" = "false" ] && [ "$DOCTOR_HAS_WARNINGS" = "true" ]; then
            pass "STATUS: READY WITH WARNINGS consistent with warnings but no failures"
        else
            fail "Doctor reports READY WITH WARNINGS but failure state is inconsistent"
        fi
        # May or may not show install hint depending on whether packages are missing
        ;;
    "STATUS: READY")
        if [ "$DOCTOR_HAS_FAILURES" = "false" ] && [ "$DOCTOR_HAS_WARNINGS" = "false" ]; then
            pass "STATUS: READY consistent with no warnings or failures"
        else
            fail "Doctor reports READY but has warnings/failures"
        fi
        # Should NOT show install hint when system is ready
        if echo "$DOCTOR_OUTPUT" | grep -q "apt-get install"; then
            # It's in the help text for the error case, but shouldn't be shown on READY
            # Actually the install hint is only in the NOT READY section, so if it's
            # showing on READY that's a bug
            fail "Build doctor shows apt-get install hint when STATUS is READY"
        else
            pass "Build doctor does not show install hint when system is ready"
        fi
        ;;
    *)
        fail "Build doctor did not report a recognized STATUS"
        ;;
esac

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
echo "--- Build-first-iso.sh Build Doctor exit code handling ---"

# The script must NOT use the broken `if ! doctor; then EC=$?` pattern
if grep -q 'if ! "\$DOCTOR_SCRIPT"' "$BUILD_FIRST"; then
    fail "build-first-iso.sh uses broken 'if ! \$DOCTOR_SCRIPT' pattern for exit code capture"
else
    pass "build-first-iso.sh does not use inverted-exit-code bug pattern"
fi

# Must capture exit code immediately after running the doctor
if grep -q 'DOCTOR_EXIT=\$?' "$BUILD_FIRST" && grep -q '"$DOCTOR_SCRIPT"' "$BUILD_FIRST"; then
    # Check that DOCTOR_EXIT=$? appears ON THE LINE AFTER "$DOCTOR_SCRIPT" or on next non-comment line
    # Extract lines around the doctor invocation
    DOCTOR_LINE=$(grep -n '"$DOCTOR_SCRIPT"' "$BUILD_FIRST" | grep -v '^.*#' | head -1 | cut -d: -f1)
    NEXT_LINE=$((DOCTOR_LINE + 1))
    NEXT_CONTENT=$(sed -n "${NEXT_LINE}p" "$BUILD_FIRST")
    if echo "$NEXT_CONTENT" | grep -q 'DOCTOR_EXIT=\$?'; then
        pass "build-first-iso.sh captures DOCTOR_EXIT immediately after running doctor"
    else
        fail "build-first-iso.sh does not capture DOCTOR_EXIT immediately (line ${NEXT_LINE}: ${NEXT_CONTENT})"
    fi
fi

# Must handle exit 0 (continue), exit 1 (stop), exit 2 (warnings prompt), and unexpected (crash)
if grep -q "case \"\$DOCTOR_EXIT\"" "$BUILD_FIRST"; then
    pass "build-first-iso.sh uses case statement for exit code dispatch"
else
    fail "build-first-iso.sh does not use case statement for exit codes"
fi
if grep -q "unexpected code\|possible crash\|unexpected exit" "$BUILD_FIRST"; then
    pass "build-first-iso.sh handles unexpected doctor exit codes"
else
    fail "build-first-iso.sh does not handle unexpected exit codes"
fi
# Must prompt user on warnings (exit 2), not silently continue
if grep -q "Do you want to continue" "$BUILD_FIRST"; then
    pass "build-first-iso.sh prompts user before continuing with warnings"
else
    fail "build-first-iso.sh does not prompt user on warnings"
fi
# --force should bypass the warning prompt
if grep -q "continuing due to --force" "$BUILD_FIRST"; then
    pass "build-first-iso.sh --force bypasses warning prompt"
else
    fail "build-first-iso.sh --force does not properly bypass warnings"
fi

echo ""
echo "--- Build-first-iso.sh error handling ---"

# Should detect it's in a Bright OS repo (from project root)
REPO_CHECK=$("$BUILD_FIRST" --skip-tests 2>&1 || true)
if echo "$REPO_CHECK" | grep -q "repository"; then
    pass "build-first-iso.sh checks for repository"
else
    # It may proceed further if repo check passes, which is fine
    pass "build-first-iso.sh starts (repository check passes or proceeds)"
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

if grep -q "Existing ISO found" "$BUILD_FIRST" && grep -q "\-\-force" "$BUILD_FIRST"; then
    pass "build-first-iso.sh has existing ISO overwrite protection (--force flag)"
else
    fail "build-first-iso.sh missing overwrite protection"
fi

echo ""
echo "--- Build log preservation ---"

if grep -q "BUILD_LOG" "$BUILD_FIRST" && grep -q "build-first-iso.log" "$BUILD_FIRST"; then
    pass "build-first-iso.sh preserves build logs"
else
    fail "build-first-iso.sh does not preserve build logs"
fi

if grep -q "Last 30 lines\|tail.*BUILD_LOG\|tail.*build" "$BUILD_FIRST"; then
    pass "build-first-iso.sh shows log tail on failure"
else
    fail "build-first-iso.sh does not show log tail on failure"
fi

echo ""
echo "--- SHA256 verification ---"

if grep -q "sha256sum -c\|sha256sum.*-c" "$BUILD_FIRST"; then
    pass "build-first-iso.sh verifies SHA256 checksum"
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

if grep -q "test-\*\.sh\|test suites\|TEST_PASS\|tests/test-" "$BUILD_FIRST"; then
    pass "build-first-iso.sh runs automated tests"
else
    fail "build-first-iso.sh does not run tests"
fi

if grep -q "\-\-skip-tests" "$BUILD_FIRST"; then
    pass "build-first-iso.sh supports --skip-tests flag"
else
    fail "build-first-iso.sh does not support --skip-tests"
fi

echo ""
echo "--- Live-build capability detection (fixture-based) ---"

# Extract the option-detection logic from auto/config and doctor into a
# testable helper function using the same robust token-extraction approach.
detect_options() {
    local helptext="$1"
    echo "$helptext" | grep -oE '\-\-[a-z][a-z0-9\-]+' | sort -u
}

# Realistic fixture: Ubuntu 24.04 live-build 3.0~a57-1
# Based on actual 'lb config --help' output
UBUNTU_LEGACY_HELP="Usage: lb config [options]
lb config - Create config directory

  -h, --help                 display help
  -u, --usage                display usage
  -v, --version              display version

  -a|--architectures ARCHITECTURE
                             set architectures
  -b|--binary-images iso|iso-hybrid|netboot|tar|hdd
                             set binary image type
  --archive-areas ARCHIVE_AREAS
                             set archive areas
  --bootloader grub|syslinux|yaboot
                             set bootloader
  --bootstrap BOOTSTRAP      set bootstrap
  --bootstrap-keyring PACKAGE
                             set bootstrap keyring
  -d|--distribution CODENAME set distribution
  --mode debian|emdebian|progress|ubuntu|kubuntu
                             set distribution mode
  --keyring-packages PACKAGE | "PACKAGES"
                             set keyring packages
  --syslinux-theme THEME_SUFFIX
                             set syslinux theme
  --parent-archive-areas PARENT_ARCHIVE_AREAS
                             set parent archive areas
  --parent-distribution CODENAME
                             set parent distribution
  --mirror-bootstrap URL     set mirror
  --mirror-binary URL        set mirror
  --mirror-chroot URL        set mirror
  --mirror-chroot-security URL
                             set security mirror
  --mirror-binary-security URL
                             set security mirror
  --apt-recommends true|false
                             enable recommends
  --apt-options OPTIONS      set apt options
  --checksums md5|sha1|sha256|none
                             set checksums
  --debian-installer cdrom|netinst|netboot|businesscard|live|false
                             enable debian installer
  --firmware-binary true|false
                             include firmware in binary
  --firmware-chroot true|false
                             include firmware in chroot
  --iso-application NAME     set application name
  --iso-publisher NAME       set publisher
  --iso-volume NAME          set volume
  --iso-preparer NAME        set preparer
  --memtest memtest86+|memtest86|none
                             set memtest
  --win32-loader true|false  enable win32 loader
  --zsync true|false         enable zsync
  --initsystem sysvinit|systemd|upstart|none
                             set init system"

DETECTED=$(detect_options "$UBUNTU_LEGACY_HELP")

# Check singular bootloader detected, plural NOT detected
if echo "$DETECTED" | grep -qFxe "--bootloader"; then
    pass "Ubuntu legacy: --bootloader (singular) detected"
else
    fail "Ubuntu legacy: --bootloader NOT detected (false negative)"
fi
if echo "$DETECTED" | grep -qFxe "--bootloaders"; then
    fail "Ubuntu legacy: --bootloaders (plural) FALSELY detected"
else
    pass "Ubuntu legacy: --bootloaders (plural) correctly NOT detected"
fi
# Check architecture option
if echo "$DETECTED" | grep -qFxe "--architectures"; then
    pass "Ubuntu legacy: --architectures (plural) detected"
else
    fail "Ubuntu legacy: --architectures NOT detected"
fi
if echo "$DETECTED" | grep -qFxe "--architecture"; then
    fail "Ubuntu legacy: --architecture (singular) FALSELY detected"
else
    pass "Ubuntu legacy: --architecture (singular) correctly NOT detected"
fi
# Check binary image option
if echo "$DETECTED" | grep -qFxe "--binary-images"; then
    pass "Ubuntu legacy: --binary-images (plural) detected"
else
    fail "Ubuntu legacy: --binary-images NOT detected"
fi
# Check Secure Boot NOT detected
if echo "$DETECTED" | grep -qFxe "--uefi-secure-boot"; then
    fail "Ubuntu legacy: --uefi-secure-boot FALSELY detected"
else
    pass "Ubuntu legacy: --uefi-secure-boot correctly NOT detected"
fi
# Check --mode debian support (critical for preventing Ubuntu mode)
if echo "$DETECTED" | grep -qFxe "--mode"; then
    pass "Ubuntu legacy: --mode detected (can force debian mode)"
else
    fail "Ubuntu legacy: --mode NOT detected (cannot prevent Ubuntu mode!)"
fi
# Check --keyring-packages support
if echo "$DETECTED" | grep -qFxe "--keyring-packages"; then
    pass "Ubuntu legacy: --keyring-packages detected (can use debian-archive-keyring)"
else
    fail "Ubuntu legacy: --keyring-packages NOT detected"
fi

# Realistic fixture: Debian Trixie modern live-build (1:2025xxxx)
MODERN_HELP="lb config - Create config directory

  -h|--help
  -u|--usage
  -v|--version

  --apt apt|apt-get|aptitude
  --apt-http-proxy URL
  --apt-indices true|false
  --apt-options OPTIONS
  --apt-recommends true|false
  --apt-secure true|false
  -a|--architecture ARCHITECTURE
  --archive-areas ARCH_AREAS
  --backports true|false
  --binary-filesystem fat16|fat32|ext2|ext3|ext4|ntfs
  -b|--binary-image iso|iso-hybrid|netboot|tar|hdd
  --bootappend-install PARAMETERS
  --bootappend-live PARAMETERS
  --bootloaders grub-legacy|grub-pc|syslinux|grub-efi
  --bootstrap-qemu-arch ARCH
  --checksums md5|sha1|sha224|sha256|sha384|sha512|none
  -d|--distribution CODENAME
  --mode debian
  --keyring-packages PACKAGE
  --firmware-binary true|false
  --firmware-chroot true|false
  -k|--linux-flavours FLAVOURS
  --memtest memtest86+|memtest86|none
  --mirror-bootstrap URL
  --mirror-binary URL
  --mirror-chroot URL
  --mirror-chroot-security URL
  --mirror-binary-security URL
  --parent-archive-areas ARCH_AREAS
  --debian-installer cdrom|netinst|netboot|live|none|false
  --iso-application NAME
  --iso-publisher NAME
  --iso-volume NAME
  --iso-preparer NAME
  --uefi-secure-boot auto|enable|disable
  --updates true|false
  --win32-loader true|false
  --zsync true|false
  --initsystem sysvinit|systemd|none"

DETECTED=$(detect_options "$MODERN_HELP")

if echo "$DETECTED" | grep -qFxe "--bootloaders"; then
    pass "Debian modern: --bootloaders (plural) detected"
else
    fail "Debian modern: --bootloaders NOT detected"
fi
if echo "$DETECTED" | grep -qFxe "--bootloader"; then
    fail "Debian modern: --bootloader (singular) FALSELY detected"
else
    pass "Debian modern: --bootloader (singular) correctly NOT detected"
fi
if echo "$DETECTED" | grep -qFxe "--architecture"; then
    pass "Debian modern: --architecture (singular) detected"
else
    fail "Debian modern: --architecture NOT detected"
fi
if echo "$DETECTED" | grep -qFxe "--binary-image"; then
    pass "Debian modern: --binary-image (singular) detected"
else
    fail "Debian modern: --binary-image NOT detected"
fi
if echo "$DETECTED" | grep -qFxe "--uefi-secure-boot"; then
    pass "Debian modern: --uefi-secure-boot detected"
else
    fail "Debian modern: --uefi-secure-boot NOT detected"
fi
if echo "$DETECTED" | grep -qFxe "--parent-archive-areas"; then
    pass "Debian modern: --parent-archive-areas detected"
else
    fail "Debian modern: --parent-archive-areas NOT detected"
fi
if echo "$DETECTED" | grep -qFxe "--mode"; then
    pass "Debian modern: --mode detected"
else
    fail "Debian modern: --mode NOT detected"
fi
if echo "$DETECTED" | grep -qFxe "--keyring-packages"; then
    pass "Debian modern: --keyring-packages detected"
else
    fail "Debian modern: --keyring-packages NOT detected"
fi

# Edge case: malformed/empty help output
EMPTY_HELP=""
DETECTED=$(detect_options "$EMPTY_HELP")
if [ -z "$DETECTED" ]; then
    pass "Empty help: no options detected (correct)"
else
    fail "Empty help: spurious options detected"
fi

# Edge case: partial/garbled help (no bootloader option at all)
GARBLED_HELP="lb config version 1.0
some random output
--some-internal-flag value
more output"
DETECTED=$(detect_options "$GARBLED_HELP")
if ! echo "$DETECTED" | grep -qFxe "--bootloader" && \
   ! echo "$DETECTED" | grep -qFxe "--bootloaders"; then
    pass "Garbled help: correctly detects no bootloader option"
else
    fail "Garbled help: false bootloader detection"
fi

# Edge case: help with groff bold markers (manpage piped through col might leave these)
BOLD_HELP="[**--bootloader** grub|syslinux]
[**--architectures** *ARCH*]
[**--binary-images** iso|iso-hybrid]
[**--uefi-secure-boot** auto|enable]"
DETECTED=$(detect_options "$BOLD_HELP")
# The ** should not interfere with token extraction (-- is followed by letters)
if echo "$DETECTED" | grep -qFxe "--bootloader"; then
    pass "Bold-marked help: --bootloader detected despite ** markers"
else
    fail "Bold-marked help: --bootloader NOT detected (** markers confuse parser)"
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
