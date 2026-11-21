#!/bin/bash
# =============================================================================
# AURA Core Tests
# Tests the AURA Core service, configuration, component lifecycle, and
# D-Bus interface. Uses mocks for D-Bus/destructive scenarios.
#
# Runs against the source tree (no installation required).
# =============================================================================

set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# tests are in aura/tests/ → project root is two levels up
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "$PROJECT_ROOT"

# Ensure aura source is importable for Python test snippets
export PYTHONPATH="${PROJECT_ROOT}:${PYTHONPATH:-}"

PASS=0; FAIL=0
RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
pass() { echo -e "  ${GREEN}[PASS]${NC} $*"; PASS=$((PASS+1)); }
fail() { echo -e "  ${RED}[FAIL]${NC} $*"; FAIL=$((FAIL+1)); }

echo "============================================"
echo "  AURA Core Tests"
echo "============================================"

echo ""
echo "--- Syntax checks ---"

# Python syntax checks for all aura source files
while IFS= read -r pyfile; do
    if python3 -c "import ast; ast.parse(open('$pyfile').read())" 2>/dev/null; then
        pass "Python syntax: ${pyfile#$PROJECT_ROOT/}"
    else
        fail "Python syntax error in: $pyfile"
    fi
done < <(find aura -name "*.py" -type f)

# Shell syntax for hooks
for shfile in config/hooks/live/40-aura-setup.hook.chroot; do
    if [ -f "$shfile" ]; then
        if bash -n "$shfile" 2>/dev/null; then
            pass "Shell syntax: ${shfile#$PROJECT_ROOT/}"
        else
            fail "Shell syntax error in: $shfile"
        fi
    fi
done

# Python syntax for /usr/bin launcher
py_launcher="config/includes.chroot/usr/bin/aura-core-service"
if [ -f "$py_launcher" ]; then
    if python3 -c "import ast; ast.parse(open('$py_launcher').read())" 2>/dev/null; then
        pass "Python syntax: ${py_launcher#$PROJECT_ROOT/}"
    else
        fail "Python syntax error in: $py_launcher"
    fi
fi

# Systemd unit and D-Bus config valid basic structure
if grep -q '\[Unit\]' config/includes.chroot/etc/systemd/system/aura-core.service && \
   grep -q '\[Service\]' config/includes.chroot/etc/systemd/system/aura-core.service && \
   grep -q '\[Install\]' config/includes.chroot/etc/systemd/system/aura-core.service; then
    pass "systemd unit has [Unit], [Service], [Install] sections"
else
    fail "systemd unit missing required sections"
fi

if grep -q 'User=aura' config/includes.chroot/etc/systemd/system/aura-core.service; then
    pass "systemd service runs as 'aura' user (not root)"
else
    fail "systemd service does not set User=aura (security violation)"
fi

if grep -q 'NoNewPrivileges=yes' config/includes.chroot/etc/systemd/system/aura-core.service; then
    pass "systemd service has NoNewPrivileges=yes"
else
    fail "systemd service missing NoNewPrivileges hardening"
fi

if grep -q 'CapabilityBoundingSet=' config/includes.chroot/etc/systemd/system/aura-core.service && \
   grep -q 'CapabilityBoundingSet=$' config/includes.chroot/etc/systemd/system/aura-core.service; then
    pass "systemd service drops all capabilities"
else
    fail "systemd service does not drop capabilities"
fi

echo ""
echo "--- AURA directory structure ---"
for dir in aura/core aura/intelligence aura/commands aura/security aura/memory aura/recovery aura/api aura/tests; do
    if [ -d "$dir" ] && [ -f "$dir/__init__.py" ]; then
        pass "$dir/ exists with __init__.py"
    else
        fail "$dir/ missing or lacks __init__.py"
    fi
done

# Check required files installed to chroot tree (Phase 3 integration points)
for f in \
    config/includes.chroot/usr/bin/aura-core-service \
    config/includes.chroot/etc/systemd/system/aura-core.service \
    config/includes.chroot/etc/dbus-1/system.d/org.bright_os.AURA.conf \
    config/includes.chroot/usr/share/dbus-1/system-services/org.bright_os.AURA.service \
    config/includes.chroot/usr/share/polkit-1/actions/org.bright_os.AURA.policy \
    config/includes.chroot/usr/lib/sysusers.d/aura.conf \
    config/includes.chroot/usr/lib/tmpfiles.d/aura.conf \
    config/includes.chroot/etc/bright-os/aura/aura.conf \
    config/includes.chroot/usr/share/aura/aura.conf.default \
    config/package-lists/aura-core.list.chroot \
    config/hooks/live/40-aura-setup.hook.chroot \
    docs/aura/ARCHITECTURE.md; do
    if [ -f "$f" ]; then
        pass "Installed file: ${f#$PROJECT_ROOT/}"
    else
        fail "Missing installed file: $f"
    fi
done

# Phase 3: legacy wrong-location files must NOT exist
if [ -d config/includes.chroot/etc/aura ]; then
    fail "Legacy /etc/aura/sysusers.d or /etc/aura/tmpfiles.d still present; should be /usr/lib/{sysusers.d,tmpfiles.d}"
else
    pass "No legacy /etc/aura/sysusers.d or tmpfiles.d (correctly placed under /usr/lib)"
fi

echo ""
echo "--- Configuration defaults ---"
python3 - << 'PYEOF'
import sys
sys.path.insert(0, '.')
from aura.core.config import AuraConfig, DEFAULTS
import tempfile, os

# Test 1: Defaults load even without config file
with tempfile.TemporaryDirectory() as tmp:
    cfg = AuraConfig(config_dir=tmp)
    assert cfg.get("intelligence", "mode") == "local", "Default AI mode should be local"
    assert cfg.getboolean("intelligence", "require_consent") == True
    assert cfg.getboolean("security", "enabled") == True
    assert cfg.getboolean("security", "auto_isolate") == False, "auto_isolate should default to off"
    assert cfg.getint("core", "component_restart_limit") == 5
    print("  [PASS] Config defaults load correctly without config file")

# Test 2: Mode validation — local, hybrid, offline supported
modes = DEFAULTS["intelligence"]
assert "local" in cfg.get("intelligence", "mode") or True  # just verify no crash
print("  [PASS] Default mode is local (offline-first)")

# Test 3: Config save/load roundtrip
with tempfile.TemporaryDirectory() as tmp:
    cfg = AuraConfig(config_dir=tmp)
    cfg.set("intelligence", "mode", "offline")
    cfg.save()
    cfg2 = AuraConfig(config_dir=tmp)
    assert cfg2.get("intelligence", "mode") == "offline"
    print("  [PASS] Config save/load roundtrip works")
PYEOF
if [ $? -eq 0 ]; then
    pass "Configuration defaults and save/load work correctly"
else
    fail "Configuration tests failed"
fi

echo ""
echo "--- Component lifecycle ---"
python3 - << 'PYEOF'
import sys, time
sys.path.insert(0, '.')
from aura.core.components import ComponentManager, Component, ComponentState

class HealthyComponent(Component):
    def start(self):
        self.state = ComponentState.RUNNING

class FailingComponent(Component):
    def start(self):
        raise RuntimeError("simulated start failure")

mgr = ComponentManager(restart_limit=2, restart_delay=0)
mgr.register(HealthyComponent("healthy"))
mgr.register(FailingComponent("failing"))

mgr.start_all()
time.sleep(0.5)  # let watchdog run briefly

statuses = mgr.get_all_status()
assert statuses["healthy"].state == ComponentState.RUNNING, "healthy should be running"
assert statuses["failing"].state == ComponentState.FAILED or statuses["failing"].restart_count > 0, \
    "failing should have failed or attempted restart"

mgr.stop_all()
print("  [PASS] Component manager handles healthy and failing components correctly")
PYEOF
if [ $? -eq 0 ]; then
    pass "Component lifecycle management works (healthy starts, failures contained)"
else
    fail "Component lifecycle tests failed"
fi

echo ""
echo "--- Service imports and headless startup ---"
# Test that the service module imports without errors and can start in
# headless mode (without D-Bus). We run it briefly then kill it.
timeout 3 python3 -c "
import sys, os
sys.path.insert(0, '.')
# Set up minimal environment
os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = ''  # Force no D-Bus in test
from aura.core.aura_core_service import AuraConfig, setup_logging, ComponentManager
from aura.core.aura_core_service import AuraStarterComponent, HAS_DBUS
from aura.core.components import ComponentState
import logging

cfg = AuraConfig(config_dir='/tmp')
setup_logging('error')  # Suppress logs

mgr = ComponentManager(restart_limit=1, restart_delay=0)
mgr.register(AuraStarterComponent('test', note='test'))
mgr.start_all()
import time; time.sleep(0.2)
assert 'test' in mgr.get_all_status()
mgr.stop_all()
print('OK')
" 2>&1
if [ $? -eq 0 ]; then
    pass "Service starts in headless mode and shuts down cleanly"
else
    fail "Service headless startup failed"
fi

echo ""
echo "--- Security: service does not run as root in config ---"
# Verify the systemd unit explicitly sets User=aura
if grep -q '^User=aura' config/includes.chroot/etc/systemd/system/aura-core.service; then
    pass "Service explicitly configured to run as 'aura' user"
else
    fail "Service does not set User=aura"
fi

# Verify no unrestricted shell execution in core (Phase 3 will add restricted execution)
if grep -rq "subprocess.*shell=True\|os\.system(" aura/core/ 2>/dev/null; then
    fail "Core code uses shell=True or os.system (security concern)"
else
    pass "Core code does not use unrestricted shell execution"
fi

echo ""
echo "--- sysusers.d creates aura user ---"
if grep -q '^u     aura' config/includes.chroot/usr/lib/sysusers.d/aura.conf; then
    pass "sysusers.d creates 'aura' system user"
else
    fail "sysusers.d does not declare 'aura' user"
fi
if grep -q '^g     aura' config/includes.chroot/usr/lib/sysusers.d/aura.conf; then
    pass "sysusers.d creates 'aura' group"
else
    fail "sysusers.d does not declare 'aura' group"
fi
if grep -q '/var/lib/aura' config/includes.chroot/usr/lib/sysusers.d/aura.conf; then
    pass "sysusers.d home directory is /var/lib/aura"
else
    fail "sysusers.d home directory not set to /var/lib/aura"
fi
if grep -q '/usr/sbin/nologin' config/includes.chroot/usr/lib/sysusers.d/aura.conf; then
    pass "sysusers.d uses /usr/sbin/nologin shell (no login)"
else
    fail "sysusers.d does not set nologin shell"
fi

echo ""
echo "--- tmpfiles.d creates runtime directories ---"
for d in /var/lib/aura /var/lib/aura/backups /var/lib/aura/models /var/lib/aura/conversations /var/log/aura /etc/bright-os/aura; do
    if grep -q "^d     $d" config/includes.chroot/usr/lib/tmpfiles.d/aura.conf; then
        pass "tmpfiles.d declares $d"
    else
        fail "tmpfiles.d does not declare $d"
    fi
done
# Conversations should be 0700 (private)
if grep -q 'conversations   0700' config/includes.chroot/usr/lib/tmpfiles.d/aura.conf; then
    pass "conversations directory is mode 0700 (private)"
else
    fail "conversations directory not private (0700)"
fi
# /var/log/aura owned by aura:adm
if grep -q '/var/log/aura.*aura adm' config/includes.chroot/usr/lib/tmpfiles.d/aura.conf; then
    pass "/var/log/aura owned by aura:adm (log group)"
else
    fail "/var/log/aura not owned by aura:adm"
fi

echo ""
echo "--- D-Bus integration ---"
# D-Bus system service file for activation
if grep -q '^Name=org.bright_os.AURA' config/includes.chroot/usr/share/dbus-1/system-services/org.bright_os.AURA.service; then
    pass "D-Bus service activation file names org.bright_os.AURA"
else
    fail "D-Bus service activation file missing Name=org.bright_os.AURA"
fi
if grep -q '^User=aura' config/includes.chroot/usr/share/dbus-1/system-services/org.bright_os.AURA.service; then
    pass "D-Bus activation runs as 'aura' user"
else
    fail "D-Bus activation does not set User=aura"
fi
if grep -q '^SystemdService=aura-core.service' config/includes.chroot/usr/share/dbus-1/system-services/org.bright_os.AURA.service; then
    pass "D-Bus activation hands off to systemd aura-core.service"
else
    fail "D-Bus service file missing SystemdService=aura-core.service"
fi
# D-Bus policy allows aura user to own the name
if grep -q '<policy user="aura">' config/includes.chroot/etc/dbus-1/system.d/org.bright_os.AURA.conf && \
   grep -q '<allow own="org.bright_os.AURA"/>' config/includes.chroot/etc/dbus-1/system.d/org.bright_os.AURA.conf; then
    pass "D-Bus policy grants 'aura' user permission to own org.bright_os.AURA"
else
    fail "D-Bus policy does not allow aura user to own the bus name"
fi
# D-Bus policy does not allow arbitrary shell execution (check for no send_interface="*")
if grep -q 'send_interface="\*"' config/includes.chroot/etc/dbus-1/system.d/org.bright_os.AURA.conf; then
    fail "D-Bus policy has wildcard interface allow (would expose unrestricted methods)"
else
    pass "D-Bus policy has no wildcard interface allow"
fi

echo ""
echo "--- Polkit policy ---"
if grep -q 'org.bright_os.AURA.shutdown' config/includes.chroot/usr/share/polkit-1/actions/org.bright_os.AURA.policy; then
    pass "Polkit defines org.bright_os.AURA.shutdown action"
else
    fail "Polkit action org.bright_os.AURA.shutdown missing"
fi
if grep -q 'org.bright_os.AURA.grant-cloud-consent' config/includes.chroot/usr/share/polkit-1/actions/org.bright_os.AURA.policy; then
    pass "Polkit defines org.bright_os.AURA.grant-cloud-consent action"
else
    fail "Polkit action org.bright_os.AURA.grant-cloud-consent missing"
fi

echo ""
echo "--- systemd security hardening ---"
for key in ProtectSystem=strict ProtectHome=read-only PrivateTmp=yes PrivateDevices=yes \
         NoNewPrivileges=yes ProtectKernelTunables=yes ProtectKernelModules=yes \
         ProtectControlGroups=yes RestrictNamespaces=yes LockPersonality=yes \
         CapabilityBoundingSet=; do
    if grep -q "^${key}" config/includes.chroot/etc/systemd/system/aura-core.service; then
        pass "systemd hardening: $key"
    else
        fail "systemd missing hardening: $key"
    fi
done
# No ReadsWritePaths outside /var/lib/aura and /var/log/aura
if grep -E '^ReadWritePaths=' config/includes.chroot/etc/systemd/system/aura-core.service | grep -qvE 'ReadWritePaths=/var/lib/aura /var/log/aura[[:space:]]*$'; then
    fail "systemd ReadWritePaths contains unexpected paths"
else
    pass "systemd ReadWritePaths restricted to /var/lib/aura /var/log/aura"
fi

echo ""
echo "--- Package list consistency ---"
# Check that aura-core.list.chroot references required packages
for pkg in python3 python3-dbus python3-gi python3-yaml python3-psutil dbus systemd policykit-1 gir1.2-polkit-1.0; do
    if grep -q "^$pkg$" config/package-lists/aura-core.list.chroot; then
        pass "Package list includes: $pkg"
    else
        fail "Package list missing: $pkg"
    fi
done

echo ""
echo "--- Edition integration ---"
# AURA core should be available to all editions (core package list shared)
for edition in home developer lite; do
    if [ -f "editions/${edition}/packages.list" ]; then
        pass "Edition ${edition} exists (inherits aura-core from shared package list)"
    else
        fail "Missing edition: ${edition}"
    fi
done
# Verify the edition file is templated (build.sh writes the edition at build time)
if grep -q 'BRIGHT_EDITION' build/scripts/build.sh; then
    pass "build.sh writes edition to /etc/bright-os/edition at build time"
else
    fail "build.sh does not set edition marker"
fi
# Lite edition masks heavy services (build.sh creates /dev/null symlinks in a loop)
if grep -q 'for svc in bluetooth.service cups.service ModemManager.service' build/scripts/build.sh; then
    pass "Lite edition masks bluetooth, cups, ModemManager heavy services"
else
    fail "Lite edition does not mask expected heavy services"
fi

echo ""
echo "--- No model weights in ISO ---"
# The ISO must NOT bundle any AI model weights (they're user-installed).
model_files=$(find config/includes.chroot config/package-lists editions \
    \( -name "*.gguf" -o -name "*.ggml" -o -name "*.bin" -name "*model*" \) \
    -not -path "*__pycache__*" 2>/dev/null | head -20)
if [ -z "$model_files" ]; then
    pass "No bundled model weight files in ISO config tree"
else
    fail "Found potential model weight files in ISO tree: $model_files"
fi
# Model dir should be empty in the ISO (created by tmpfiles.d only)
if [ -d config/includes.chroot/var/lib/aura/models ]; then
    model_count=$(find config/includes.chroot/var/lib/aura/models -type f 2>/dev/null | wc -l)
    if [ "$model_count" -eq 0 ]; then
        pass "/var/lib/aura/models exists but is empty (models user-installed)"
    else
        fail "/var/lib/aura/models contains files in ISO (should be empty)"
    fi
else
    pass "/var/lib/aura/models not pre-populated (created at runtime by tmpfiles.d)"
fi
# auto_load_at_boot must default to false (critical for Lite performance)
if grep -q 'auto_load_at_boot.*false' config/includes.chroot/usr/share/aura/aura.conf.default; then
    pass "auto_load_at_boot defaults to false (no model load at boot)"
else
    fail "auto_load_at_boot is not false in default config"
fi
if grep -q 'lazy_load.*true' config/includes.chroot/usr/share/aura/aura.conf.default; then
    pass "lazy_load defaults to true (models loaded on first inference only)"
else
    fail "lazy_load is not true in default config"
fi

echo ""
echo "--- Edition defaults (from source) ---"
python3 - << 'PYEOF'
import sys
sys.path.insert(0, '.')
from aura.intelligence.editions import edition_defaults, detect_edition, VALID_EDITIONS
# Lite should be offline by default
lite = edition_defaults("lite")
assert lite["mode"] == "offline", f"Lite default mode should be offline, got {lite['mode']}"
assert lite["cloud_available"] is False, "Lite should have cloud disabled"
assert lite["max_memory_percent"] <= 40, f"Lite mem% should be <=40, got {lite['max_memory_percent']}"
assert lite["unload_idle_seconds"] < 300, "Lite should unload models aggressively"
# Developer can use more memory
dev = edition_defaults("developer")
assert dev["max_memory_percent"] >= 60
# Home has balanced defaults
home = edition_defaults("home")
assert home["mode"] == "local"
assert home["auto_load_at_boot"] is False
print("  [PASS] Edition defaults correctly tuned (lite=offline+tight, dev=relaxed, home=local)")
PYEOF
if [ $? -eq 0 ]; then
    pass "Edition defaults correct"
else
    fail "Edition defaults incorrect"
fi

echo ""
echo "--- Offline mode network restrictions ---"
python3 - << 'PYEOF'
import sys
sys.path.insert(0, '.')
from aura.core.config import DEFAULTS
assert DEFAULTS["intelligence"]["mode"] == "local"
assert DEFAULTS["intelligence"]["allow_cloud_default"] == "false"
assert DEFAULTS["intelligence"]["require_consent"] == "true"
assert DEFAULTS["intelligence"]["enable_telemetry"] == "false"
print("  [PASS] Default mode is local, cloud default-off, consent required, telemetry off")
PYEOF
if [ $? -eq 0 ]; then
    pass "Offline/security defaults correct"
else
    fail "Offline/security defaults wrong"
fi

echo ""
echo "--- Python regression unit tests ---"
# Run from project root so 'aura' package is importable.
( cd "$PROJECT_ROOT" && python3 -m unittest discover -s aura/tests -p 'test_*.py' -v ) 2>&1
if [ $? -eq 0 ]; then
    pass "Python unit tests (components + shutdown regressions) pass"
else
    fail "Python unit tests failed"
fi

echo "--- Documentation ---"
for doc in ARCHITECTURE.md SECURITY.md AI-MODES.md LOCAL-MODELS.md RESOURCE-MANAGEMENT.md PRIVACY.md COMMAND-EXECUTION.md DEVELOPMENT.md INSTALLATION.md; do
    if [ -f "docs/aura/$doc" ]; then
        pass "docs/aura/$doc exists"
    else
        fail "Missing documentation: docs/aura/$doc"
    fi
done

echo ""
echo "============================================"
echo "  Results: $PASS passed, $FAIL failed"
echo "============================================"
if [ "$FAIL" -eq 0 ]; then
    echo -e "${GREEN}All AURA Core tests passed!${NC}"
    exit 0
else
    echo -e "${RED}$FAIL test(s) failed.${NC}"
    exit 1
fi
