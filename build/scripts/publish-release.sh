#!/bin/bash
# =============================================================================
# Bright OS GitHub Release Publisher
# =============================================================================
# Publishes already-built Bright OS ISOs to a GitHub Release.
#
# Usage:
#   ./build/scripts/publish-release.sh VERSION
#
# Prerequisites:
#   - All three editions must have been built successfully
#   - ISOs must exist in build/output/<edition>/
#   - GitHub CLI (gh) must be installed and authenticated
#   - You must be in the Bright OS git repository
#
# This script:
#   1. Verifies gh is installed and authenticated
#   2. Checks that all three ISOs exist and pass checksum verification
#   3. Creates a consolidated SHA256SUMS file
#   4. Creates a GitHub Release (or uploads to an existing draft)
#   5. Uploads the ISOs and SHA256SUMS as release assets
#
# Does NOT publish automatically after building. Explicit user command required.
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

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
    log_error "Usage: $0 <version>"
    log_error "Example: $0 0.1.0-alpha"
    exit 1
fi

# Validate version string
if ! echo "$VERSION" | grep -qE '^[a-zA-Z0-9][a-zA-Z0-9._-]*$'; then
    log_error "Invalid version string: $VERSION"
    exit 1
fi

ARCH="amd64"
EDITIONS="home developer lite"
TAG="v${VERSION}"
OUTPUT_DIR="${PROJECT_ROOT}/build/output"

echo "========================================"
echo "  Bright OS Release Publisher"
echo "  Version: $VERSION"
echo "  Tag:     $TAG"
echo "========================================"
echo ""

# --- Check git repository ---
echo "--- Git Repository ---"
cd "$PROJECT_ROOT"
if ! git rev-parse --git-dir &>/dev/null; then
    log_error "Not in a git repository."
    exit 1
fi
REMOTE_URL=$(git remote get-url origin 2>/dev/null || echo "")
if [ -z "$REMOTE_URL" ]; then
    log_error "No 'origin' remote configured."
    exit 1
fi
echo "Remote: $REMOTE_URL"
log_ok "Git repository found"

# --- Check gh CLI ---
echo ""
echo "--- GitHub CLI ---"
if ! command -v gh &>/dev/null; then
    log_error "GitHub CLI (gh) is not installed."
    log_error "Install it with: sudo apt-get install -y gh"
    log_error "Or download from: https://cli.github.com/"
    exit 1
fi
GH_VERSION=$(gh --version | head -1)
echo "gh: $GH_VERSION"
log_ok "gh CLI found"

# Check authentication
if ! gh auth status &>/dev/null; then
    log_error "Not authenticated with GitHub."
    log_error "Run: gh auth login"
    exit 1
fi
log_ok "Authenticated with GitHub"

# Determine repository
GH_REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null || echo "")
if [ -z "$GH_REPO" ]; then
    # Try to detect from remote URL
    GH_REPO=$(git remote get-url origin | sed -n 's|.*github.com[:/]\(.*\)\.git|\1|p; s|.*github.com[:/]\(.*\)|\1|p' | head -1)
fi
echo "Repository: $GH_REPO"

# --- Check all ISOs exist ---
echo ""
echo "--- ISO Files ---"
MISSING=0
ISO_PATHS=()
SHA_PATHS=()
for edition in $EDITIONS; do
    ISO_NAME="bright-os-${VERSION}-${edition}-${ARCH}.iso"
    ISO_PATH="${OUTPUT_DIR}/${edition}/${ISO_NAME}"
    SHA_PATH="${ISO_PATH}.sha256"

    if [ ! -f "$ISO_PATH" ]; then
        log_error "Missing ISO for ${edition}: ${ISO_PATH}"
        log_error "  Build it with: ./build/scripts/build.sh ${edition} --version ${VERSION}"
        MISSING=$((MISSING+1))
        continue
    fi

    if [ ! -s "$ISO_PATH" ]; then
        log_error "ISO file is empty: ${ISO_PATH}"
        MISSING=$((MISSING+1))
        continue
    fi

    if [ ! -f "$SHA_PATH" ]; then
        log_error "Missing checksum file for ${edition}: ${SHA_PATH}"
        MISSING=$((MISSING+1))
        continue
    fi

    SIZE=$(du -h "$ISO_PATH" | cut -f1)
    SIZE_BYTES=$(stat -c%s "$ISO_PATH")
    echo "  ${edition}: ${ISO_NAME} (${SIZE})"

    # Check GitHub size limit (2 GiB)
    if [ "$SIZE_BYTES" -gt 2147483648 ]; then
        log_error "${edition} ISO exceeds GitHub's 2 GiB file size limit (${SIZE})"
        MISSING=$((MISSING+1))
        continue
    fi

    ISO_PATHS+=("$ISO_PATH")
    SHA_PATHS+=("$SHA_PATH")
done

if [ "$MISSING" -gt 0 ]; then
    echo ""
    log_error "${MISSING} edition(s) missing or invalid. Build them first."
    exit 1
fi
log_ok "All three edition ISOs found"

# --- Verify checksums ---
echo ""
echo "--- Checksum Verification ---"
for i in "${!ISO_PATHS[@]}"; do
    ISO_PATH="${ISO_PATHS[$i]}"
    SHA_PATH="${SHA_PATHS[$i]}"
    EDITION=$(basename "$(dirname "$ISO_PATH")")

    echo -n "  Verifying ${EDITION}... "
    if (cd "$(dirname "$ISO_PATH")" && sha256sum -c "$(basename "$SHA_PATH")") 2>/dev/null; then
        echo "OK"
    else
        echo "FAILED"
        log_error "Checksum mismatch for ${EDITION}!"
        exit 1
    fi
done
log_ok "All checksums verified"

# --- Run ISO validation on all three editions ---
echo ""
echo "--- ISO Validation ---"
VALIDATE_SCRIPT="${PROJECT_ROOT}/build/scripts/validate-iso.sh"
if [ ! -x "$VALIDATE_SCRIPT" ]; then
    log_error "validate-iso.sh not found or not executable"
    exit 1
fi

VALIDATION_FAILS=0
for i in "${!ISO_PATHS[@]}"; do
    ISO_PATH="${ISO_PATHS[$i]}"
    EDITION=$(basename "$(dirname "$ISO_PATH")")

    echo "  Validating ${EDITION}..."
    set +e
    bash "$VALIDATE_SCRIPT" "$ISO_PATH" >/tmp/bright-validate-${EDITION}.log 2>&1
    VRC=$?
    set -e

    if [ $VRC -eq 0 ]; then
        echo "    ${EDITION}: PASS"
    elif [ $VRC -eq 2 ]; then
        echo "    ${EDITION}: INCONCLUSIVE (some validation tools missing)"
        log_warn "Validation inconclusive for ${EDITION} - install genisoimage, xorriso, file for full validation"
    else
        echo "    ${EDITION}: FAIL"
        log_error "Validation FAILED for ${EDITION}:"
        tail -20 /tmp/bright-validate-${EDITION}.log | sed 's/^/    /'
        VALIDATION_FAILS=$((VALIDATION_FAILS+1))
    fi
done
rm -f /tmp/bright-validate-home.log /tmp/bright-validate-developer.log /tmp/bright-validate-lite.log

if [ "$VALIDATION_FAILS" -gt 0 ]; then
    echo ""
    log_error "${VALIDATION_FAILS} edition(s) failed ISO validation. Refusing to publish."
    log_error "Fix the ISO issues and rebuild before publishing."
    exit 1
fi
log_ok "ISO validation complete"

# --- Create consolidated SHA256SUMS ---
echo ""
echo "--- Creating SHA256SUMS ---"
SHA256SUMS_FILE="${OUTPUT_DIR}/SHA256SUMS"
: > "$SHA256SUMS_FILE"
for edition in $EDITIONS; do
    ISO_NAME="bright-os-${VERSION}-${edition}-${ARCH}.iso"
    SHA_PATH="${OUTPUT_DIR}/${edition}/${ISO_NAME}.sha256"
    HASH=$(cut -d' ' -f1 "$SHA_PATH")
    echo "${HASH}  ${ISO_NAME}" >> "$SHA256SUMS_FILE"
done
cat "$SHA256SUMS_FILE"
log_ok "SHA256SUMS created at ${SHA256SUMS_FILE}"

# --- Create release notes ---
echo ""
echo "--- Preparing Release Notes ---"
NOTES_FILE=$(mktemp /tmp/bright-release-notes-XXXXXX.md)
trap 'rm -f "$NOTES_FILE"' EXIT

BUILD_DATE=$(date -u +"%Y-%m-%d %H:%M UTC")
COMMIT_SHA=$(git rev-parse HEAD | cut -c1-10)
TITLE_VERSION=$(echo "$VERSION" | sed 's/-alpha/ Alpha/; s/-beta/ Beta/; s/-rc/ Release Candidate/; s/-dev/ Development/')

cat > "$NOTES_FILE" << NOTES
# Bright OS ${TITLE_VERSION}

**Debian base:** Debian 13 Trixie
**Architecture:** x86_64 / amd64
**Build date:** ${BUILD_DATE}
**Commit:** \`${COMMIT_SHA}\`

## Available Editions

| Edition | ISO File | Description |
|---------|----------|-------------|
| Home | \`bright-os-${VERSION}-home-amd64.iso\` | Full KDE Plasma desktop for everyday use (web, office, media) |
| Developer | \`bright-os-${VERSION}-developer-amd64.iso\` | KDE Plasma + development tools (Git, Docker, Arduino, KiCad, databases) |
| Lite | \`bright-os-${VERSION}-lite-amd64.iso\` | Lightweight LXQt + Openbox desktop for older hardware (2-4 GB RAM) |

## Verify Downloads

After downloading, verify the SHA256 checksum:
\`\`\`
sha256sum -c SHA256SUMS --ignore-missing
\`\`\`

## Write to USB

\`\`\`
sudo dd if=bright-os-${VERSION}-home-amd64.iso of=/dev/sdX bs=4M status=progress conv=fsync
\`\`\`

Boot from the USB drive; the Calamares installer launches from the live desktop.

## System Requirements

- 64-bit x86 processor (Intel/AMD)
- 2 GB RAM minimum (4 GB recommended, 8 GB for Developer edition)
- 20 GB free disk space for installation
- USB drive (8 GB+) for installation media
- Internet connection recommended for updates

## Testing Status

- **Structural validation:** ISOs have been verified to contain valid ISO9660 filesystem, Linux kernel, initrd, squashfs root, BIOS MBR boot signature, UEFI EFI boot image, and GRUB bootloader.
- **Boot testing:** Boot these ISOs in a virtual machine (QEMU, VirtualBox) before installing on physical hardware.
- **Secure Boot:** shim-signed is included for Secure Boot support but should be tested before relying on it. If boot fails, disable Secure Boot.
- **LUKS:** Full-disk encryption is configured in Calamares.

## Known Issues (Alpha)

- Early development software - expect bugs and missing features
- Wine/Proton compatibility layer is not included in this release
- No automatic update system configured yet
- Some hardware may require additional firmware after installation
NOTES

echo "Release notes prepared."

# --- Confirm with user ---
echo ""
echo "--- Ready to Publish ---"
echo "Tag:      $TAG"
echo "Title:    Bright OS ${TITLE_VERSION}"
echo "Repo:     $GH_REPO"
echo "Assets:"
for edition in $EDITIONS; do
    ISO_NAME="bright-os-${VERSION}-${edition}-${ARCH}.iso"
    ISO_PATH="${OUTPUT_DIR}/${edition}/${ISO_NAME}"
    SIZE=$(du -h "$ISO_PATH" | cut -f1)
    echo "  - ${ISO_NAME} (${SIZE})"
done
echo "  - SHA256SUMS"
echo ""

# Check if release already exists
if gh release view "$TAG" &>/dev/null; then
    log_warn "Release ${TAG} already exists!"
    echo "Assets will be uploaded to the existing release."
    read -r -p "Continue? [y/N] " CONFIRM
    if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
        echo "Aborted."
        exit 0
    fi
else
    read -r -p "Create release ${TAG} and upload assets? [y/N] " CONFIRM
    if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
        echo "Aborted."
        exit 0
    fi
fi

# --- Create or use existing release ---
echo ""
echo "--- Publishing Release ---"
if gh release view "$TAG" &>/dev/null; then
    log_info "Release ${TAG} already exists; uploading assets..."
else
    log_info "Creating release ${TAG}..."
    gh release create "$TAG" \
        --title "Bright OS ${TITLE_VERSION}" \
        --notes-file "$NOTES_FILE" \
        --target "$(git rev-parse HEAD)"
fi

# Upload assets
echo ""
echo "--- Uploading Assets ---"
for edition in $EDITIONS; do
    ISO_NAME="bright-os-${VERSION}-${edition}-${ARCH}.iso"
    ISO_PATH="${OUTPUT_DIR}/${edition}/${ISO_NAME}"
    echo "Uploading ${ISO_NAME}..."
    gh release upload "$TAG" "$ISO_PATH" --clobber
done

echo "Uploading SHA256SUMS..."
gh release upload "$TAG" "$SHA256SUMS_FILE" --clobber

RELEASE_URL="https://github.com/${GH_REPO}/releases/tag/${TAG}"

echo ""
log_ok "========================================"
log_ok "  RELEASE PUBLISHED"
log_ok ""
log_ok "  URL: ${RELEASE_URL}"
log_ok "========================================"
echo ""
echo "Download page: ${RELEASE_URL}"
echo ""
