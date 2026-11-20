#!/bin/bash
# =============================================================================
# Bright OS ISO Build Script
# =============================================================================
# Builds a bootable Bright OS ISO using Debian live-build.
#
# Usage:
#   ./build.sh [OPTIONS] [EDITION]
#
# Editions: home (default), developer, lite
#
# Requirements:
#   - Debian 13 (trixie) amd64 build machine  (Debian 12 bookworm also works)
#   - live-build package installed
#   - Root/sudo NOT required for lb config; lb build uses fakeroot where needed
#     but some live-build versions may require sudo for chroot operations.
#   - Minimum 20 GB free disk space
#   - Minimum 4 GB RAM (8 GB recommended)
# =============================================================================

set -euo pipefail

# Determine script location and project root
# Script is at: <root>/build/scripts/build.sh
# So PROJECT_ROOT is two levels up from the script directory.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
LIVE_BUILD_DIR="${PROJECT_ROOT}/build/live-build"
CONFIG_DIR="${PROJECT_ROOT}/config"
EDITIONS_DIR="${PROJECT_ROOT}/editions"

# Validate that PROJECT_ROOT looks correct
if [ ! -f "${PROJECT_ROOT}/README.md" ] || [ ! -d "${CONFIG_DIR}" ]; then
    echo "[ERROR] PROJECT_ROOT calculation failed."
    echo "  SCRIPT_DIR=${SCRIPT_DIR}"
    echo "  PROJECT_ROOT=${PROJECT_ROOT}"
    echo "  Could not find README.md or config/ at project root."
    echo "  Make sure you are running this script from the repository,"
    echo "  or that the script hasn't been moved."
    exit 1
fi

# Defaults
EDITION="home"
ARCH="amd64"
VERSION="0.1.0-alpha"
SKIP_BUILD=false
CLEAN_ONLY=false
VERBOSE=false
DEBIAN_CODENAME="${BRIGHT_DEBIAN_CODENAME:-trixie}"

# Valid values
VALID_EDITIONS="home developer lite"
VALID_ARCHS="amd64"   # x86-64 only for Alpha 0.1
REQUIRED_DISK_GB=20
REQUIRED_RAM_MB=4096

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
    local ec="${1:-0}"
    cat <<EOF
Bright OS Build Script

Usage: $0 [OPTIONS] [EDITION]

Editions:
  home        Bright OS Home edition (default)
  developer   Bright OS Developer edition
  lite        Bright OS Lite edition

Options:
  -h, --help            Show this help
  -v, --version VER     Set version string (default: ${VERSION})
  -a, --arch ARCH       Set architecture (default: ${ARCH}; only amd64 supported in Alpha)
  -d, --distro CODENAME Debian codename (default: ${DEBIAN_CODENAME})
  --clean               Clean build directory only
  --skip-build          Configure only, do not build
  --verbose             Verbose build output
EOF
    exit $ec
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        home|developer|lite)
            EDITION="$1"
            shift
            ;;
        -h|--help)
            usage
            ;;
        -v|--version)
            if [ $# -lt 2 ]; then
                log_error "--version requires an argument"
                exit 1
            fi
            VERSION="$2"
            shift 2
            ;;
        -a|--arch)
            if [ $# -lt 2 ]; then
                log_error "--arch requires an argument"
                exit 1
            fi
            ARCH="$2"
            shift 2
            ;;
        -d|--distro)
            if [ $# -lt 2 ]; then
                log_error "--distro requires an argument"
                exit 1
            fi
            DEBIAN_CODENAME="$2"
            shift 2
            ;;
        --clean)
            CLEAN_ONLY=true
            shift
            ;;
        --skip-build)
            SKIP_BUILD=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            usage 1
            ;;
    esac
done

# Validate edition
if ! echo " ${VALID_EDITIONS} " | grep -q " ${EDITION} "; then
    log_error "Invalid edition '${EDITION}'. Valid editions: ${VALID_EDITIONS}"
    exit 1
fi

# Validate architecture
if ! echo " ${VALID_ARCHS} " | grep -q " ${ARCH} "; then
    log_error "Invalid architecture '${ARCH}'. Valid architectures for Alpha 0.1: ${VALID_ARCHS}"
    exit 1
fi

# Validate codename (basic sanity)
case "${DEBIAN_CODENAME}" in
    bookworm|trixie|forky) ;;  # Known codenames
    *) log_warn "Debian codename '${DEBIAN_CODENAME}' is not one of: bookworm, trixie, forky" ;;
esac

log_info "========================================"
log_info "  Bright OS Build System"
log_info "  Edition:    ${EDITION}"
log_info "  Version:    ${VERSION}"
log_info "  Arch:       ${ARCH}"
log_info "  Distro:     Debian ${DEBIAN_CODENAME}"
log_info "  Project:    ${PROJECT_ROOT}"
log_info "========================================"

# --- Check prerequisites ---
check_dependencies() {
    log_info "Checking build dependencies..."
    local missing=()
    local deps="lb debootstrap mksquashfs xorriso"
    for dep in $deps; do
        if ! command -v "$dep" &>/dev/null; then
            missing+=("$dep")
        fi
    done

    # Check for bootloader packages (grub, isolinux, mtools)
    # These don't have simple command names but their files need to exist
    local boot_missing=()
    if ! dpkg -l isolinux 2>/dev/null | grep -q '^ii'; then
        boot_missing+=("isolinux")
    fi
    if ! dpkg -l mtools 2>/dev/null | grep -q '^ii'; then
        boot_missing+=("mtools")
    fi
    if ! dpkg -l grub-pc-bin 2>/dev/null | grep -q '^ii'; then
        boot_missing+=("grub-pc-bin")
    fi
    if ! dpkg -l grub-efi-amd64-bin 2>/dev/null | grep -q '^ii'; then
        boot_missing+=("grub-efi-amd64-bin")
    fi

    if [ ${#missing[@]} -gt 0 ] || [ ${#boot_missing[@]} -gt 0 ]; then
        local all_missing=("${missing[@]}" "${boot_missing[@]}")
        log_error "Missing dependencies: ${all_missing[*]}"
        log_info ""
        log_info "Install all dependencies with:"
        log_info "  sudo apt-get install -y live-build debootstrap squashfs-tools xorriso \\"
        log_info "    isolinux syslinux-efi grub-pc-bin grub-efi-amd64-bin mtools dosfstools"
        exit 1
    fi
    log_ok "All required build tools found"
}

check_dependencies

# --- Check required source files exist ---
check_source_files() {
    log_info "Checking source files..."
    local required_files=(
        "${LIVE_BUILD_DIR}/auto/config"
        "${LIVE_BUILD_DIR}/auto/build"
        "${LIVE_BUILD_DIR}/auto/clean"
        "${CONFIG_DIR}/package-lists/base.list.chroot"
        "${CONFIG_DIR}/hooks/live/00-bright-os-branding.hook.chroot"
        "${CONFIG_DIR}/hooks/live/10-bright-os-components.hook.chroot"
        "${CONFIG_DIR}/includes.binary/boot/grub/grub.cfg"
        "${CONFIG_DIR}/includes.chroot/etc/bright-os/edition"
        "${CONFIG_DIR}/includes.chroot/usr/bin/bright-desktop-shell"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/Shell.qml"
        "${CONFIG_DIR}/includes.chroot/usr/share/bright-os/bright-desktop-shell.py"
        "${EDITIONS_DIR}/${EDITION}/packages.list"
    )
    local missing=0
    for f in "${required_files[@]}"; do
        if [ ! -f "$f" ]; then
            log_error "Missing required file: $f"
            missing=$((missing+1))
        fi
    done
    if [ $missing -gt 0 ]; then
        log_error "${missing} required source file(s) missing. Cannot continue."
        exit 1
    fi
    log_ok "All required source files present"
}

check_source_files

# --- Check disk space (use PROJECT_ROOT filesystem) ---
AVAIL_KB=$(df --output=avail "${PROJECT_ROOT}" | tail -1 | tr -d ' ')
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
if [ "$AVAIL_GB" -lt "$REQUIRED_DISK_GB" ]; then
    log_error "Insufficient disk space: ${AVAIL_GB} GB available, ${REQUIRED_DISK_GB} GB required."
    exit 1
fi
log_ok "Disk space: ${AVAIL_GB} GB available (${REQUIRED_DISK_GB} GB required)"

# --- Set up build directory ---
BUILD_DIR="${PROJECT_ROOT}/build/output/${EDITION}"
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# --- Clean if requested ---
if [ "$CLEAN_ONLY" = true ]; then
    log_info "Cleaning build directory: ${BUILD_DIR}"
    if command -v lb &>/dev/null; then
        lb clean --purge 2>/dev/null || true
    fi
    rm -rf config/ local/ .build/ chroot/ binary/
    # Don't delete .iso or .sha256 files (those are outputs); only clean build artifacts
    log_ok "Clean complete (ISO files preserved)"
    exit 0
fi

# --- Copy live-build auto scripts ---
log_info "Setting up live-build configuration..."
mkdir -p auto
# Use shopt to prevent glob from expanding literally if no files
shopt -s nullglob
for f in "${LIVE_BUILD_DIR}/auto/"*; do
    cp "$f" "auto/"
    chmod +x "auto/$(basename "$f")"
done
shopt -u nullglob

# Verify auto scripts were copied
if [ ! -x auto/config ] || [ ! -x auto/build ]; then
    log_error "Failed to copy auto/config or auto/build from ${LIVE_BUILD_DIR}/auto/"
    exit 1
fi

# --- Copy config tree (package lists, hooks, includes) ---
rm -rf config
cp -r "${CONFIG_DIR}" ./config

# --- Copy edition-specific package lists ---
EDITION_PKGS="${EDITIONS_DIR}/${EDITION}/packages.list"
if [ -f "${EDITION_PKGS}" ]; then
    cp "${EDITION_PKGS}" "config/package-lists/edition-packages.list.chroot"
    log_info "Edition package list: ${EDITION_PKGS}"
else
    log_warn "No edition-specific package list found at ${EDITION_PKGS}; using base packages only"
fi

# --- Copy edition-specific hooks if present ---
EDITION_HOOKS_DIR="${EDITIONS_DIR}/${EDITION}/hooks"
if [ -d "${EDITION_HOOKS_DIR}" ]; then
    shopt -s nullglob
    hook_count=0
    for h in "${EDITION_HOOKS_DIR}/"*; do
        cp "$h" config/hooks/live/
        chmod +x "config/hooks/live/$(basename "$h")"
        hook_count=$((hook_count+1))
    done
    shopt -u nullglob
    log_info "Copied ${hook_count} edition-specific hook(s)"
fi

# --- Write edition marker into chroot ---
echo "${EDITION}" > "config/includes.chroot/etc/bright-os/edition"

# --- Lite edition: mask heavy services ---
if [ "${EDITION}" = "lite" ]; then
    mkdir -p config/includes.chroot/etc/systemd/system
    for svc in bluetooth.service cups.service ModemManager.service; do
        ln -sf /dev/null "config/includes.chroot/etc/systemd/system/${svc}" 2>/dev/null || true
    done
    log_info "Lite edition: masking bluetooth, cups, ModemManager"
fi

# --- Export environment for auto/config ---
export BRIGHT_EDITION="$EDITION"
export BRIGHT_ARCH="$ARCH"
export BRIGHT_VERSION="$VERSION"
export BRIGHT_DEBIAN_CODENAME="$DEBIAN_CODENAME"

# Update auto/config to use the selected codename
# The auto/config reads BRIGHT_DEBIAN_CODENAME; we set it above.

# --- Run auto/config ---
log_info "Configuring live-build for Debian ${DEBIAN_CODENAME}..."
set +e
./auto/config
CONFIG_STATUS=$?
set -e
if [ $CONFIG_STATUS -ne 0 ]; then
    log_error "live-build configuration failed (exit code ${CONFIG_STATUS})"
    exit $CONFIG_STATUS
fi
log_ok "live-build configuration complete"

if [ "$SKIP_BUILD" = true ]; then
    log_ok "Configuration complete. Skipping build (--skip-build)."
    log_info "Build directory: ${BUILD_DIR}"
    exit 0
fi


# --- Build ---
log_info "Starting ISO build (this will take 30-90 minutes)..."
BUILD_LOG="build.log"

# Temporarily disable pipefail so PIPESTATUS works correctly with tee
set +o pipefail
if [ "$VERBOSE" = true ]; then
    # Verbose mode: show all build output on screen
    ./auto/build 2>&1 | tee "${BUILD_LOG}"
    BUILD_STATUS=${PIPESTATUS[0]}
else
    # Normal mode: full output saved to build.log; key stages shown on screen
    ./auto/build 2>&1 | tee "${BUILD_LOG}" | grep -E --line-buffered \
        '^P:|^E:|^I:|^W:|BUILD SUCCESS|BUILD FAILED|mksquashfs|genisoimage|xorriso|^\[|=====' \
        || true
    BUILD_STATUS=${PIPESTATUS[0]}
fi
# Restore strict mode
set -euo pipefail


if [ $BUILD_STATUS -ne 0 ]; then
    log_error "Build failed with exit code ${BUILD_STATUS}!"
    log_error "Last 20 lines of build.log:"
    tail -20 "${BUILD_LOG}" >&2 || true
    log_error "See ${BUILD_DIR}/${BUILD_LOG} for full details."
    exit $BUILD_STATUS
fi

# --- Locate and rename ISO ---
# Use an array to safely capture glob results
shopt -s nullglob
ISO_CANDIDATES=(live-image-*.hybrid.iso live-image-*.iso)
shopt -u nullglob

ISO_NAME="bright-os-${VERSION}-${EDITION}-${ARCH}.iso"
ISO_PATH="${BUILD_DIR}/${ISO_NAME}"

if [ ${#ISO_CANDIDATES[@]} -eq 0 ]; then
    log_error "Build completed but no ISO image was found in ${BUILD_DIR}"
    log_error "Contents of build directory:"
    ls -la >&2 || true
    exit 1
fi

if [ ${#ISO_CANDIDATES[@]} -gt 1 ]; then
    log_warn "Multiple ISO candidates found; using first: ${ISO_CANDIDATES[0]}"
fi

GENERATED_ISO="${ISO_CANDIDATES[0]}"

# Don't overwrite an existing ISO of the same name unless it's our own build
if [ -f "${ISO_NAME}" ] && [ "${GENERATED_ISO}" != "${ISO_NAME}" ]; then
    log_error "Output ISO ${ISO_NAME} already exists in build directory."
    log_error "Remove it manually or use a different version string."
    exit 1
fi

mv "${GENERATED_ISO}" "${ISO_NAME}"

# --- Generate checksums (only after successful build and rename) ---
log_info "Generating SHA256 checksum..."
sha256sum "${ISO_NAME}" > "${ISO_NAME}.sha256"

# --- Report ---
ISO_SIZE=$(du -h "${ISO_NAME}" | cut -f1)
SHA256=$(cut -d' ' -f1 "${ISO_NAME}.sha256")

echo ""
log_ok "========================================"
log_ok "  BUILD SUCCESSFUL"
log_ok "  Edition:   ${EDITION}"
log_ok "  ISO:       ${ISO_PATH}"
log_ok "  Size:      ${ISO_SIZE}"
log_ok "  SHA256:    ${SHA256}"
log_ok "  Log:       ${BUILD_DIR}/${BUILD_LOG}"
log_ok "========================================"
echo ""
log_info "To test in QEMU:"
log_info "  ${PROJECT_ROOT}/build/scripts/test-in-qemu.sh ${ISO_PATH}"
echo ""
log_info "To write to USB:"
log_info "  sudo dd if=${ISO_PATH} of=/dev/sdX bs=4M status=progress conv=fsync"
