#!/bin/bash
# =============================================================================
# Bright OS ISO Validation Script
# Validates a built ISO for filesystem integrity, boot structures, and content.
# Exits 0 if validation passes, 1 if critical checks fail.
# Warnings do not cause failure.
# =============================================================================

set -u

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0
INCONCLUSIVE=0

pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; WARN=$((WARN+1)); }
inconclusive() { echo -e "${BLUE}[INCONCLUSIVE]${NC} $*"; INCONCLUSIVE=$((INCONCLUSIVE+1)); }

usage() {
    cat <<EOF
Bright OS ISO Validator

Usage: $0 <path-to.iso>

Validates:
  - File readability and basic size
  - ISO 9660 filesystem
  - Hybrid/USB boot signature
  - BIOS and UEFI boot structures
  - Live system files (kernel, initrd, squashfs)
  - GRUB presence
  - SHA256 checksum (if .sha256 file exists)
EOF
    exit "${1:-0}"
}

ISO_PATH="${1:-}"
if [ -z "$ISO_PATH" ]; then
    echo "ERROR: No ISO path specified."
    usage 1
fi

if [ "$ISO_PATH" = "-h" ] || [ "$ISO_PATH" = "--help" ]; then
    usage 0
fi

if [ ! -f "$ISO_PATH" ]; then
    echo "ERROR: File not found: $ISO_PATH"
    exit 1
fi

if [ ! -r "$ISO_PATH" ]; then
    echo "ERROR: File not readable: $ISO_PATH"
    exit 1
fi

echo "========================================"
echo "  Bright OS ISO Validation"
echo "  File: $ISO_PATH"
echo "========================================"

# --- Check available tools ---
HAVE_FILE=false
HAVE_ISOINFO=false
HAVE_XXD=false
HAVE_DD=false
HAVE_SHA=false

command -v file &>/dev/null && HAVE_FILE=true
command -v isoinfo &>/dev/null && HAVE_ISOINFO=true
command -v xxd &>/dev/null && HAVE_XXD=true
command -v dd &>/dev/null && HAVE_DD=true
command -v sha256sum &>/dev/null && HAVE_SHA=true

echo ""
echo "--- File Integrity ---"

# File size
SIZE=$(stat -c%s "$ISO_PATH" 2>/dev/null || echo 0)
if [ "$SIZE" -le 0 ]; then
    fail "ISO file is empty"
else
    SIZE_MB=$((SIZE / 1024 / 1024))
    if [ "$SIZE" -gt 100000000 ]; then
        pass "File size: ${SIZE_MB} MB"
    else
        fail "File size too small: ${SIZE_MB} MB (expected > 100 MB for a real ISO)"
    fi
fi

# File is readable
if [ -r "$ISO_PATH" ]; then
    pass "File is readable"
else
    fail "File is not readable"
fi

# SHA256 checksum verification
SHA_FILE="${ISO_PATH}.sha256"
if [ -f "$SHA_FILE" ]; then
    if $HAVE_SHA; then
        if (cd "$(dirname "$ISO_PATH")" && sha256sum -c "$(basename "$SHA_FILE")") 2>/dev/null; then
            pass "SHA256 checksum verified"
        else
            fail "SHA256 checksum mismatch!"
        fi
    else
        warn "sha256sum not available; skipping checksum verification"
    fi
else
    warn "No .sha256 checksum file found (${SHA_FILE})"
fi

echo ""
echo "--- ISO Format ---"

# File type detection
if $HAVE_FILE; then
    FTYPE=$(file "$ISO_PATH")
    if echo "$FTYPE" | grep -qi "iso 9660"; then
        pass "Valid ISO 9660 filesystem"
    else
        fail "Not recognized as ISO 9660 (file says: $(echo "$FTYPE" | head -c 200))"
    fi
    if echo "$FTYPE" | grep -qi "hybrid"; then
        pass "Hybrid ISO (USB-bootable)"
    else
        warn "May not be hybrid ISO (USB bootability uncertain)"
    fi
else
    inconclusive "Cannot verify ISO type ('file' command not available)"
fi

echo ""
echo "--- Boot Structures ---"

# MBR boot signature check (BIOS boot)
if $HAVE_DD && $HAVE_XXD; then
    SIG=$(dd if="$ISO_PATH" bs=1 count=2 skip=510 2>/dev/null | xxd -p)
    if [ "$SIG" = "55aa" ]; then
        pass "MBR boot signature 0x55AA present (BIOS bootable)"
    else
        fail "MBR boot signature not found (got '${SIG}', expected '55aa')"
    fi
elif $HAVE_DD; then
    # xxd not available, try od
    SIG=$(dd if="$ISO_PATH" bs=1 count=2 skip=510 2>/dev/null | od -An -tx1 | tr -d ' \n')
    if [ "$SIG" = "55aa" ]; then
        pass "MBR boot signature 0x55AA present (BIOS bootable)"
    else
        inconclusive "Cannot verify MBR boot signature (dd/xxd/od tools needed)"
    fi
else
    warn "'dd' not available; skipping MBR boot signature check"
fi

# ISO9660 structure inspection
echo ""
echo "--- ISO Contents ---"
if $HAVE_ISOINFO; then
    if isoinfo -d -i "$ISO_PATH" &>/dev/null; then
        pass "ISO9660 primary volume descriptor readable"
        VOLUME=$(isoinfo -d -i "$ISO_PATH" 2>/dev/null | grep "Volume id:" | cut -d: -f2- | xargs || echo "(unknown)")
        echo "  Volume ID: ${VOLUME}"

        # Get full listing
        ISO_LISTING=$(mktemp /tmp/bright-iso-list-XXXXXX.txt)
        # Use isoinfo -f (full-path listing) and strip ISO9660 version suffixes
        # (e.g. ;1) before grepping. ISO9660 paths are UPPERCASE by default so
        # use case-insensitive matching.
        if isoinfo -i "$ISO_PATH" -f 2>/dev/null | sed 's/;[0-9]*$//' > "$ISO_LISTING"; then
            # Check for kernel (vmlinuz or vmlinuz-* in /live/)
            if grep -qiE '^/live/vmlinuz' "$ISO_LISTING"; then
                pass "Kernel (live/vmlinuz) found"
            else
                fail "Kernel (live/vmlinuz) not found in ISO"
            fi

            # Check for initrd (initrd.img or initrd.img-* in /live/)
            if grep -qiE '^/live/initrd' "$ISO_LISTING"; then
                pass "Initrd (live/initrd*) found"
            else
                fail "Initrd not found in ISO"
            fi

            # Check for squashfs (filesystem.squashfs or NNN-filesystem.squashfs)
            if grep -qiE '^/live/.*\.squashfs' "$ISO_LISTING"; then
                pass "Squashfs root filesystem present (live/*.squashfs)"
            else
                fail "filesystem.squashfs not found — ISO has no live system"
            fi

            # Check for EFI boot (efi.img or EFI/BOOT/BOOTX64.EFI)
            if grep -qiE 'efi\.img$|efi/boot/bootx64\.efi$' "$ISO_LISTING"; then
                pass "EFI boot files detected (UEFI boot support)"
            else
                fail "EFI boot files not detected — ISO may not boot on UEFI systems"
            fi

            # Check for GRUB
            if grep -qiE '/boot/grub/' "$ISO_LISTING"; then
                pass "GRUB bootloader files present"
            else
                warn "GRUB files not found"
            fi

            # Check for isolinux (BIOS boot)
            if grep -qiE '/isolinux/' "$ISO_LISTING"; then
                pass "ISOLINUX present (BIOS boot via isolinux)"
            else
                warn "ISOLINUX not found (BIOS boot may rely solely on GRUB)"
            fi
        else
            fail "Could not list ISO9660 directory contents"
        fi
        rm -f "$ISO_LISTING"
    else
        fail "Cannot read ISO9660 filesystem with isoinfo"
    fi
else
    inconclusive "Cannot verify ISO contents (isoinfo/xorriso not available)"
    echo "  Install with: sudo apt-get install -y genisoimage xorriso"
fi

# --- Report ---
echo ""
echo "========================================"
echo "  Validation Results"
echo "  Passed:       $PASS"
echo "  Warnings:     $WARN"
echo "  Failed:       $FAIL"
echo "  Inconclusive: $INCONCLUSIVE"
echo "========================================"

if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo -e "${RED}Validation FAILED: $FAIL critical check(s) failed.${NC}"
    echo "The ISO is likely not bootable or is corrupt."
    exit 1
elif [ "$INCONCLUSIVE" -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}Validation INCONCLUSIVE: $INCONCLUSIVE check(s) could not be performed.${NC}"
    echo "Install missing tools (isoinfo, file, xorriso) and re-run for complete results."
    echo ""
    echo "IMPORTANT: Passing validation does NOT prove the OS boots correctly."
    echo "Actual boot testing (QEMU or real hardware) is required to confirm bootability."
    exit 2
else
    echo ""
    echo -e "${GREEN}Validation PASSED.${NC}"
    echo ""
    if [ "$WARN" -gt 0 ]; then
        echo -e "${YELLOW}Note: ${WARN} warning(s) present (see above).${NC}"
        echo ""
    fi
    echo "Next steps:"
    echo "  1. Test boot in QEMU (does NOT guarantee boot success — visual check required):"
    echo "     qemu-system-x86_64 -cdrom $ISO_PATH -m 4G -enable-kvm"
    echo "  2. Test UEFI boot:"
    echo "     qemu-system-x86_64 -cdrom $ISO_PATH -m 4G -enable-kvm -bios /usr/share/OVMF/OVMF_CODE.fd"
    echo "  3. Write to USB and test on real hardware:"
    echo "     sudo dd if=$ISO_PATH of=/dev/sdX bs=4M status=progress conv=fsync"
    echo ""
    echo "IMPORTANT: Passing validation does NOT prove the OS boots correctly."
    echo "Actual boot testing (QEMU or real hardware) is required to confirm bootability."
    exit 0
fi
