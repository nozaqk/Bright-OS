#!/bin/bash
# =============================================================================
# Bright OS Build Environment Setup
# =============================================================================
# Checks that the system can build Bright OS and installs missing dependencies.
#
# Requirements:
#   - Debian 12 (Bookworm) or later; Debian 13 (Trixie) recommended
#   - x86_64 / amd64 architecture
#   - At least 20 GB free disk space
#   - At least 4 GB RAM (8 GB recommended)
#   - Root/sudo access for apt-get
#
# Usage:
#   ./build/scripts/setup-build-env.sh          # Check and install dependencies
#   ./build/scripts/setup-build-env.sh --check  # Check only, don't install
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

CHECK_ONLY=false
if [ "${1:-}" = "--check" ] || [ "${1:-}" = "-c" ]; then
    CHECK_ONLY=true
fi

echo "========================================"
echo "  Bright OS Build Environment Setup"
echo "========================================"
echo ""

# --- Check operating system ---
echo "--- Operating System ---"
if [ ! -f /etc/os-release ]; then
    log_error "Cannot determine operating system (/etc/os-release not found)"
    log_error "Bright OS builds require Debian 12 (Bookworm) or later."
    exit 1
fi

. /etc/os-release
OS_ID="${ID:-unknown}"
OS_VERSION="${VERSION_ID:-unknown}"
OS_NAME="${PRETTY_NAME:-unknown}"

echo "Detected: $OS_NAME"

if [ "$OS_ID" != "debian" ]; then
    log_warn "This system does not appear to be Debian (detected: $OS_ID)."
    log_warn "Building on non-Debian systems may work with debootstrap/chroot but is untested."
    log_warn "A Debian 13 Trixie system or VM is strongly recommended."
    echo ""
    # Don't exit, but warn
else
    log_ok "Debian detected"
fi

# Check architecture
echo ""
echo "--- Architecture ---"
ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
echo "Architecture: $ARCH"
if [ "$ARCH" != "amd64" ] && [ "$ARCH" != "x86_64" ]; then
    log_error "Bright OS currently supports only amd64/x86_64. Detected: $ARCH"
    exit 1
fi
log_ok "amd64 architecture supported"

# Check RAM
echo ""
echo "--- Memory ---"
TOTAL_RAM_KB=$(grep MemTotal /proc/meminfo | awk '{print $2}')
TOTAL_RAM_GB=$((TOTAL_RAM_KB / 1024 / 1024))
echo "Total RAM: ${TOTAL_RAM_GB} GB"
if [ "$TOTAL_RAM_GB" -lt 4 ]; then
    log_error "Insufficient RAM: ${TOTAL_RAM_GB} GB detected, need at least 4 GB."
    log_error "Building with less RAM may result in OOM kills during package installation."
    exit 1
elif [ "$TOTAL_RAM_GB" -lt 8 ]; then
    log_warn "RAM is ${TOTAL_RAM_GB} GB; 8 GB or more is recommended for reliable builds."
else
    log_ok "RAM sufficient (${TOTAL_RAM_GB} GB)"
fi

# Check disk space
echo ""
echo "--- Disk Space ---"
AVAIL_KB=$(df --output=avail "$PROJECT_ROOT" | tail -1 | tr -d ' ')
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
echo "Available in project directory: ${AVAIL_GB} GB"
if [ "$AVAIL_GB" -lt 20 ]; then
    log_error "Insufficient disk space: ${AVAIL_GB} GB available, 20 GB required."
    log_error "Free up space or choose a different build location."
    exit 1
elif [ "$AVAIL_GB" -lt 30 ]; then
    log_warn "Disk space is ${AVAIL_GB} GB; 30+ GB is recommended for building multiple editions."
else
    log_ok "Disk space sufficient (${AVAIL_GB} GB available)"
fi

# Check sudo/root for installing packages
echo ""
echo "--- Privileges ---"
if [ "$(id -u)" -eq 0 ]; then
    log_ok "Running as root"
    SUDO=""
elif command -v sudo &>/dev/null; then
    # Check if sudo works without password or prompt
    if sudo -n true 2>/dev/null; then
        log_ok "sudo available (passwordless)"
        SUDO="sudo"
    else
        log_info "sudo available (you may be prompted for password)"
        SUDO="sudo"
    fi
else
    log_error "sudo is not available and you are not root. Cannot install packages."
    log_error "Run as root or install sudo."
    exit 1
fi

# --- Check required build tools ---
echo ""
echo "--- Build Tools ---"
MISSING=()

# Essential CLI tools
for cmd in lb debootstrap mksquashfs xorriso; do
    if command -v "$cmd" &>/dev/null; then
        log_ok "$cmd found: $(command -v "$cmd")"
    else
        log_warn "$cmd not found"
        MISSING+=("$cmd")
    fi
done

# Map command names to package names
declare -A CMD_PKG=(
    [lb]=live-build
    [debootstrap]=debootstrap
    [mksquashfs]=squashfs-tools
    [xorriso]=xorriso
)

# Check dpkg-installed bootloader packages
echo ""
echo "--- Bootloader and Firmware Packages ---"
BOOT_PKGS="isolinux syslinux-common syslinux-efi mtools dosfstools grub-pc-bin grub-efi-amd64-bin"
# shim-signed and grub-efi-amd64-signed are recommended for Secure Boot but not strictly required
RECOMMENDED_PKGS="shim-signed grub-efi-amd64-signed"

for pkg in $BOOT_PKGS; do
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
        log_ok "$pkg installed"
    else
        log_warn "$pkg not installed"
        MISSING+=("$pkg")
    fi
done

for pkg in $RECOMMENDED_PKGS; do
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
        log_ok "$pkg installed (recommended)"
    else
        log_warn "$pkg not installed (recommended for Secure Boot support)"
        MISSING+=("$pkg")
    fi
done

# Validation tools
echo ""
echo "--- Validation Tools ---"
VAL_PKGS="genisoimage file"
for pkg in $VAL_PKGS; do
    if dpkg-query -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "install ok installed"; then
        log_ok "$pkg installed"
    else
        log_warn "$pkg not installed (needed for ISO validation)"
        MISSING+=("$pkg")
    fi
done

for cmd in sha256sum dd; do
    if command -v "$cmd" &>/dev/null; then
        log_ok "$cmd found"
    else
        log_warn "$cmd not found"
    fi
done

# Install missing packages
if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    echo "--- Installing Missing Packages ---"
    # Map command names to package names
    PKGS_TO_INSTALL=()
    for m in "${MISSING[@]}"; do
        if [ -n "${CMD_PKG[$m]:-}" ]; then
            PKGS_TO_INSTALL+=("${CMD_PKG[$m]}")
        else
            PKGS_TO_INSTALL+=("$m")
        fi
    done
    # Deduplicate
    PKGS_TO_INSTALL=($(printf "%s\n" "${PKGS_TO_INSTALL[@]}" | sort -u))

    if [ "$CHECK_ONLY" = true ]; then
        log_warn "Check-only mode: would install: ${PKGS_TO_INSTALL[*]}"
        log_info "Run without --check to install missing packages."
        echo ""
        echo "  $SUDO apt-get update"
        echo "  $SUDO apt-get install -y ${PKGS_TO_INSTALL[*]}"
    else
        log_info "Installing: ${PKGS_TO_INSTALL[*]}"
        $SUDO apt-get update -qq
        $SUDO apt-get install -y --no-install-recommends "${PKGS_TO_INSTALL[@]}"
        log_ok "Package installation complete"
    fi
else
    echo ""
    log_ok "All required build tools are already installed"
fi

# Check live-build version
echo ""
echo "--- Live Build Version ---"
if command -v lb &>/dev/null; then
    LB_VERSION=$(lb --version 2>&1 | head -1 || echo "unknown")
    echo "live-build: $LB_VERSION"
    log_ok "live-build available"
fi

# Final summary
echo ""
echo "========================================"
if [ ${#MISSING[@]} -gt 0 ] && [ "$CHECK_ONLY" = true ]; then
    log_warn "Build environment has missing dependencies. Install them before building."
    echo "========================================"
    exit 1
elif [ ${#MISSING[@]} -gt 0 ]; then
    log_ok "Dependencies installed. You may need to open a new shell for PATH changes."
    echo "========================================"
else
    log_ok "Build environment is ready."
    echo "========================================"
fi
echo ""
echo "To build an edition:"
echo "  ./build/scripts/build.sh home"
echo "  ./build/scripts/build.sh developer"
echo "  ./build/scripts/build.sh lite"
echo ""
echo "To build all editions:"
echo "  ./build/scripts/build-all.sh"
echo ""
echo "Build output will be in: build/output/<edition>/"
echo ""
