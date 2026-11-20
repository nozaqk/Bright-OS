#!/bin/bash
# =============================================================================
# Bright OS ISO Build Script
# =============================================================================
# Builds a bootable Bright OS ISO using Debian live-build.
#
# Usage:
#   ./build.sh [edition] [options]
#
# Editions: home (default), developer, lite
#
# Requirements:
#   - Debian 12 (bookworm) build machine
#   - live-build package installed
#   - Root/sudo access for package installation during build
#   - Minimum 15 GB free disk space
#   - Minimum 4 GB RAM (8 GB recommended)
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LIVE_BUILD_DIR="${PROJECT_ROOT}/build/live-build"
CONFIG_DIR="${PROJECT_ROOT}/config"

# Defaults
EDITION="home"
ARCH="amd64"
VERSION="0.1.0-alpha"
SKIP_BUILD=false
CLEAN_ONLY=false
VERBOSE=false

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

usage() {
    cat <<EOF
Bright OS Build Script

Usage: $0 [OPTIONS] [EDITION]

Editions:
  home        Bright OS Home edition (default)
  developer   Bright OS Developer edition
  lite        Bright OS Lite edition

Options:
  -h, --help          Show this help
  -v, --version VER   Set version string (default: ${VERSION})
  -a, --arch ARCH     Set architecture (default: ${ARCH})
  --clean             Clean build directory only
  --skip-build        Configure only, do not build
  --verbose           Verbose output
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        home|developer|lite) EDITION="$1"; shift ;;
        -h|--help) usage ;;
        -v|--version) VERSION="$2"; shift 2 ;;
        -a|--arch) ARCH="$2"; shift 2 ;;
        --clean) CLEAN_ONLY=true; shift ;;
        --skip-build) SKIP_BUILD=true; shift ;;
        --verbose) VERBOSE=true; shift ;;
        *) log_error "Unknown option: $1"; usage ;;
    esac
done

log_info "========================================"
log_info "  Bright OS Build System"
log_info "  Edition:   ${EDITION}"
log_info "  Version:   ${VERSION}"
log_info "  Arch:      ${ARCH}"
log_info "========================================"

# Check prerequisites
check_dependencies() {
    log_info "Checking build dependencies..."
    local missing=()
    local deps="lb debootstrap mksquashfs xorriso"
    for dep in $deps; do
        if ! command -v $dep &>/dev/null; then
            missing+=($dep)
        fi
    done
    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Missing dependencies: ${missing[*]}"
        log_info "Install them with:"
        log_info "  sudo apt-get install live-build debootstrap squashfs-tools xorriso \\"
        log_info "    isolinux syslinux-efi grub-pc-bin grub-efi-amd64-bin mtools dosfstools"
        exit 1
    fi
    log_ok "All dependencies found"
}

check_dependencies

# Check disk space
AVAIL_KB=$(df --output=avail "$SCRIPT_DIR" | tail -1)
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
if [ "$AVAIL_GB" -lt 15 ]; then
    log_warn "Less than 15 GB free disk space available (${AVAIL_GB} GB). Build may fail."
else
    log_ok "Disk space: ${AVAIL_GB} GB available"
fi

# Set up build directory
BUILD_DIR="${PROJECT_ROOT}/build/output/${EDITION}"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Clean if requested
if [ "$CLEAN_ONLY" = true ]; then
    log_info "Cleaning build directory..."
    lb clean --purge 2>/dev/null || true
    rm -rf config/ local/ .build/ chroot/ binary/
    log_ok "Clean complete"
    exit 0
fi

# Copy live-build auto scripts
log_info "Setting up live-build configuration..."
mkdir -p auto
cp "${LIVE_BUILD_DIR}/auto/"* auto/
chmod +x auto/*

# Copy config tree (package lists, hooks, includes)
rm -rf config
cp -r "${CONFIG_DIR}" ./config

# Copy edition-specific package lists
EDITION_DIR="${PROJECT_ROOT}/editions/${EDITION}"
if [ -f "${EDITION_DIR}/packages.list" ]; then
    cp "${EDITION_DIR}/packages.list" "config/package-lists/edition-packages.list.chroot"
fi

# Apply edition-specific hooks
if [ -d "${EDITION_DIR}/hooks" ]; then
    cp "${EDITION_DIR}/hooks/"* config/hooks/live/
fi

# Set edition marker in the chroot (overrides default "home")
echo "${EDITION}" > "config/includes.chroot/etc/bright-os/edition"

# For Lite edition, disable unnecessary services and set lighter defaults
if [ "${EDITION}" = "lite" ]; then
    # Mask heavy services for Lite
    mkdir -p config/includes.chroot/etc/systemd/system
    for svc in bluetooth.service cups.service snapd.service ModemManager.service; do
        ln -sf /dev/null "config/includes.chroot/etc/systemd/system/${svc}" 2>/dev/null || true
    done
fi

# Export environment for auto/config
export BRIGHT_EDITION="$EDITION"
export BRIGHT_ARCH="$ARCH"
export BRIGHT_VERSION="$VERSION"

# Run auto/config
log_info "Configuring live-build..."
./auto/config 2>&1

if [ "$SKIP_BUILD" = true ]; then
    log_ok "Configuration complete. Skipping build (--skip-build)."
    exit 0
fi

# Build
log_info "Starting ISO build (this will take a while)..."
if [ "$VERBOSE" = true ]; then
    ./auto/build 2>&1 | tee build.log
else
    ./auto/build 2>&1 | tee build.log
fi

BUILD_STATUS=$?
if [ $BUILD_STATUS -ne 0 ]; then
    log_error "Build failed! Check build.log for details."
    exit $BUILD_STATUS
fi

# Rename ISO
ISO_NAME="bright-os-${VERSION}-${EDITION}-${ARCH}.iso"
if ls live-image-*.hybrid.iso 2>/dev/null; then
    mv live-image-*.hybrid.iso "$ISO_NAME"
    ISO_PATH="${BUILD_DIR}/${ISO_NAME}"
    
    # Generate checksums
    log_info "Generating checksums..."
    sha256sum "$ISO_NAME" > "${ISO_NAME}.sha256"
    
    # Report
    ISO_SIZE=$(du -h "$ISO_NAME" | cut -f1)
    log_ok "========================================"
    log_ok "  BUILD SUCCESSFUL"
    log_ok "  ISO:  ${ISO_PATH}"
    log_ok "  Size: ${ISO_SIZE}"
    log_ok "  SHA256: $(cat ${ISO_NAME}.sha256)"
    log_ok "========================================"
else
    log_error "Build completed but no ISO was found."
    exit 1
fi
