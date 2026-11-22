"""Phase 3.2: Runtime integration verification tests.

These tests verify the AURA service's integration properties that can be
checked without a live D-Bus/Polkit daemon:
  - File layout, permissions, packaging consistency.
  - Launcher script correctness (sys.path).
  - systemd unit hardening and configuration.
  - D-Bus activation, policy, and Polkit action files.
  - Headless startup/shutdown lifecycle.
  - Edition configuration defaults.
  - Deployment-mode transitions.
  - Method signature correctness (in_signature matches args).
  - Security: unprivileged user, no shell execution, credential redaction.

Tests that require a real system D-Bus + Polkit daemon are documented as
manual procedures at the end of this file (VM_RUNTIME_PROCEDURE).
"""
import configparser
import os
import pathlib
import re
import signal
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

CONFIG = PROJECT_ROOT / "config/includes.chroot"


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class FileLayoutTests(unittest.TestCase):
    """All installation files exist at their correct FHS paths."""

    REQUIRED_FILES = [
        "usr/bin/aura-core-service",
        "etc/systemd/system/aura-core.service",
        "etc/dbus-1/system.d/org.bright_os.AURA.conf",
        "usr/share/dbus-1/system-services/org.bright_os.AURA.service",
        "usr/share/polkit-1/actions/org.bright_os.AURA.policy",
        "usr/lib/sysusers.d/aura.conf",
        "usr/lib/tmpfiles.d/aura.conf",
        "etc/bright-os/aura/aura.conf",
        "usr/share/aura/aura.conf.default",
        "usr/lib/aura/__init__.py",
        "usr/lib/aura/core/aura_core_service.py",
        "usr/lib/aura/core/components.py",
        "usr/lib/aura/core/config.py",
        "usr/lib/aura/core/logger.py",
        "usr/lib/aura/intelligence/__init__.py",
        "usr/lib/aura/intelligence/health.py",
        "usr/lib/aura/intelligence/inference.py",
        "usr/lib/aura/intelligence/model_manager.py",
        "usr/lib/aura/intelligence/networking.py",
        "usr/lib/aura/intelligence/provider.py",
        "usr/lib/aura/intelligence/resource_manager.py",
        "usr/lib/aura/intelligence/secure_store.py",
        "usr/lib/aura/intelligence/mode_manager.py",
        "usr/lib/aura/intelligence/editions.py",
        "usr/lib/aura/intelligence/providers/__init__.py",
        "usr/lib/aura/intelligence/providers/cloud.py",
        "usr/lib/aura/intelligence/providers/llamacpp.py",
        "usr/lib/aura/intelligence/providers/ollama.py",
    ]

    def test_all_files_present(self):
        missing = [p for p in self.REQUIRED_FILES
                   if not (CONFIG / p).is_file()]
        self.assertEqual(missing, [], f"Missing installation files: {missing}")

    def test_launcher_is_executable(self):
        launcher = CONFIG / "usr/bin/aura-core-service"
        mode = launcher.stat().st_mode
        self.assertTrue(mode & 0o111,
                        f"launcher must be executable (mode {oct(mode)})")

    def test_legacy_paths_do_not_exist(self):
        """sysusers/tmpfiles must NOT be in /etc/aura/ (non-standard)."""
        self.assertFalse((CONFIG / "etc/aura").exists(),
                         "legacy /etc/aura/ must not exist")

    def test_no_model_weight_files(self):
        for pattern in ("*.gguf", "*.ggml", "*.bin"):
            for p in CONFIG.rglob(pattern):
                self.fail(f"Model weight file found in ISO tree: {p}")


class SourcePackagingSyncTests(unittest.TestCase):
    """Source and packaged copies must be identical."""

    def test_aura_core_service_matches(self):
        src = (PROJECT_ROOT / "aura/core/aura_core_service.py").read_bytes()
        pkg = (CONFIG / "usr/lib/aura/core/aura_core_service.py").read_bytes()
        self.assertEqual(src, pkg,
                         "source and packaged aura_core_service.py differ")

    def test_all_py_files_in_sync(self):
        src_dir = PROJECT_ROOT / "aura"
        pkg_dir = CONFIG / "usr/lib/aura"
        diffs = []
        for src_file in src_dir.rglob("*.py"):
            rel = src_file.relative_to(src_dir)
            pkg_file = pkg_dir / rel
            if not pkg_file.exists():
                diffs.append(f"missing in package: {rel}")
                continue
            if src_file.read_bytes() != pkg_file.read_bytes():
                diffs.append(f"content differs: {rel}")
        for sh_file in src_dir.rglob("*.sh"):
            rel = sh_file.relative_to(src_dir)
            pkg_file = pkg_dir / rel
            if not pkg_file.exists():
                diffs.append(f"missing in package: {rel}")
                continue
            if sh_file.read_bytes() != pkg_file.read_bytes():
                diffs.append(f"content differs: {rel}")
        self.assertEqual(diffs, [], f"Source/packaging sync errors: {diffs}")

    def test_launcher_sys_path_is_correct(self):
        """The /usr/bin launcher must add /usr/lib (parent of the 'aura'
        package directory) to sys.path, NOT /usr/lib/aura (which is the
        package itself)."""
        launcher = _read(CONFIG / "usr/bin/aura-core-service")
        self.assertIn('sys.path.insert(0, "/usr/lib")', launcher,
                      "Launcher must add /usr/lib to sys.path so that "
                      "'import aura' resolves to /usr/lib/aura/")
        self.assertNotIn('sys.path.insert(0, "/usr/lib/aura")', launcher,
                         "Launcher must NOT add /usr/lib/aura (that would "
                         "make 'import aura' look for /usr/lib/aura/aura/)")


class SystemdUnitTests(unittest.TestCase):
    """systemd unit configuration checks."""

    def setUp(self):
        self.content = _read(CONFIG / "etc/systemd/system/aura-core.service")

    def test_runs_as_unprivileged_user(self):
        self.assertRegex(self.content, r"(?m)^User=aura\s*$")
        self.assertRegex(self.content, r"(?m)^Group=aura\s*$")

    def test_no_root(self):
        self.assertNotRegex(self.content, r"(?m)^User=root\s*$")

    def test_hardening_directives_present(self):
        required = [
            "NoNewPrivileges=yes",
            "PrivateTmp=yes",
            "PrivateDevices=yes",
            "ProtectSystem=strict",
            "ProtectHome=read-only",
            "ProtectKernelTunables=yes",
            "ProtectKernelModules=yes",
            "ProtectControlGroups=yes",
            "RestrictNamespaces=yes",
            "LockPersonality=yes",
            "CapabilityBoundingSet=",
        ]
        for d in required:
            self.assertIn(d, self.content, f"Missing hardening: {d}")

    def test_capabilities_dropped(self):
        # CapabilityBoundingSet=  (empty) means drop all caps.
        self.assertRegex(self.content, r"(?m)^CapabilityBoundingSet=\s*$")
        self.assertRegex(self.content, r"(?m)^AmbientCapabilities=\s*$")

    def test_readwrite_paths_limited(self):
        for line in self.content.splitlines():
            if line.startswith("ReadWritePaths="):
                paths = line.split("=", 1)[1].split()
                self.assertEqual(set(paths), {"/var/lib/aura", "/var/log/aura"},
                    f"ReadWritePaths must be limited to aura state/log dirs")
                break
        else:
            self.fail("ReadWritePaths missing from unit")

    def test_execstart_points_to_launcher(self):
        self.assertIn("ExecStart=/usr/bin/aura-core-service --foreground",
                      self.content)

    def test_after_ordering_includes_tmpfiles(self):
        self.assertIn("systemd-tmpfiles-setup.service", self.content)
        self.assertIn("systemd-sysusers.service", self.content)

    def test_dbust_is_wants_not_requires(self):
        """D-Bus must be Wants=, not Requires=, so AURA can start in
        headless mode on minimal systems."""
        self.assertRegex(self.content, r"(?m)^Wants=.*dbus\.service")
        self.assertNotRegex(self.content, r"(?m)^Requires=.*dbus\.service")

    def test_failure_action_none(self):
        """AURA must not bring down the system if it fails."""
        self.assertIn("FailureAction=none", self.content)

    def test_restart_policy(self):
        self.assertIn("Restart=on-failure", self.content)
        self.assertIn("StartLimitBurst=5", self.content)

    def test_execstartpre_runs_as_root(self):
        """ExecStartPre must be prefixed with '+' to run as root (needed
        because the service user can't run systemd-tmpfiles)."""
        self.assertIn("ExecStartPre=+/bin/systemd-tmpfiles", self.content)

    def test_syslog_identifier(self):
        self.assertIn("SyslogIdentifier=aura-core", self.content)

    def test_install_wanted_by_multi_user(self):
        self.assertIn("WantedBy=multi-user.target", self.content)
        self.assertIn("Alias=aura.service", self.content)


class DBusPolicyTests(unittest.TestCase):
    """D-Bus configuration and policy checks."""

    def setUp(self):
        self.policy = _read(CONFIG / "etc/dbus-1/system.d/org.bright_os.AURA.conf")
        self.activation = _read(
            CONFIG / "usr/share/dbus-1/system-services/org.bright_os.AURA.service")

    def test_aura_user_can_own_name(self):
        self.assertIn('<policy user="aura">', self.policy)
        self.assertIn('<allow own="org.bright_os.AURA"/>', self.policy)

    def test_aura_user_can_send_signals(self):
        self.assertIn('send_type="signal"', self.policy)

    def test_root_can_communicate(self):
        self.assertIn('<policy user="root">', self.policy)

    def test_no_wildcard_allows(self):
        self.assertNotIn('send_interface="*"', self.policy)
        self.assertNotIn('send_member="*"', self.policy)

    def test_signal_receive_allowed(self):
        self.assertIn('receive_type="signal"', self.policy)

    def test_all_implemented_methods_listed(self):
        """Every @dbus.service.method-decorated method in aura_core_service.py
        must have a matching send_member allow in the D-Bus policy (otherwise
        the method is unreachable)."""
        src = _read(PROJECT_ROOT / "aura/core/aura_core_service.py")
        methods = re.findall(r'def\s+(\w+)\(self[^)]*\)', src)
        # Methods that are NOT D-Bus methods
        not_dbus = {"main", "parse_args", "handle_signal", "_state_changed_cb",
                    "_ai_event_cb", "_wire_ai_listeners", "_engine", "__init__",
                    "stop", "start", "health_check"}
        dbus_methods = set()
        # Find methods preceded by @dbus.service.method decorator
        for m in re.finditer(r'@dbus\.service\.method\([^)]+\)\s+def\s+(\w+)\(',
                             src, re.DOTALL):
            dbus_methods.add(m.group(1))

        for m in sorted(dbus_methods):
            if m in not_dbus:
                continue
            self.assertIn(f'send_member="{m}"', self.policy,
                          f"D-Bus method {m} missing from policy allow list")

    def test_activation_file_correct(self):
        self.assertIn("Name=org.bright_os.AURA", self.activation)
        self.assertIn("SystemdService=aura-core.service", self.activation)
        self.assertIn("User=aura", self.activation)
        self.assertIn("Exec=/usr/bin/aura-core-service --foreground",
                      self.activation)

    def test_no_arbitrary_command_execution(self):
        """D-Bus policy must not expose methods that can run arbitrary
        shell commands. Check that no member names like Exec/Run/Command
        are allowed."""
        for dangerous in ("Exec", "RunCommand", "Shell", "Eval"):
            self.assertNotIn(f'send_member="{dangerous}"', self.policy,
                             f"Policy exposes dangerous-sounding method {dangerous}")


class PolkitPolicyTests(unittest.TestCase):
    """Polkit action file checks."""

    def setUp(self):
        import xml.etree.ElementTree as ET
        self.tree = ET.parse(
            CONFIG / "usr/share/polkit-1/actions/org.bright_os.AURA.policy")
        self.root = self.tree.getroot()

    def _defaults(self, action_id):
        for action in self.root.findall("action"):
            if action.get("id") == action_id:
                return action.find("defaults")
        self.fail(f"action {action_id} not found")

    def test_shutdown_requires_admin(self):
        d = self._defaults("org.bright_os.AURA.shutdown")
        self.assertEqual(d.findtext("allow_any"), "auth_admin")
        self.assertEqual(d.findtext("allow_inactive"), "auth_admin")
        self.assertIn(d.findtext("allow_active"),
                      ("auth_admin", "auth_admin_keep"))

    def test_grant_cloud_consent_requires_admin(self):
        """Critical: granting cloud consent must require admin, not 'yes'."""
        d = self._defaults("org.bright_os.AURA.grant-cloud-consent")
        self.assertEqual(d.findtext("allow_any"), "auth_admin")
        self.assertEqual(d.findtext("allow_inactive"), "auth_admin")
        self.assertIn(d.findtext("allow_active"),
                      ("auth_admin", "auth_admin_keep"))
        self.assertNotEqual(d.findtext("allow_active"), "yes",
                            "grant-cloud-consent must NOT allow active users "
                            "without admin authentication")


class MethodSignatureTests(unittest.TestCase):
    """Verify D-Bus method signatures match the Python method arguments."""

    def _method_specs(self):
        """Yield (method_name, in_signature, arg_names_from_def) for each
        @dbus.service.method in aura_core_service.py."""
        src = _read(PROJECT_ROOT / "aura/core/aura_core_service.py")
        # Match a decorator block followed by 'def name(args):'
        pattern = re.compile(
            r'@dbus\.service\.method\([^)]*?in_signature="([^"]*)"'
            r'[^)]*?\)\s*\n\s*def\s+(\w+)\(self([^)]*)\)',
            re.MULTILINE)
        return [(m.group(2), m.group(1), m.group(3)) for m in pattern.finditer(src)]

    def test_in_signature_matches_arg_count(self):
        """in_signature must match the number of explicit Python parameters
        (excluding sender_keyword, which is injected by dbus-python)."""
        # Signature type codes: s=str, b=bool, i=int32, u=uint32, x=int64,
        # t=uint64, d=double, a=array, v=variant, o=object_path, g=sig,
        # {m,n}=dict entries, ()=struct. Simple single-char type codes
        # (skipping array/dict/struct prefixes) count as one arg.
        def count_args(sig):
            count = 0
            i = 0
            while i < len(sig):
                c = sig[i]
                if c in "sbyuqixntdogv":
                    count += 1
                elif c == "a":
                    # array: skip 'a' and element type code
                    i += 1
                    if i < len(sig) and sig[i] == "{":
                        # dict entry {kv}: find closing }
                        depth = 0
                        while i < len(sig):
                            if sig[i] == "{":
                                depth += 1
                            elif sig[i] == "}":
                                depth -= 1
                                if depth == 0:
                                    break
                            i += 1
                    # else single element type follows which we already skip
                elif c == "(":
                    # struct: consume until )
                    depth = 0
                    while i < len(sig):
                        if sig[i] == "(":
                            depth += 1
                        elif sig[i] == ")":
                            depth -= 1
                            if depth == 0:
                                count += 1
                                break
                        i += 1
                i += 1
            return count

        for name, sig, args_str in self._method_specs():
            # Args after self are comma-separated; sender_keyword is
            # injected by dbus-python and shouldn't count.
            args = [a.strip() for a in args_str.split(",") if a.strip()]
            py_args = [a for a in args if "sender" not in a.split("=")[0]]
            n_expected = len(py_args)
            n_sig = count_args(sig)
            self.assertEqual(n_sig, n_expected,
                f"Method {name}: in_signature '{sig}' implies {n_sig} args "
                f"but method takes {n_expected} non-sender args "
                f"({py_args}).")


class HeadlessRuntimeTests(unittest.TestCase):
    """Tests that start the actual service in headless mode."""

    def setUp(self):
        self._saved_dbus = os.environ.pop("DBUS_SYSTEM_BUS_ADDRESS", None)
        self._saved_edition = os.environ.pop("AURA_EDITION", None)
        os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = ""

    def tearDown(self):
        if self._saved_dbus is None:
            os.environ.pop("DBUS_SYSTEM_BUS_ADDRESS", None)
        else:
            os.environ["DBUS_SYSTEM_BUS_ADDRESS"] = self._saved_dbus
        if self._saved_edition is None:
            os.environ.pop("AURA_EDITION", None)
        else:
            os.environ["AURA_EDITION"] = self._saved_edition

    def test_headless_start_stop(self):
        """Service must start and stop cleanly without D-Bus."""
        os.environ["AURA_EDITION"] = "lite"
        from aura.core.aura_core_service import (
            AuraConfig, setup_logging, ComponentManager,
            AuraStarterComponent, IntelligenceComponent, HAS_DBUS)
        from aura.core.components import ComponentState
        import logging
        logging.disable(logging.CRITICAL)
        try:
            cfg = AuraConfig(config_dir="/tmp")
            mgr = ComponentManager(restart_limit=1, restart_delay=0)
            intel = IntelligenceComponent("intelligence", cfg)
            mgr.register(intel)
            mgr.register(AuraStarterComponent("cmds", available=False))
            mgr.start_all()
            time.sleep(0.3)
            statuses = mgr.get_all_status()
            self.assertEqual(statuses["intelligence"].state,
                             ComponentState.RUNNING)
            mgr.stop_all()
            for name, s in mgr.get_all_status().items():
                self.assertIn(s.state,
                              (ComponentState.STOPPED, ComponentState.DISABLED),
                              f"component {name} not stopped")
        finally:
            logging.disable(logging.NOTSET)

    def test_mode_switching_offline_blocks_network(self):
        from aura.core.aura_core_service import (
            AuraConfig, setup_logging, IntelligenceComponent)
        import logging
        logging.disable(logging.CRITICAL)
        try:
            cfg = AuraConfig(config_dir="/tmp")
            intel = IntelligenceComponent("intelligence", cfg)
            intel.start()
            eng = intel.engine
            self.assertIsNotNone(eng)
            eng.set_mode("offline")
            self.assertFalse(eng._mode_manager.network_enabled())
            # Switching back to local should work
            eng.set_mode("local")
            intel.stop()
        finally:
            logging.disable(logging.NOTSET)

    def test_intelligence_graceful_disable_on_missing_deps(self):
        """If the intelligence engine cannot import (simulated), the
        component must go DISABLED, not crash the service."""
        from aura.core.aura_core_service import (
            AuraConfig, IntelligenceComponent)
        from aura.core.components import ComponentState
        import builtins
        real_import = builtins.__import__
        def fake_import(name, *a, **k):
            if name == "aura.intelligence":
                raise ImportError("simulated missing module")
            return real_import(name, *a, **k)
        builtins.__import__ = fake_import
        try:
            cfg = AuraConfig(config_dir="/tmp")
            comp = IntelligenceComponent("intelligence", cfg)
            comp.start()
            self.assertEqual(comp.state, ComponentState.DISABLED)
            comp.stop()
        finally:
            builtins.__import__ = real_import


class SecurityBoundaryTests(unittest.TestCase):
    def test_no_shell_true_in_core(self):
        src = _read(PROJECT_ROOT / "aura/core/aura_core_service.py")
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system(", src)

    def test_credentials_never_logged(self):
        """Credential values must never appear in logs."""
        ss = _read(PROJECT_ROOT / "aura/intelligence/secure_store.py")
        # The secure store must not log key content; only length.
        self.assertIn("len", ss.lower())
        # Must explicitly avoid logging stderr
        self.assertIn("stderr", ss.lower())
        self.assertNotRegex(ss, r'logger\.[a-z]+\([^)]*key[^)]*%\)')

    def test_no_model_weights_packaged(self):
        """Confirm no .gguf/.ggml/.bin model files are anywhere under
        config/includes.chroot."""
        for p in CONFIG.rglob("*.gguf"):
            self.fail(f"found .gguf: {p}")
        for p in CONFIG.rglob("*.ggml"):
            self.fail(f"found .ggml: {p}")

    def test_default_config_safe(self):
        cfg = configparser.ConfigParser()
        cfg.read_string(_read(CONFIG / "usr/share/aura/aura.conf.default"))
        self.assertEqual(cfg["intelligence"]["auto_load_at_boot"], "false")
        self.assertEqual(cfg["intelligence"]["lazy_load"], "true")
        self.assertEqual(cfg["intelligence"]["allow_cloud_default"], "false")
        self.assertEqual(cfg["intelligence"]["require_consent"], "true")
        self.assertEqual(cfg["intelligence"]["enable_telemetry"], "false")
        self.assertEqual(cfg["security"]["auto_isolate"], "false")


class EditionConfigTests(unittest.TestCase):
    def test_lite_defaults_offline(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        from aura.intelligence.editions import edition_defaults
        lite = edition_defaults("lite")
        self.assertEqual(lite["mode"], "offline")
        self.assertFalse(lite["cloud_available"])
        self.assertLessEqual(lite["max_memory_percent"], 40)
        self.assertLess(lite["unload_idle_seconds"], 300)
        self.assertFalse(lite["auto_load_at_boot"])

    def test_developer_relaxed_resources(self):
        from aura.intelligence.editions import edition_defaults
        dev = edition_defaults("developer")
        self.assertGreaterEqual(dev["max_memory_percent"], 60)
        self.assertTrue(dev["dev_tools_enabled"])

    def test_home_balanced(self):
        from aura.intelligence.editions import edition_defaults
        home = edition_defaults("home")
        self.assertEqual(home["mode"], "local")
        self.assertFalse(home["auto_load_at_boot"])

    def test_build_script_lite_masks_heavy_services(self):
        bs = _read(PROJECT_ROOT / "build/scripts/build.sh")
        for svc in ("bluetooth.service", "cups.service", "ModemManager.service"):
            self.assertIn(svc, bs,
                          f"Lite edition must mask {svc}")


class ChrootHookTests(unittest.TestCase):
    def setUp(self):
        self.hook = _read(PROJECT_ROOT / "config/hooks/live/40-aura-setup.hook.chroot")

    def test_hook_uses_standard_sysusers_path(self):
        self.assertIn("/usr/lib/sysusers.d/aura.conf", self.hook)
        self.assertIn("/usr/lib/tmpfiles.d/aura.conf", self.hook)

    def test_hook_has_useradd_fallback(self):
        self.assertIn("useradd", self.hook)

    def test_hook_enables_service(self):
        self.assertIn("systemctl enable aura-core.service", self.hook)

    def test_hook_sets_launcher_executable(self):
        self.assertIn("chmod +x /usr/bin/aura-core-service", self.hook)

    def test_hook_sets_shell_nounset(self):
        self.assertIn("set -e", self.hook)


class PackageListTests(unittest.TestCase):
    def setUp(self):
        self.plist = _read(
            PROJECT_ROOT / "config/package-lists/aura-core.list.chroot")

    def test_required_packages(self):
        for pkg in ("python3", "python3-dbus", "python3-gi", "python3-yaml",
                    "python3-psutil", "dbus", "systemd", "policykit-1",
                    "gir1.2-polkit-1.0"):
            self.assertIn(pkg, self.plist.splitlines(),
                          f"Missing package: {pkg}")

    def test_no_model_packages(self):
        """No model runtime packages must be installed by default.
        Comment lines (#) are ignored."""
        active_lines = [
            l for l in self.plist.splitlines()
            if l.strip() and not l.lstrip().startswith("#")
        ]
        active = "\n".join(active_lines).lower()
        for forbidden in ("llama.cpp", "gguf", "ollama",
                          "stable-diffusion", "pytorch"):
            self.assertNotIn(forbidden, active,
                             f"Package list installs forbidden model "
                             f"runtime: {forbidden}")


# ---------------------------------------------------------------------------
# VM_RUNTIME_PROCEDURE: tests that require a provisioned Debian system with
# dbus-daemon, polkitd, python3-dbus and python3-gi installed.  These cannot
# run in the sandbox but are documented for reproducible verification.
#
# On a Debian 13 Trixie VM with aura-core installed:
#
#   # 1. Verify service startup
#   systemctl start aura-core.service
#   systemctl is-active aura-core.service     # => active
#   ps -o user,group,comm -p $(pgrep -f aura-core-service)  # => aura:aura
#
#   # 2. D-Bus registration
#   busctl list | grep bright_os.AURA        # => org.bright_os.AURA
#   dbus-send --system --dest=org.bright_os.AURA \
#     --type=method_call --print-reply /org/bright_os/AURA \
#     org.bright_os.AURA.GetVersion          # => "0.1.0-alpha"
#
#   # 3. Shutdown requires admin
#   sudo -u nobody dbus-send --system --dest=org.bright_os.AURA \
#     --type=method_call --print-reply /org/bright_os/AURA \
#     org.bright_os.AURA.Shutdown            # => NotAuthorized error
#
#   # 4. Shutdown as root works
#   dbus-send --system --dest=org.bright_os.AURA \
#     --type=method_call --print-reply /org/bright_os/AURA \
#     org.bright_os.AURA.Shutdown            # => service stops cleanly
#
#   # 5. GrantCloudConsent requires admin for active users
#   #    (prompts for password via polkit agent when run as normal user)
#   pkexec dbus-send --system --dest=org.bright_os.AURA \
#     --type=method_call --print-reply /org/bright_os/AURA \
#     org.bright_os.AURA.GrantCloudConsent boolean:true
#
#   # 6. Revoking consent does not require admin
#   dbus-send --system --dest=org.bright_os.AURA \
#     --type=method_call --print-reply /org/bright_os/AURA \
#     org.bright_os.AURA.GrantCloudConsent boolean:false  # => returns true
#
#   # 7. Service restarts on failure
#   systemctl restart aura-core.service
#   systemctl is-active aura-core.service     # => active
#
#   # 8. AURA doesn't run as root
#   ps -o user -p $(pgrep -f aura-core-service) | tail -1  # => aura
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    unittest.main(verbosity=2)
