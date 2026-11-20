#!/bin/bash
# =============================================================================
# Bright OS ISO Validation Script
# Validates a built ISO for correctness, bootability, and integrity.
# =============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

ISO_PATH="$1"
if [ -z "$ISO_PATH" ] || [ ! -f "$ISO_PATH" ]; then
    echo "Usage: $0 <path-to-bright-os.iso>"
    echo "Validates a Bright OS ISO image."
    exit 1
fi

PASS=0
FAIL=0
WARN=0

pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; WARN=$((WARN+1)); }

echo "========================================"
echo "  Bright OS ISO Validation"
echo "  File: $ISO_PATH"
echo "========================================"

# Basic file checks
echo ""
echo "--- File Integrity ---"
SIZE=$(stat -c%s "$ISO_PATH" 2>/dev/null || echo 0)
SIZE_MB=$((SIZE / 1024 / 1024))
if [ "$SIZE" -gt 100000000 ]; then
    pass "ISO size: ${SIZE_MB} MB (expected > 100 MB)"
else
    fail "ISO size too small: ${SIZE_MB} MB"
fi

# Check for checksum file
SHA_FILE="${ISO_PATH}.sha256"
if [ -f "$SHA_FILE" ]; then
    if sha256sum -c "$SHA_FILE" 2>/dev/null; then
        pass "SHA256 checksum verified"
    else
        fail "SHA256 checksum mismatch"
    fi
else
    warn "No .sha256 checksum file found"
fi

# ISO format validation
echo ""
echo "--- ISO Format ---"
if file "$ISO_PATH" | grep -qi "iso 9660\|hybrid"; then
    pass "Valid ISO 9660 image"
else
    fail "Not a valid ISO 9660 image"
fi

if file "$ISO_PATH" | grep -qi "hybrid"; then
    pass "Hybrid ISO (USB-bootable)"
else
    warn "May not be a hybrid ISO (USB bootability uncertain)"
fi

# MBR boot code check
if dd if="$ISO_PATH" bs=1 count=2 skip=510 2>/dev/null | xxd | grep -q "55 aa"; then
    pass "MBR boot signature present (BIOS bootable)"
else
    warn "MBR boot signature not found"
fi

# ISO structure inspection
echo ""
echo "--- ISO Structure ---"
if command -v isoinfo &>/dev/null; then
    if isoinfo -d -i "$ISO_PATH" &>/dev/null; then
        pass "ISO9660 filesystem readable"
        VOLUME=$(isoinfo -d -i "$ISO_PATH" 2>/dev/null | grep "Volume id:" | cut -d: -f2- | xargs)
        echo "  Volume: ${VOLUME}"
    else
        fail "Cannot read ISO9660 filesystem"
    fi
    
    # Check for live system files
    if isoinfo -i "$ISO_PATH" -l 2>/dev/null | grep -q "live/vmlinuz"; then
        pass "Kernel (vmlinuz) found in /live/"
    else
        fail "Kernel not found in /live/"
    fi
    
    if isoinfo -i "$ISO_PATH" -l 2>/dev/null | grep -q "live/initrd"; then
        pass "Initrd found in /live/"
    else
        fail "Initrd not found in /live/"
    fi
    
    if isoinfo -i "$ISO_PATH" -l 2>/dev/null | grep -q "live/filesystem.squashfs"; then
        pass "Squashfs root filesystem present"
    else
        fail "filesystem.squashfs not found"
    fi
    
    # Check for EFI boot
    if isoinfo -i "$ISO_PATH" -l 2>/dev/null | grep -q "efi.img\|EFI/boot"; then
        pass "EFI boot support detected"
    else
        warn "EFI boot files not detected"
    fi
    
    # Check for GRUB
    if isoinfo -i "$ISO_PATH" -l 2>/dev/null | grep -q "grub"; then
        pass "GRUB bootloader present"
    else
        warn "GRUB files not found"
    fi
else
    warn "isoinfo not available, skipping structure checks"
fi

# Report
echo ""
echo "========================================"
echo "  Validation Results"
echo "  Passed: $PASS"
echo "  Warnings: $WARN"
echo "  Failed: $FAIL"
echo "========================================"

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}Validation FAILED${NC}"
    exit 1
else
    echo -e "${GREEN}Validation PASSED${NC}"
    echo ""
    echo "Boot testing recommendations:"
    echo "  1. Test in QEMU:  qemu-system-x86_64 -cdrom $ISO_PATH -m 4G -enable-kvm"
    echo "  2. Test on USB:   dd if=$ISO_PATH of=/dev/sdX bs=4M status=progress"
    echo "  3. Test on real hardware: boot from USB on both UEFI and BIOS systems"
    exit 0
fi
