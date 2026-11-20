#!/bin/bash
# =============================================================================
# Phase 13: GitHub Actions Workflow Tests
# Validates the build-bright-os.yml workflow structure and configuration.
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$PROJECT_ROOT"

PASS=0; FAIL=0
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass() { echo -e "${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }

WF=".github/workflows/build-bright-os.yml"

echo "============================================"
echo "  GitHub Actions Workflow Tests"
echo "============================================"

echo ""
echo "--- File existence ---"
if [ -f "$WF" ]; then
    pass "Workflow file exists at $WF"
else
    fail "Workflow file not found at $WF"
    echo "Cannot continue without workflow file"
    exit 1
fi

echo ""
echo "--- YAML syntax ---"
if python3 -c "
import yaml
with open('$WF') as f:
    data = yaml.safe_load(f)
if not isinstance(data, dict):
    exit(1)
if 'jobs' not in data:
    exit(1)
" 2>/dev/null; then
    pass "YAML is valid and has 'jobs' key"
else
    fail "YAML is invalid or missing 'jobs' key"
fi

echo ""
echo "--- Workflow name ---"
WF_NAME=$(python3 -c "
import yaml
with open('$WF') as f:
    data = yaml.safe_load(f)
print(data.get('name',''))
" 2>/dev/null)
if echo "$WF_NAME" | grep -qi "bright os.*build\|build.*bright os\|iso build"; then
    pass "Workflow name: $WF_NAME"
else
    fail "Workflow name not descriptive: '$WF_NAME'"
fi

echo ""
echo "--- Triggers ---"
# Check tag push trigger (v*)
if grep -q "tags:" "$WF" && grep -q "'v\*'" "$WF"; then
    pass "Tag push trigger configured (v* pattern)"
else
    fail "Tag push trigger not configured for v* tags"
fi

# Check workflow_dispatch
if grep -q "workflow_dispatch:" "$WF"; then
    pass "Manual workflow_dispatch trigger configured"
else
    fail "workflow_dispatch manual trigger missing"
fi

# Check manual dispatch inputs
if grep -q "version:" "$WF" && grep -q "edition:" "$WF"; then
    pass "Manual dispatch has version and edition inputs"
else
    fail "Manual dispatch missing version or edition inputs"
fi

echo ""
echo "--- Permissions and security ---"
# Default permissions should be read-only
if grep -q "contents: read" "$WF"; then
    pass "Default contents permission is read"
else
    fail "Default contents permission should be read"
fi

# Release job should have contents: write
if python3 -c "
import yaml
with open('$WF') as f:
    wf = yaml.safe_load(f)
# YAML loads 'on' as True; find release job
jobs = wf.get('jobs', {})
rel = jobs.get('create-release', {})
perms = rel.get('permissions', {})
exit(0 if perms.get('contents') == 'write' else 1)
" 2>/dev/null; then
    pass "Release job has contents: write permission"
else
    fail "Release job missing contents: write permission"
fi

# Build jobs should have contents: read (not write)
if python3 -c "
import yaml
with open('$WF') as f:
    wf = yaml.safe_load(f)
jobs = wf.get('jobs', {})
build = jobs.get('build-edition', {})
perms = build.get('permissions', {})
exit(0 if perms.get('contents') == 'read' else 1)
" 2>/dev/null; then
    pass "Build job uses read-only permissions"
else
    fail "Build job should have read-only permissions"
fi

# Check that third-party actions are pinned to SHAs (not floating tags)
UNPINNED=$(grep -E "uses: (actions|docker|github)/" "$WF" | grep -v "uses:.*@[0-9a-f]\{40\}" | grep -v "^#" || true)
if [ -z "$UNPINNED" ]; then
    pass "All third-party actions pinned to commit SHAs"
else
    fail "Some actions not pinned to SHAs:"
    echo "$UNPINNED" | while read line; do echo "  $line"; done
fi

# Concurrency group to prevent overlapping releases
if grep -q "concurrency:" "$WF" && grep -q "cancel-in-progress: true" "$WF"; then
    pass "Concurrency control enabled (cancel-in-progress: true)"
else
    fail "Missing concurrency control for release safety"
fi

echo ""
echo "--- Matrix configuration ---"
# Check all three editions are in the matrix
for edition in home developer lite; do
    if grep -q "edition: ${edition}" "$WF"; then
        pass "Edition '${edition}' included in build matrix"
    else
        fail "Edition '${edition}' missing from build matrix"
    fi
done

# Check fail-fast: false (all editions build even if one fails)
if grep -q "fail-fast: false" "$WF"; then
    pass "fail-fast: false (all editions run even on failure)"
else
    fail "fail-fast should be false for complete build picture"
fi

echo ""
echo "--- Build environment ---"
# Search both workflow and CI scripts for build environment details
SEARCH_TARGET="$WF build/scripts/ci/build-in-container.sh build/scripts/ci/validate-in-container.sh"

# Check that build runs on ubuntu-latest
if grep -q "runs-on: ubuntu-latest" "$WF"; then
    pass "Uses ubuntu-latest runners"
else
    fail "Should use ubuntu-latest runners"
fi

# Check Debian Trixie container is used (in workflow or CI scripts)
if grep -q "debian:trixie" $SEARCH_TARGET; then
    pass "Builds inside Debian Trixie Docker container"
else
    fail "Should use Debian Trixie container for build environment"
fi

# Check container runs with --privileged for chroot operations
if grep -q "\-\-privileged" $SEARCH_TARGET; then
    pass "Docker container runs with --privileged (needed for chroot mounts)"
else
    fail "Docker container needs --privileged for chroot/mount operations"
fi

# Check build dependencies are installed (in CI scripts)
for dep in live-build debootstrap squashfs-tools xorriso isolinux grub-pc-bin grub-efi-amd64-bin; do
    if grep -q "$dep" build/scripts/ci/build-in-container.sh; then
        pass "Build dependency '${dep}' is installed in container"
    else
        fail "Build dependency '${dep}' not found in container install step"
    fi
done

echo ""
echo "--- Version extraction ---"
# Check version extraction strips 'v' prefix from tags
if grep -q 'GITHUB_REF#refs/tags/v' "$WF"; then
    pass "Version strips leading 'v' from tag (v0.1.0-alpha -> 0.1.0-alpha)"
else
    fail "Version extraction should strip 'v' prefix from tags"
fi

# Check version string validation
if grep -qE "grep -qE.*a-zA-Z0-9" "$WF"; then
    pass "Version string is validated (safe characters only)"
else
    fail "Version string should be validated for safe filename characters"
fi

echo ""
echo "--- Build command ---"
# Check build script is called correctly (in CI scripts)
if grep -q "build/scripts/build.sh" build/scripts/ci/build-in-container.sh; then
    pass "Calls build/scripts/build.sh"
else
    fail "Should call build/scripts/build.sh"
fi

# Check --version flag is used
if grep -q "\-\-version" build/scripts/ci/build-in-container.sh; then
    pass "Passes --version flag to build script"
else
    fail "Should pass --version flag"
fi

echo ""
echo "--- ISO validation ---"
# Check ISO existence check (in CI scripts)
if grep -q "ISO not found\|Expected ISO not found" build/scripts/ci/build-in-container.sh build/scripts/ci/validate-in-container.sh; then
    pass "Checks for ISO existence after build"
else
    fail "Should check for ISO existence"
fi

# Check ISO size check
if grep -q "ISO_SIZE_MB" build/scripts/ci/validate-in-container.sh && grep -q "lt 100\|< 100" build/scripts/ci/validate-in-container.sh; then
    pass "Rejects ISOs smaller than 100 MB"
else
    fail "Should reject suspiciously small ISOs"
fi

# Check GitHub 2 GiB size limit
if grep -q "2147483648\|2048" build/scripts/ci/validate-in-container.sh; then
    pass "Checks GitHub 2 GiB asset size limit"
else
    fail "Should check GitHub's 2 GiB per-file limit"
fi

# Check validate-iso.sh is run
if grep -q "validate-iso.sh" build/scripts/ci/validate-in-container.sh; then
    pass "Runs validate-iso.sh for structural validation"
else
    fail "Should run validate-iso.sh"
fi

# Check checksum verification
if grep -q "sha256sum -c" build/scripts/ci/validate-in-container.sh; then
    pass "Verifies SHA256 checksum after build"
else
    fail "Should verify SHA256 checksum"
fi

# Check validate-iso runs inside Debian container
if grep -q "debian:trixie" build/scripts/ci/validate-in-container.sh; then
    pass "Validation runs inside Debian Trixie container (correct tool versions)"
else
    fail "Validation should run inside Debian Trixie container"
fi

echo ""
echo "--- Artifact upload ---"
# Check upload-artifact is used
if grep -q "upload-artifact" "$WF"; then
    pass "Uses upload-artifact action"
else
    fail "Should use upload-artifact action"
fi

# Check artifact names follow convention
for edition in home developer lite; do
    if grep -q "bright-os-${edition}-amd64" "$WF"; then
        pass "Artifact name 'bright-os-${edition}-amd64' follows convention"
    else
        fail "Artifact name for ${edition} doesn't follow bright-os-{edition}-amd64 convention"
    fi
done

# Check retention period
if grep -q "retention-days: 14" "$WF"; then
    pass "Artifact retention set to 14 days"
else
    fail "Should set artifact retention (14 days recommended)"
fi

# Check if-no-files-found: error (don't silently succeed with no artifacts)
if grep -q "if-no-files-found: error" "$WF"; then
    pass "if-no-files-found set to error (fails on missing artifacts)"
else
    fail "Should set if-no-files-found: error"
fi

# Check artifacts include ISO, checksum, and build log
for artifact in "\.iso\b" "\.sha256" "build\.log"; do
    if grep -q "$artifact" "$WF"; then
        pass "Artifacts include $(echo $artifact | sed 's/\\b//;s/\\//g') files"
    else
        fail "Artifacts should include $artifact files"
    fi
done

echo ""
echo "--- Release job ---"
# Check release job depends on build-edition
if grep -q "needs: build-edition" "$WF"; then
    pass "Release job needs build-edition (waits for all editions)"
else
    fail "Release job must depend on build-edition"
fi

# Check release only on tag push
if grep -q "startsWith(github.ref" "$WF" && grep -q "refs/tags/v" "$WF"; then
    pass "Release job condition checks for v* tag"
else
    fail "Release job should only run on v* tag pushes"
fi

# Check manual dispatch does NOT create a release
# The create-release job if-condition must check for push (tag) events only
if python3 -c "
import yaml
with open('$WF') as f:
    wf = yaml.safe_load(f)
jobs = wf.get('jobs', {})
rel = jobs.get('create-release', {})
cond = rel.get('if', '')
# Must check for push event and tag ref
if 'push' in cond and 'refs/tags/v' in cond:
    exit(0)
exit(1)
" 2>/dev/null; then
    pass "Release job only runs on push tag events (not manual dispatch)"
else
    fail "Release job should not run on manual workflow_dispatch"
fi

# Check download-artifact in release job
if awk '/^  create-release:/,0' "$WF" | grep -q "download-artifact"; then
    pass "Release job downloads artifacts from build jobs"
else
    fail "Release job should download artifacts before publishing"
fi

# Check gh release create is used
if grep -q "gh release create" "$WF"; then
    pass "Uses 'gh release create' to publish release"
else
    fail "Should use 'gh release create'"
fi

# Check GITHUB_TOKEN is used (not a PAT)
if grep -q "GITHUB_TOKEN\|github.token" "$WF"; then
    pass "Uses built-in GITHUB_TOKEN (no custom PAT needed)"
else
    fail "Should use GITHUB_TOKEN for authentication"
fi

# Check release notes include key information
if grep -q "Debian base\|Debian 13 Trixie" "$WF"; then
    pass "Release notes mention Debian base version"
else
    fail "Release notes should mention Debian base version"
fi

# Check SHA256SUMS is uploaded
if grep -q "SHA256SUMS" "$WF"; then
    pass "SHA256SUMS file is included in release assets"
else
    fail "Should include consolidated SHA256SUMS in release"
fi

# Check all three ISOs are uploaded to release
for edition in home developer lite; do
    if grep -q "bright-os-.*-${edition}-amd64" "$WF"; then
        pass "Release includes ${edition} edition ISO"
    else
        fail "Release should include ${edition} edition ISO"
    fi
done

# Check release notes warn about boot testing status
if grep -q "not.*boot.*test\|Boot testing\|boot-tested\|untested" "$WF"; then
    pass "Release notes include boot-testing status (not claiming boot success)"
else
    fail "Release notes must disclose that boot testing is pending"
fi

echo ""
echo "--- Build log preservation ---"
# Check build log is shown on failure
if grep -q "tail.*build\.log\|build log tail\|Last 100 lines" "$WF"; then
    pass "Build log tail shown on failure for debugging"
else
    fail "Should show build log tail on failure"
fi

# Check build log is uploaded as artifact
if grep -q "build.log" "$WF" && grep -q "cp.*build.log" "$WF"; then
    pass "Build log is saved and uploaded with artifacts"
else
    fail "Build log should be saved and uploaded as artifact"
fi

echo ""
echo "--- Disk space ---"
# Check disk space is verified
if grep -q "df -h" "$WF"; then
    pass "Checks available disk space"
else
    fail "Should check disk space before building"
fi

# Check disk space cleanup is performed
if grep -q "Free disk space\|rm -rf.*android\|rm -rf.*dotnet" "$WF"; then
    pass "Frees disk space by removing unnecessary preinstalled software"
else
    fail "Should free disk space on runner before building"
fi

echo ""
echo "--- Pull request safety ---"
# Ensure the workflow does NOT run on pull requests from forks
# (The on: section should only have push (tags) and workflow_dispatch, not pull_request)
if grep -q "pull_request:" "$WF"; then
    fail "Should NOT trigger on pull requests (security risk from untrusted code)"
else
    pass "Does not trigger on pull requests (prevents untrusted code execution with secrets)"
fi

# =============================================================================

echo ""
echo "--- CI helper scripts ---"
if [ -f "build/scripts/ci/build-in-container.sh" ]; then
    pass "CI build helper script exists"
    if bash -n build/scripts/ci/build-in-container.sh 2>/dev/null; then
        pass "CI build script syntax valid"
    else
        fail "CI build script has syntax errors"
    fi
else
    fail "Missing CI build helper script (build/scripts/ci/build-in-container.sh)"
fi

if [ -f "build/scripts/ci/validate-in-container.sh" ]; then
    pass "CI validate helper script exists"
    if bash -n build/scripts/ci/validate-in-container.sh 2>/dev/null; then
        pass "CI validate script syntax valid"
    else
        fail "CI validate script has syntax errors"
    fi
else
    fail "Missing CI validate helper script (build/scripts/ci/validate-in-container.sh)"
fi

if grep -q "build/scripts/ci/build-in-container.sh" "$WF"; then
    pass "Workflow uses CI build-in-container.sh helper"
else
    fail "Workflow should use build/scripts/ci/build-in-container.sh"
fi

if grep -q "build/scripts/ci/validate-in-container.sh" "$WF"; then
    pass "Workflow uses CI validate-in-container.sh helper"
else
    fail "Workflow should use build/scripts/ci/validate-in-container.sh"
fi

# download-artifact v4 does not support merge-multiple
if ! grep -q "merge-multiple" "$WF"; then
    pass "No invalid merge-multiple option (removed for download-artifact v4)"
else
    fail "merge-multiple is not a valid option for download-artifact v4"
fi

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All workflow tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
