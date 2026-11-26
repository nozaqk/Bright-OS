#!/bin/bash
# =============================================================================
# Phase 6.2 — ISO build pipeline static checks
#
# Verifies that the GitHub Actions ISO build and release workflows reference
# existing scripts, use the correct trigger filters, and never publish
# releases from ordinary pushes or pull requests.
#
# These are STATIC checks only — they do not run lb build or boot an ISO.
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

PASS=0; FAIL=0
pass() { echo "  [PASS] $*"; PASS=$((PASS+1)); }
fail() { echo "  [FAIL] $*"; FAIL=$((FAIL+1)); }

echo "=========================================="
echo " Phase 6.2 — ISO build pipeline static checks"
echo "=========================================="
echo ""

WF_ISO=".github/workflows/iso-build.yml"
WF_REL=".github/workflows/release.yml"

echo "--- Workflow files exist and are valid YAML ---"
for f in "$WF_ISO" "$WF_REL"; do
    if [ -f "$f" ]; then pass "$f exists"; else fail "$f missing"; fi
done
python3 -c "
import yaml, sys
for p in ['$WF_ISO', '$WF_REL']:
    yaml.safe_load(open(p))
print('YAML_OK')
" && pass "Both workflows parse as valid YAML" || fail "YAML parse error in a workflow file"

echo ""
echo "--- Triggers (checked via YAML parsing) ---"
python3 - "$WF_ISO" "$WF_REL" <<'PY'
import sys, yaml
wf_iso = yaml.safe_load(open(sys.argv[1]))
wf_rel = yaml.safe_load(open(sys.argv[2]))

def check(cond, msg):
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        sys.exit(1)

on_iso = wf_iso.get(True, wf_iso.get('on', {}))
on_rel = wf_rel.get(True, wf_rel.get('on', {}))

# iso-build must run on push to the phase6-2 branch
push_branches_iso = (on_iso.get('push') or {}).get('branches', [])
check(any('phase6-2' in str(b) for b in push_branches_iso),
      "iso-build triggers on push to arena/phase6-2-iso-build")
check(bool(on_iso.get('pull_request')), "iso-build runs on pull_request")
check(bool(on_iso.get('workflow_dispatch') is not None), "iso-build supports workflow_dispatch")

# release MUST be restricted to v* tags
push_tags_rel = (on_rel.get('push') or {}).get('tags', [])
check(any('v[0-9]' in str(t) for t in push_tags_rel),
      "release.yml push trigger restricted to v* tags")
check(not on_rel.get('pull_request'),
      "release.yml does NOT trigger on pull requests")
check(not (on_rel.get('push') or {}).get('branches'),
      "release.yml does NOT trigger on branch pushes")
check(on_rel.get('workflow_dispatch') is not None,
      "release.yml supports manual workflow_dispatch")
print("YAML_TRIGGERS_OK")
PY
echo "(triggers verified above)"

echo ""
echo "--- Permissions and release safety ---"
python3 - "$WF_ISO" "$WF_REL" <<'PY'
import sys, yaml
wf_iso = yaml.safe_load(open(sys.argv[1]))
wf_rel = yaml.safe_load(open(sys.argv[2]))

def check(cond, msg):
    if cond:
        print(f"  [PASS] {msg}")
    else:
        print(f"  [FAIL] {msg}")
        sys.exit(1)

iso_perms = wf_iso.get('permissions', {})
rel_perms = wf_rel.get('permissions', {})
check(iso_perms.get('contents') == 'read', "iso-build uses contents:read (least privilege)")
check(rel_perms.get('contents') == 'write', "release uses contents:write")

# Release must be a draft
release_job = (wf_rel.get('jobs') or {}).get('build-and-release', {})
release_step = None
for s in release_job.get('steps', []):
    if s.get('uses', '').startswith('softprops/action-gh-release'):
        release_step = s
        break
check(release_step is not None, "release uses softprops/action-gh-release")
if release_step:
    with_ = release_step.get('with', {})
    check(str(with_.get('draft')).lower() == 'true', "release creates DRAFT releases")
    # Must not create tags automatically (no 'tag_name' from anything other than user tag)
    check(with_.get('tag_name') is not None, "release references the git tag_name")
print("PERMS_OK")
PY

echo ""
echo "--- Referenced build scripts and helper tools ---"
for f in \
    build/scripts/build.sh \
    build/scripts/validate-iso.sh \
    build/live-build/auto/config \
    build/live-build/auto/build \
    tools/ci/extract_manifest.py \
    tools/ci/record_build_measurement.py \
    tools/ci/record_release_measurement.py; do
    if [ -f "$f" ]; then pass "$f exists"; else fail "$f missing"; fi
done
for f in build/scripts/build.sh build/scripts/validate-iso.sh \
         build/live-build/auto/config build/live-build/auto/build; do
    if [ -x "$f" ]; then pass "$f executable"; else fail "$f not executable"; fi
done
for f in tools/ci/extract_manifest.py tools/ci/record_build_measurement.py tools/ci/record_release_measurement.py; do
    if python3 -m py_compile "$f"; then
        pass "$f compiles"
    else
        fail "$f has a Python syntax error"
    fi
done

echo ""
echo "--- Build invocation uses correct flags ---"
# Match build.sh invocation (may be preceded by sudo -E or bash -x flags).
if grep -qE "build/scripts/build\.sh" "$WF_ISO" && \
   grep -q "\-\-version" "$WF_ISO" && \
   grep -q "\-\-distro" "$WF_REL"; then
    pass "Workflows invoke build.sh with --version and --distro"
else
    fail "Workflows do not invoke build.sh correctly"
fi

echo ""
echo "--- Phase 6.3: labwc default compositor, KWin recovery ---"
if grep -q "BRIGHT_EDITION: home" "$WF_ISO" "$WF_REL"; then
    pass "CI/release default edition is 'home'"
else
    fail "Default edition is not 'home'"
fi
# Phase 6.3: labwc is default compositor in core; kwin-wayland is in
# optional-recovery-kwin profile.
if grep -q "^labwc$" config/package-lists/core.list.chroot; then
    pass "labwc is in core (default compositor, Phase 6.3)"
else
    fail "labwc not in core.list.chroot"
fi
if grep -q "^greetd$" config/package-lists/core.list.chroot; then
    pass "greetd is in core (lightweight display manager, Phase 6.3)"
else
    fail "greetd not in core.list.chroot"
fi
if grep -q "^kwin-wayland$" config/package-lists/optional-recovery-kwin.list.chroot \
   && grep -q "^sddm$" config/package-lists/optional-recovery-kwin.list.chroot; then
    pass "KWin+SDDM available via optional-recovery-kwin profile (recovery path)"
else
    fail "kwin-wayland/sddm missing from optional-recovery-kwin profile"
fi

# --- Summary ---
echo ""
echo "=========================================="
echo " Results:  $PASS passed, $FAIL failed"
echo "=========================================="
if [ "$FAIL" -gt 0 ]; then
    echo "Static checks FAILED."; exit 1
fi
echo "All Phase 6.2 ISO-pipeline static checks passed."
echo "Note: These checks validate the WORKFLOW FILES and SCRIPTS only."
echo "The actual ISO build runs in GitHub Actions after push."
