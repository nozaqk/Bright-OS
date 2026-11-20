#!/bin/bash
# =============================================================================
# Bright OS Build Doctor
# =============================================================================
# Diagnoses whether the host system is ready to build Bright OS ISOs.
# Does NOT modify the system or install packages.
#
# Exit codes:
#   0 = All critical checks pass (system is ready)
#   1 = One or more critical failures (build will not work)
#   2 = Warnings present but no failures (build may work with caveats)
# =============================================================================

set -u

# Determine project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

PASS=0
WARN=0
FAIL=0
CRITICAL_FAILURES=0

pass()    { echo -e "  ${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
warn()    { echo -e "  ${YELLOW}[WARN]${NC} $*"; WARN=$((WARN+1)); }
fail()    { echo -e "  ${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); CRITICAL_FAILURES=$((CRITICAL_FAILURES+1)); }
header()  { echo -e "\n${BOLD}${BLUE}── $* ──${NC}"; }
info()    { echo -e "  ${BLUE}[INFO]${NC} $*"; }

# ---- Dependency lists ----
# Essential tools that MUST be present
REQUIRED_TOOLS="lb debootstrap mksquashfs xorriso"
# Bootloader packages needed for BIOS+UEFI dual-boot ISO creation
REQUIRED_BOOT_PKGS="isolinux syslinux-common mtools dosfstools"
# GRUB packages for generating boot images
REQUIRED_GRUB_PKGS="grub-pc-bin grub-efi-amd64-bin"
# Optional but recommended
RECOMMENDED_PKGS="shim-signed grub-efi-amd64-signed ovmf qemu-system-x86 qemu-utils genisoimage file"
# Validation tools
VALIDATION_TOOLS="sha256sum isoinfo"

# Minimum requirements
MIN_RAM_MB=3072          # 3 GB absolute minimum; warn below 4 GB
REC_RAM_MB=4096          # 4 GB recommended
MIN_DISK_GB=18           # Absolute minimum for one edition
REC_DISK_GB=25           # Recommended for one edition
MIN_CPUS=2               # 2 cores minimum usable

echo "============================================================"
echo "  Bright OS Build Doctor"
echo "  Project: ${PROJECT_ROOT}"
echo "============================================================"

# ============================================================
header "1. Operating System"
# ============================================================

if [ ! -f /etc/os-release ]; then
    fail "Cannot determine operating system (/etc/os-release missing)"
else
    . /etc/os-release
    OS_ID="${ID:-unknown}"
    OS_VERSION_ID="${VERSION_ID:-unknown}"
    OS_VERSION_CODENAME="${VERSION_CODENAME:-unknown}"
    OS_PRETTY="${PRETTY_NAME:-unknown}"

    echo "  Detected: ${OS_PRETTY}"

    if [ "$OS_ID" = "debian" ]; then
        pass "Operating system is Debian"

        case "$OS_VERSION_CODENAME" in
            trixie)
                pass "Debian 13 Trixie (recommended for Bright OS builds)"
                ;;
            bookworm)
                warn "Debian 12 Bookworm detected. You CAN build Trixie ISOs from Bookworm"
                info "  (live-build will bootstrap a Trixie chroot), but Trixie native is recommended."
                ;;
            forky)
                warn "Debian forky/sid detected. Build may work but is untested."
                ;;
            *)
                if [ "$OS_VERSION_ID" = "12" ] || [ "$OS_VERSION_ID" = "13" ]; then
                    pass "Debian version ${OS_VERSION_ID} (supported)"
                else
                    warn "Debian version ${OS_VERSION_ID} (${OS_VERSION_CODENAME}) — may work but untested"
                fi
                ;;
        esac
    elif [ "$OS_ID" = "ubuntu" ]; then
        warn "Ubuntu detected. Building may work but is not officially supported."
        info "  Debian 13 Trixie is the recommended build host."
    else
        fail "Unsupported operating system: ${OS_ID}. Bright OS builds require Debian."
        info "  Install Debian 12 Bookworm or Debian 13 Trixie in a VM or on hardware."
    fi
fi

# ============================================================
header "2. CPU Architecture"
# ============================================================

ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
echo "  Architecture: ${ARCH}"
CPU_CORES=$(nproc 2>/dev/null || echo 1)
echo "  CPU cores: ${CPU_CORES}"

if [ "$ARCH" = "amd64" ] || [ "$ARCH" = "x86_64" ]; then
    pass "amd64 architecture supported (Bright OS targets x86_64)"
else
    fail "Unsupported architecture: ${ARCH}. Bright OS currently supports only amd64."
fi

if [ "$CPU_CORES" -ge 4 ]; then
    pass "Sufficient CPU cores (${CPU_CORES}); build should be reasonably fast"
elif [ "$CPU_CORES" -ge "$MIN_CPUS" ]; then
    warn "${CPU_CORES} CPU cores available (minimum ${MIN_CPUS}); build will be slow"
else
    fail "Only ${CPU_CORES} CPU core detected; minimum ${MIN_CPUS} recommended"
fi

# ============================================================
header "3. Memory (RAM)"
# ============================================================

if [ -f /proc/meminfo ]; then
    TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
    TOTAL_RAM_MB=$((TOTAL_RAM_KB / 1024))
    TOTAL_RAM_GB=$((TOTAL_RAM_MB / 1024))
    AVAIL_RAM_KB=$(grep MemAvailable /proc/meminfo 2>/dev/null | awk '{print $2}')
    AVAIL_RAM_MB=$((AVAIL_RAM_KB / 1024))
    echo "  Total RAM: ${TOTAL_RAM_MB} MB (${TOTAL_RAM_GB} GB)"
    echo "  Available: ${AVAIL_RAM_MB} MB"

    if [ "$TOTAL_RAM_MB" -ge 8192 ]; then
        pass "RAM is 8 GB or more (excellent for building)"
    elif [ "$TOTAL_RAM_MB" -ge "$REC_RAM_MB" ]; then
        pass "RAM is 4+ GB (meets recommended requirement)"
    elif [ "$TOTAL_RAM_MB" -ge "$MIN_RAM_MB" ]; then
        warn "RAM is ${TOTAL_RAM_MB} MB (below recommended 4 GB; build may OOM)"
        info "  Close other applications or add swap space before building."
    else
        fail "Insufficient RAM: ${TOTAL_RAM_MB} MB (minimum ${MIN_RAM_MB} MB required)"
        info "  Building with less than 3 GB RAM will likely fail with OOM kills."
    fi
else
    warn "Cannot determine RAM (/proc/meminfo not available)"
fi

# Check for swap
if command -v free &>/dev/null; then
    SWAP_MB=$(free -m | awk '/^Swap:/ {print $2}')
    if [ "$SWAP_MB" -gt 0 ]; then
        pass "Swap space available: ${SWAP_MB} MB"
    else
        warn "No swap space detected. With <8 GB RAM, add at least 4 GB swap."
    fi
fi

# ============================================================
header "4. Disk Space"
# ============================================================

AVAIL_KB=$(df --output=avail "${PROJECT_ROOT}" 2>/dev/null | tail -1 | tr -d ' ')
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
TOTAL_DISK_KB=$(df --output=size "${PROJECT_ROOT}" 2>/dev/null | tail -1 | tr -d ' ')
TOTAL_DISK_GB=$((TOTAL_DISK_KB / 1024 / 1024))
echo "  Filesystem: ${PROJECT_ROOT}"
echo "  Total disk: ${TOTAL_DISK_GB} GB"
echo "  Available:  ${AVAIL_GB} GB"

# Check existing build output usage
if [ -d "${PROJECT_ROOT}/build/output" ]; then
    BUILD_USAGE_MB=$(du -sm "${PROJECT_ROOT}/build/output" 2>/dev/null | cut -f1 || echo 0)
    BUILD_USAGE_GB=$((BUILD_USAGE_MB / 1024))
    if [ "$BUILD_USAGE_MB" -gt 100 ]; then
        info "  Existing build output: ${BUILD_USAGE_MB} MB (${BUILD_USAGE_GB} GB)"
    fi
fi

if [ "$AVAIL_GB" -ge "$REC_DISK_GB" ]; then
    pass "Disk space sufficient (${AVAIL_GB} GB available, ${REC_DISK_GB} GB recommended)"
elif [ "$AVAIL_GB" -ge "$MIN_DISK_GB" ]; then
    warn "Disk space is ${AVAIL_GB} GB (minimum ${MIN_DISK_GB} GB, recommended ${REC_DISK_GB} GB)"
    info "  Build one edition at a time and use './build/scripts/build.sh --clean <edition>' between builds."
else
    fail "Insufficient disk space: ${AVAIL_GB} GB available (minimum ${MIN_DISK_GB} GB required)"
    info "  Free up space by cleaning old builds: ./build/scripts/build.sh --clean home"
fi

# Check for temp filesystem space (used during package extraction)
TMP_AVAIL_KB=$(df --output=avail /tmp 2>/dev/null | tail -1 | tr -d ' ')
TMP_AVAIL_GB=$((TMP_AVAIL_KB / 1024 / 1024))
echo "  /tmp available: ${TMP_AVAIL_GB} GB"
if [ "$TMP_AVAIL_GB" -lt 5 ]; then
    warn "/tmp has only ${TMP_AVAIL_GB} GB available (5+ GB recommended)"
    info "  live-build uses TMPDIR for package extraction; set TMPDIR to a larger location if needed."
fi

# ============================================================
header "5. Privileges"
# ============================================================

if [ "$(id -u)" -eq 0 ]; then
    warn "Running as root. live-build should NOT be run as root directly — use sudo."
    info "  The build script uses sudo internally for privileged operations."
elif command -v sudo &>/dev/null; then
    if sudo -n true 2>/dev/null; then
        pass "sudo available (passwordless)"
    else
        pass "sudo available (you will be prompted for password)"
    fi
else
    fail "sudo is not available and you are not root."
    info "  Install sudo or run as root (not recommended)."
fi

# ============================================================
header "6. Network Connectivity"
# ============================================================

# Check basic internet
if ping -c 1 -W 3 8.8.8.8 >/dev/null 2>&1; then
    pass "Basic internet connectivity (ping to 8.8.8.8)"
else
    # Try curl as fallback (ping may be blocked)
    if curl -s --connect-timeout 5 https://github.com >/dev/null 2>&1; then
        pass "Internet connectivity (HTTPS reachable, ping may be blocked)"
    else
        fail "No internet connectivity detected"
        info "  Building requires downloading ~3 GB of packages from Debian mirrors."
    fi
fi

# Check DNS resolution
if host deb.debian.org >/dev/null 2>&1 || nslookup deb.debian.org >/dev/null 2>&1 || getent hosts deb.debian.org >/dev/null 2>&1; then
    pass "DNS resolution works (deb.debian.org resolves)"
else
    fail "DNS resolution failed for deb.debian.org"
fi

# Check Debian mirror HTTP access
echo ""
info "Checking Debian mirror access (this may take a few seconds)..."
MIRROR_OK=false
if curl -sI --connect-timeout 10 -L "http://deb.debian.org/debian/dists/trixie/Release" 2>&1 | head -1 | grep -qE "HTTP/.* 200|HTTP/.*30"; then
    pass "Debian mirror (deb.debian.org) is reachable"
    MIRROR_OK=true
else
    fail "Cannot reach Debian mirror (http://deb.debian.org/debian/dists/trixie/Release)"
    info "  Check your network connection, proxy settings, and firewall rules."
fi

if curl -sI --connect-timeout 10 -L "http://security.debian.org/debian-security/dists/trixie-security/Release" 2>&1 | head -1 | grep -qE "HTTP/.* 200|HTTP/.*30"; then
    pass "Debian security mirror (security.debian.org) is reachable"
else
    fail "Cannot reach Debian security mirror"
fi

# ============================================================
header "7. Required Build Tools"
# ============================================================

MISSING_TOOLS=""
for cmd in $REQUIRED_TOOLS; do
    if command -v "$cmd" >/dev/null 2>&1; then
        version="$($cmd --version 2>&1 | head -1 || echo 'version unknown')"
        pass "$cmd found: $version"
    else
        fail "$cmd not found"
        MISSING_TOOLS="$MISSING_TOOLS $cmd"
    fi
done

echo ""
info "Bootloader packages:"
MISSING_BOOT=""
for pkg in $REQUIRED_BOOT_PKGS; do
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
        pass "$pkg installed"
    else
        fail "$pkg not installed"
        MISSING_BOOT="$MISSING_BOOT $pkg"
    fi
done

echo ""
info "GRUB packages:"
MISSING_GRUB=""
for pkg in $REQUIRED_GRUB_PKGS; do
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
        pass "$pkg installed"
    else
        fail "$pkg not installed"
        MISSING_GRUB="$MISSING_GRUB $pkg"
    fi
done

echo ""
info "Validation tools:"
for cmd in $VALIDATION_TOOLS; do
    if command -v "$cmd" >/dev/null 2>&1; then
        pass "$cmd found"
    else
        fail "$cmd not found"
        MISSING_TOOLS="$MISSING_TOOLS $cmd"
    fi
done

echo ""
info "Recommended packages (not required but improve the build):"
for pkg in $RECOMMENDED_PKGS; do
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed" || command -v "$pkg" >/dev/null 2>&1; then
        pass "$pkg available"
    else
        warn "$pkg not installed"
    fi
done

# ============================================================
header "8. Project Configuration Files"
# ============================================================

REQUIRED_FILES=(
    "build/live-build/auto/config"
    "build/live-build/auto/build"
    "build/live-build/auto/clean"
    "config/package-lists/core.list.chroot"
    "config/package-lists/desktop.list.chroot"
    "config/package-lists/desktop-lite.list.chroot"
    "config/hooks/live/00-bright-os-branding.hook.chroot"
    "config/hooks/live/10-bright-os-components.hook.chroot"
    "config/hooks/live/20-installer-setup.hook.chroot"
    "config/includes.binary/boot/grub/grub.cfg"
    "config/includes.chroot/etc/bright-os/edition"
    "config/includes.chroot/usr/bin/bright-desktop-shell"
    "config/includes.chroot/usr/share/bright-os/Shell.qml"
    "config/includes.chroot/usr/share/bright-os/bright-desktop-shell.py"
    "config/includes.chroot/usr/share/bright-os/design/DesignTokens.js"
    "config/includes.chroot/usr/share/bright-os/profiles/EditionProfiles.js"
    "config/includes.chroot/usr/share/bright-os/installer/settings.conf"
    "config/includes.chroot/usr/share/bright-os/installer/modules/bootloader.conf"
    "config/includes.chroot/usr/share/bright-os/installer/modules/displaymanager.conf"
    "installer/calamares/settings.conf"
    "installer/calamares/modules/displaymanager.conf"
    "installer/calamares/modules/bootloader.conf"
    "installer/calamares/modules/fstab.conf"
    "installer/calamares/modules/packages.conf"
    "editions/lite/packages.list"
    "editions/home/packages.list"
    "editions/developer/packages.list"
)

MISSING_FILES=0
for f in "${REQUIRED_FILES[@]}"; do
    if [ -f "${PROJECT_ROOT}/${f}" ]; then
        pass "$f"
    else
        fail "Missing: $f"
        MISSING_FILES=$((MISSING_FILES+1))
    fi
done

if [ "$MISSING_FILES" -gt 0 ]; then
    info "  ${MISSING_FILES} required project file(s) missing. The repository may be incomplete."
fi

# ============================================================
header "9. Build Output Directory"
# ============================================================

BUILD_OUTPUT="${PROJECT_ROOT}/build/output"
mkdir -p "$BUILD_OUTPUT" 2>/dev/null || true
BUILD_OUT_KB=$(df --output=avail "$BUILD_OUTPUT" 2>/dev/null | tail -1 | tr -d ' ')
BUILD_OUT_GB=$((BUILD_OUT_KB / 1024 / 1024))
echo "  Build output: ${BUILD_OUTPUT}"
echo "  Space available: ${BUILD_OUT_GB} GB"

# Check for existing ISOs (don't overwrite)
EXISTING_ISO=""
shopt -s nullglob
for iso in "${BUILD_OUTPUT}"/lite/bright-os-*-lite-amd64.iso; do
    if [ -f "$iso" ]; then
        EXISTING_ISO="$iso"
    fi
done
shopt -u nullglob
if [ -n "$EXISTING_ISO" ]; then
    ISO_SIZE=$(du -h "$EXISTING_ISO" | cut -f1)
    warn "Existing Lite ISO found: ${EXISTING_ISO} (${ISO_SIZE})"
    info "  build-first-iso.sh will not overwrite it without confirmation."
else
    pass "No existing Lite ISO (clean start)"
fi

# Check for stale build directories
for ed in lite home developer; do
    if [ -d "${BUILD_OUTPUT}/${ed}/chroot" ]; then
        warn "Stale chroot directory found in build/output/${ed}/"
        info "  Run './build/scripts/build.sh --clean ${ed}' to clean before building."
    fi
done

# ============================================================
header "10. KVM Acceleration (for QEMU testing)"
# ============================================================

if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    pass "/dev/kvm accessible (hardware-accelerated QEMU available)"
else
    warn "/dev/kvm not available (QEMU will use slow TCG software emulation)"
    info "  Boot testing is still possible but much slower."
fi

# ============================================================
# Summary
# ============================================================

echo ""
echo "============================================================"
echo "  Build Doctor Summary"
echo "============================================================"
echo -e "  ${GREEN}Passed:${NC}    ${PASS}"
echo -e "  ${YELLOW}Warnings:${NC}  ${WARN}"
echo -e "  ${RED}Failed:${NC}    ${FAIL}"
echo ""

# Determine overall status
if [ "$CRITICAL_FAILURES" -gt 0 ]; then
    echo -e "  ${RED}${BOLD}STATUS: NOT READY${NC}"
    echo ""
    echo "  The following issues must be resolved before building:"
    echo ""

    if [ -n "$MISSING_TOOLS" ] || [ -n "$MISSING_BOOT" ] || [ -n "$MISSING_GRUB" ]; then
        echo "  Install missing packages:"
        echo "    sudo apt-get update"
        echo -n "    sudo apt-get install -y"
        for t in $MISSING_TOOLS; do
            case "$t" in
                lb) echo -n " live-build" ;;
                mksquashfs) echo -n " squashfs-tools" ;;
                isoinfo) echo -n " genisoimage" ;;
                *) echo -n " $t" ;;
            esac
        done
        for p in $MISSING_BOOT $MISSING_GRUB; do
            echo -n " $p"
        done
        echo ""
        echo ""
    fi

    if [ "$MIRROR_OK" != "true" ]; then
        echo "  - Check network connectivity to Debian mirrors (deb.debian.org)."
        echo "    If behind a proxy, set http_proxy/https_proxy environment variables."
        echo ""
    fi

    if [ "$MISSING_FILES" -gt 0 ]; then
        echo "  - Ensure you have cloned the complete Bright OS repository."
        echo ""
    fi

    exit 1

elif [ "$WARN" -gt 0 ]; then
    echo -e "  ${YELLOW}${BOLD}STATUS: READY WITH WARNINGS${NC}"
    echo ""
    echo "  The build should work, but note the warnings above."
    echo "  To build the first Lite ISO:"
    echo ""
    echo "    ./build/scripts/build-first-iso.sh"
    echo ""
    exit 2
else
    echo -e "  ${GREEN}${BOLD}STATUS: READY${NC}"
    echo ""
    echo "  Your system is ready to build Bright OS!"
    echo "  To build the first Lite ISO:"
    echo ""
    echo "    ./build/scripts/build-first-iso.sh"
    echo ""
    exit 0
fi
