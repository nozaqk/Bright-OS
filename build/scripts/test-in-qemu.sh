#!/bin/bash
# =============================================================================
# Bright OS QEMU Boot Test Script
# Boots the ISO in QEMU for quick testing without writing to USB.
#
# Usage: ./test-in-qemu.sh [path-to-iso] [--uefi|--bios] [memory-in-MB]
# =============================================================================

set -euo pipefail

# Script is at <root>/build/scripts/test-in-qemu.sh
# PROJECT_ROOT is two levels up from scripts directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Validate project root
if [ ! -f "${PROJECT_ROOT}/README.md" ]; then
    echo "ERROR: Cannot determine project root from SCRIPT_DIR=${SCRIPT_DIR}"
    exit 1
fi

# Defaults
ISO_PATH=""
BOOT_MODE="bios"
MEMORY=4096
CPUS=4

# Parse optional ISO path argument (first non-option arg that is a file)
for arg in "$@"; do
    if [ -f "$arg" ]; then
        ISO_PATH="$arg"
        break
    fi
done

# Find ISO if not specified on command line
if [ -z "$ISO_PATH" ]; then
    # Look for built ISOs in build/output
    shopt -s nullglob
    candidates=(
        "${PROJECT_ROOT}/build/output/home/bright-os-"*"-home-amd64.iso"
        "${PROJECT_ROOT}/build/output/developer/bright-os-"*"-developer-amd64.iso"
        "${PROJECT_ROOT}/build/output/lite/bright-os-"*"-lite-amd64.iso"
    )
    shopt -u nullglob
    for candidate in "${candidates[@]}"; do
        if [ -f "$candidate" ]; then
            ISO_PATH="$candidate"
            break
        fi
    done
fi

if [ -z "$ISO_PATH" ] || [ ! -f "$ISO_PATH" ]; then
    echo "ERROR: No ISO file found."
    echo ""
    echo "Build one first:"
    echo "  ${PROJECT_ROOT}/build/scripts/build.sh home"
    echo ""
    echo "Or specify an ISO path:"
    echo "  $0 /path/to/bright-os.iso [--uefi|--bios] [memory-MB]"
    exit 1
fi

# Parse remaining options
while [[ $# -gt 0 ]]; do
    case "$1" in
        --uefi) BOOT_MODE="uefi"; shift ;;
        --bios) BOOT_MODE="bios"; shift ;;
        -h|--help)
            echo "Usage: $0 [path-to-iso] [--uefi|--bios] [memory-in-MB]"
            exit 0 ;;
        *)
            if [[ "$1" =~ ^[0-9]+$ ]]; then
                MEMORY="$1"
            fi
            shift ;;
    esac
done

if ! command -v qemu-system-x86_64 &>/dev/null; then
    echo "ERROR: qemu-system-x86_64 not found."
    echo "Install with: sudo apt-get install -y qemu-system-x86 qemu-utils ovmf"
    exit 1
fi

echo "=== Bright OS QEMU Test ==="
echo "ISO:    $ISO_PATH"
echo "Mode:   $BOOT_MODE"
echo "Memory: ${MEMORY} MB"
echo "CPUs:   $CPUS"
echo "Project root: ${PROJECT_ROOT}"
echo ""

# Check for KVM
KVM_ARGS=""
if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    KVM_ARGS="-enable-kvm -cpu host"
    echo "KVM acceleration: enabled"
else
    echo "KVM acceleration: not available (slower emulation)"
fi

# Check for OVMF for UEFI boot
UEFI_ARGS=""
if [ "$BOOT_MODE" = "uefi" ]; then
    OVMF_FOUND=""
    for ovmf in /usr/share/OVMF/OVMF_CODE.fd \
                /usr/share/OVMF/OVMF_CODE_4M.fd \
                /usr/share/edk2/x64/OVMF_CODE.fd \
                /usr/share/edk2-ovmf/x64/OVMF_CODE.fd \
                /usr/share/qemu/OVMF_CODE.fd; do
        if [ -f "$ovmf" ]; then
            UEFI_ARGS="-bios $ovmf"
            OVMF_FOUND="$ovmf"
            break
        fi
    done
    if [ -z "$UEFI_ARGS" ]; then
        echo "WARNING: OVMF firmware not found. Install ovmf package for UEFI testing."
        echo "  sudo apt-get install -y ovmf"
        echo "Falling back to BIOS boot."
        BOOT_MODE="bios"
    else
        echo "UEFI firmware: $OVMF_FOUND"
    fi
fi

echo ""
echo "Starting QEMU..."
echo "  Close QEMU window (or press Ctrl+C here) to stop."
echo ""

exec qemu-system-x86_64 \
    -cdrom "$ISO_PATH" \
    -m "$MEMORY" \
    $KVM_ARGS \
    -smp "$CPUS" \
    -vga virtio \
    -display gtk \
    -usb -device usb-ehci -device usb-tablet \
    -netdev user,id=net0 \
    -device e1000,netdev=net0 \
    -boot d \
    $UEFI_ARGS
