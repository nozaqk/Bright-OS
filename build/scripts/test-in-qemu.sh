#!/bin/bash
# =============================================================================
# Bright OS QEMU Boot Test Script
# Boots the ISO in QEMU for quick testing without writing to USB.
#
# Usage: ./test-in-qemu.sh [path-to-iso] [--uefi|--bios] [memory-in-MB]
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Defaults
ISO_PATH=""
BOOT_MODE="bios"
MEMORY=4096
CPUS=4

# Find ISO if not specified
if [ $# -ge 1 ] && [ -f "$1" ]; then
    ISO_PATH="$1"
    shift
fi

if [ -z "$ISO_PATH" ]; then
    # Look for built ISOs
    for candidate in \
        "${PROJECT_ROOT}/build/output/home/bright-os-"*"-home-amd64.iso" \
        "${PROJECT_ROOT}/build/output/developer/bright-os-"*"-developer-amd64.iso" \
        "${PROJECT_ROOT}/build/output/lite/bright-os-"*"-lite-amd64.iso"; do
        if [ -f "$candidate" ]; then
            ISO_PATH="$candidate"
            break
        fi
    done
fi

if [ -z "$ISO_PATH" ] || [ ! -f "$ISO_PATH" ]; then
    echo "Error: No ISO file found. Build one first with ./build/scripts/build.sh [edition]"
    echo ""
    echo "Usage: $0 [path-to-iso] [--uefi|--bios] [memory-in-MB]"
    exit 1
fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --uefi) BOOT_MODE="uefi"; shift ;;
        --bios) BOOT_MODE="bios"; shift ;;
        *)
            if [[ "$1" =~ ^[0-9]+$ ]]; then
                MEMORY="$1"
            fi
            shift ;;
    esac
done

echo "=== Bright OS QEMU Test ==="
echo "ISO:    $ISO_PATH"
echo "Mode:   $BOOT_MODE"
echo "Memory: ${MEMORY} MB"
echo "CPUs:   $CPUS"
echo ""

# Check for KVM
KVM_ARGS=""
if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
    KVM_ARGS="-enable-kvm -cpu host"
    echo "KVM acceleration: enabled"
else
    echo "KVM acceleration: not available (slower emulation)"
fi

# Check for OVMF for UEFI
UEFI_ARGS=""
if [ "$BOOT_MODE" = "uefi" ]; then
    for ovmf in /usr/share/OVMF/OVMF_CODE.fd /usr/share/edk2/x64/OVMF_CODE.fd /usr/share/edk2-ovmf/x64/OVMF_CODE.fd; do
        if [ -f "$ovmf" ]; then
            UEFI_ARGS="-bios $ovmf"
            echo "UEFI firmware: $ovmf"
            break
        fi
    done
    if [ -z "$UEFI_ARGS" ]; then
        echo "Warning: OVMF not found. Install ovmf package for UEFI testing."
        echo "Falling back to BIOS boot."
        BOOT_MODE="bios"
    fi
fi

echo ""
echo "Starting QEMU... (close QEMU window or press Ctrl+C to stop)"
echo ""

exec qemu-system-x86_64 \
    -cdrom "$ISO_PATH" \
    -m "$MEMORY" \
    $KVM_ARGS \
    -smp "$CPUS" \
    -vga virtio \
    -display gtk \
    -usb -device usb-ehci -device usb-tablet \
    -net nic -net user \
    $UEFI_ARGS \
    -boot d
