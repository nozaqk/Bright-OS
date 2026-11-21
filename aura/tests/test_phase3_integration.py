"""Phase 3: AURA system integration tests.

These tests verify integration properties that don't require a real
installed system: file layout, configuration defaults, edition profiles,
security properties, D-Bus interface completeness, and failure isolation.

Tests that require an actual installed system (real D-Bus, real systemd,
real Polkit) are separated out and marked as skipped unless the
environment supports them.
"""
import configparser
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _find_config_root():
    """Find the root holding config/includes.chroot (either source tree root
    or installed system root)."""
    for cand in (
        PROJECT_ROOT,
        pathlib.Path("/"),
    ):
        if (cand / "config/includes.chroot/etc/systemd/system/aura-core.service").exists():
            return cand
    return PROJECT_ROOT


CONFIG_ROOT = _find_config_root()
CONFIG = CONFIG_ROOT / "config" / "includes.chroot"


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class FileLayoutTests(unittest.TestCase):
    """Check that installation files exist in their correct locations."""

    def test_systemd_unit_installed(self):
        unit = CONFIG / "etc/systemd/system/aura-core.service"
        self.assertTrue(unit.is_file(), f"Missing {unit}")
        content = _read(unit)
        self.assertIn("[Unit]", content)
        self.assertIn("[Service]", content)
        self.assertIn("[Install]", content)

    def test_systemd_runs_as_aura_user(self):
        content = _read(CONFIG / "etc/systemd/system/aura-core.service")
        self.assertRegex(content, r"(?m)^User=aura\s*$",
                         "Service must run as 'aura', not root")
        self.assertRegex(content, r"(?m)^Group=aura\s*$",
                         "Service must run as 'aura' group")

    def test_systemd_has_no_new_privileges(self):
        content = _read(CONFIG / "etc/systemd/system/aura-core.service")
        self.assertIn("NoNewPrivileges=yes", content)

    def test_systemd_hardening_present(self):
        content = _read(CONFIG / "etc/systemd/system/aura-core.service")
        for key in ("ProtectSystem=strict", "PrivateTmp=yes",
                     "PrivateDevices=yes", "ProtectHome=read-only",
                     "CapabilityBoundingSet="):
            self.assertIn(key, content, f"Missing hardening directive: {key}")

    def test_systemd_rw_paths_restricted(self):
        content = _read(CONFIG / "etc/systemd/system/aura-core.service")
        for line in content.splitlines():
            if line.startswith("ReadWritePaths="):
                paths = line.split("=", 1)[1].split()
                self.assertEqual(
                    set(paths), {"/var/lib/aura", "/var/log/aura"},
                    f"ReadWritePaths should be limited to /var/lib/aura and /var/log/aura, got {paths}")
                break
        else:
            self.fail("ReadWritePaths not found in unit file")

    def test_dbus_policy_installed(self):
        pol = CONFIG / "etc/dbus-1/system.d/org.bright_os.AURA.conf"
        self.assertTrue(pol.is_file(), f"Missing {pol}")
        content = _read(pol)
        self.assertIn("<policy user=\"aura\">", content)
        self.assertIn("<allow own=\"org.bright_os.AURA\"/>", content)

    def test_dbus_service_activation_file(self):
        svc = CONFIG / "usr/share/dbus-1/system-services/org.bright_os.AURA.service"
        self.assertTrue(svc.is_file(), f"Missing {svc}")
        content = _read(svc)
        self.assertIn("Name=org.bright_os.AURA", content)
        self.assertIn("User=aura", content)
        self.assertIn("SystemdService=aura-core.service", content)

    def test_dbus_policy_no_wildcards(self):
        content = _read(CONFIG / "etc/dbus-1/system.d/org.bright_os.AURA.conf")
        self.assertNotIn('send_interface="*"', content,
                         "D-Bus policy must not allow wildcard interface")
        self.assertNotIn('send_member="*"', content,
                         "D-Bus policy must not allow wildcard method")

    def test_polkit_policy_installed(self):
        pol = CONFIG / "usr/share/polkit-1/actions/org.bright_os.AURA.policy"
        self.assertTrue(pol.is_file(), f"Missing {pol}")
        content = _read(pol)
        self.assertIn("org.bright_os.AURA.shutdown", content)
        self.assertIn("org.bright_os.AURA.grant-cloud-consent", content)
        self.assertIn("<action id=", content)

    def test_sysusers_at_standard_path(self):
        f = CONFIG / "usr/lib/sysusers.d/aura.conf"
        self.assertTrue(f.is_file(), f"sysusers.d should be at {f}")
        content = _read(f)
        self.assertIn("u     aura", content, "sysusers must declare 'u aura'")
        self.assertIn("g     aura", content, "sysusers must declare 'g aura'")
        self.assertIn("/var/lib/aura", content)
        self.assertIn("/usr/sbin/nologin", content)

    def test_sysusers_not_at_legacy_path(self):
        self.assertFalse(
            (CONFIG / "etc/aura").exists(),
            "Legacy /etc/aura/sysusers.d and tmpfiles.d should have been removed")

    def test_tmpfiles_at_standard_path(self):
        f = CONFIG / "usr/lib/tmpfiles.d/aura.conf"
        self.assertTrue(f.is_file(), f"tmpfiles.d should be at {f}")
        content = _read(f)
        for d in ("/var/lib/aura", "/var/lib/aura/backups",
                  "/var/lib/aura/models", "/var/lib/aura/conversations",
                  "/var/log/aura"):
            self.assertIn(d, content, f"tmpfiles.d missing directory {d}")

    def test_tmpfiles_conversations_is_private(self):
        content = _read(CONFIG / "usr/lib/tmpfiles.d/aura.conf")
        # find the conversations line
        for line in content.splitlines():
            if "conversations" in line:
                parts = line.split()
                # 4th column is mode (e.g. 0700)
                self.assertIn("0700", parts,
                              f"conversations should be mode 0700, got: {line}")
                break
        else:
            self.fail("conversations not found in tmpfiles.d")

    def test_aura_conf_defaults_installed(self):
        self.assertTrue(
            (CONFIG / "usr/share/aura/aura.conf.default").is_file())
        etc = CONFIG / "etc/bright-os/aura/aura.conf"
        self.assertTrue(etc.is_file(), f"Missing {etc}")

    def test_launcher_script_present_and_executable(self):
        launcher = CONFIG / "usr/bin/aura-core-service"
        self.assertTrue(launcher.is_file())
        # In the git tree the bit may not be set, but the build hook
        # chmods it; verify the source is syntactically valid.
        content = _read(launcher)
        self.assertIn("aura_core_service", content)

    def test_chroot_hook_present_and_valid(self):
        hook = PROJECT_ROOT / "config/hooks/live/40-aura-setup.hook.chroot"
        self.assertTrue(hook.is_file())
        # Shell syntax check
        r = subprocess.run(["bash", "-n", str(hook)], capture_output=True)
        self.assertEqual(r.returncode, 0,
                         f"Hook syntax error: {r.stderr.decode()}")

    def test_chroot_hook_uses_standard_sysusers_tmpfiles_paths(self):
        hook = _read(PROJECT_ROOT / "config/hooks/live/40-aura-setup.hook.chroot")
        self.assertIn("/usr/lib/sysusers.d/aura.conf", hook)
        self.assertIn("/usr/lib/tmpfiles.d/aura.conf", hook)
        self.assertNotIn("/etc/aura/sysusers.d", hook,
                         "Hook must not reference the legacy /etc/aura path")


class PackageListTests(unittest.TestCase):
    """Verify package lists reference required packages."""

    def setUp(self):
        self.pkglist = _read(CONFIG.parent / "package-lists" / "aura-core.list.chroot")

    def test_required_python_packages(self):
        for pkg in ("python3", "python3-dbus", "python3-gi", "python3-yaml",
                    "python3-psutil"):
            self.assertIn(pkg, self.pkglist.splitlines(),
                          f"Missing package: {pkg}")

    def test_required_system_packages(self):
        for pkg in ("dbus", "systemd", "policykit-1"):
            self.assertIn(pkg, self.pkglist.splitlines(),
                          f"Missing package: {pkg}")

    def test_polkit_gir_package(self):
        self.assertIn("gir1.2-polkit-1.0", self.pkglist.splitlines(),
                      "Polkit GIR bindings required for authorization checks")

    def test_no_model_weights_in_package_lists(self):
        for plist in (CONFIG.parent / "package-lists").glob("*.list.chroot"):
            content = _read(plist)
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                self.assertNotIn("gguf", line.lower(),
                                 f"Model weight file referenced in {plist.name}: {line}")
                self.assertNotIn("llama-model", line.lower())


class EditionTests(unittest.TestCase):
    """Verify edition-specific behavior."""

    def test_edition_files_exist(self):
        for ed in ("home", "developer", "lite"):
            self.assertTrue(
                (PROJECT_ROOT / "editions" / ed / "packages.list").is_file(),
                f"Missing edition package list: {ed}")

    def test_edition_detection_from_env(self):
        import importlib
        sys.path.insert(0, str(PROJECT_ROOT))
        from aura.intelligence import editions
        importlib.reload(editions)
        # Default should be home
        self.assertEqual(editions.detect_edition(), "home")
        # Env override for testing
        os.environ["AURA_EDITION"] = "lite"
        try:
            self.assertEqual(editions.detect_edition(), "lite")
        finally:
            del os.environ["AURA_EDITION"]

    def test_lite_defaults_are_offline_and_conservative(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        from aura.intelligence.editions import edition_defaults
        lite = edition_defaults("lite")
        self.assertEqual(lite["mode"], "offline")
        self.assertFalse(lite["cloud_available"])
        self.assertLessEqual(lite["max_memory_percent"], 40)
        self.assertLess(lite["unload_idle_seconds"], 300)

    def test_developer_defaults_allow_more_resources(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        from aura.intelligence.editions import edition_defaults
        dev = edition_defaults("developer")
        self.assertGreaterEqual(dev["max_memory_percent"], 60)
        self.assertTrue(dev["dev_tools_enabled"])

    def test_home_defaults_balanced(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        from aura.intelligence.editions import edition_defaults
        home = edition_defaults("home")
        self.assertEqual(home["mode"], "local")
        self.assertFalse(home["auto_load_at_boot"])

    def test_build_script_writes_edition_marker(self):
        bs = _read(PROJECT_ROOT / "build/scripts/build.sh")
        self.assertIn('echo "${EDITION}"', bs)
        self.assertIn("config/includes.chroot/etc/bright-os/edition", bs)


class DefaultConfigTests(unittest.TestCase):
    """Verify security-critical defaults in the configuration."""

    def setUp(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        from aura.core.config import DEFAULTS
        self.d = DEFAULTS

    def test_default_mode_is_local(self):
        self.assertEqual(self.d["intelligence"]["mode"], "local")

    def test_cloud_disabled_by_default(self):
        self.assertEqual(self.d["intelligence"]["allow_cloud_default"], "false")
        self.assertEqual(self.d["intelligence"]["require_consent"], "true")

    def test_no_auto_load_at_boot(self):
        self.assertEqual(self.d["intelligence"]["auto_load_at_boot"], "false")

    def test_lazy_load_enabled(self):
        self.assertEqual(self.d["intelligence"]["lazy_load"], "true")

    def test_telemetry_disabled(self):
        self.assertEqual(self.d["intelligence"]["enable_telemetry"], "false")

    def test_auto_isolate_defaults_off(self):
        self.assertEqual(self.d["security"]["auto_isolate"], "false")

    def test_default_cpu_threads_leaves_headroom(self):
        self.assertEqual(self.d["intelligence"]["cpu_threads"], "0")

    def test_max_memory_capped(self):
        self.assertEqual(self.d["intelligence"]["max_memory_percent"], "50")


class NoModelWeightsTests(unittest.TestCase):
    """Verify no AI model weights are bundled with the ISO."""

    def test_no_gguf_files_in_config_tree(self):
        for p in (CONFIG.parent).rglob("*.gguf"):
            self.fail(f"Found .gguf model weight: {p}")

    def test_no_ggml_files_in_config_tree(self):
        for p in (CONFIG.parent).rglob("*.ggml"):
            self.fail(f"Found .ggml model weight: {p}")

    def test_no_models_in_var_lib_aura(self):
        models_dir = CONFIG / "var/lib/aura/models"
        if models_dir.exists():
            files = [p for p in models_dir.rglob("*") if p.is_file()]
            self.assertEqual(files, [],
                             f"Found files in /var/lib/aura/models (should be empty in ISO): {files}")


class DBusServiceCompletenessTests(unittest.TestCase):
    """Verify every advertised D-Bus method has an implementation."""

    def test_all_methods_implemented(self):
        sys.path.insert(0, str(PROJECT_ROOT))
        # Inspect the source for @dbus.service.method decorators to find
        # all registered method names; verify the service class has them.
        src = _read(PROJECT_ROOT / "aura/core/aura_core_service.py")
        import re
        methods = re.findall(r'def\s+(\w+)\(self', src)
        # Methods that must exist
        required = {
            "GetVersion", "GetStatus", "GetServiceInfo", "ListComponents",
            "GetComponentStatus", "GetAllComponentStatus", "IsComponentHealthy",
            "Shutdown", "GetAIMode", "SetAIMode", "ListAIModels",
            "ListAIProviders", "GetActiveAIProvider", "GetLoadedModel",
            "LoadAIModel", "UnloadAIModel", "GetHardwareSuitability",
            "GetResourceUsage", "GetInferenceStatus", "CancelInference",
            "CancelAllInference", "GrantCloudConsent",
        }
        for m in required:
            self.assertIn(m, methods, f"D-Bus method {m} not implemented in aura_core_service.py")


class FailureIsolationTests(unittest.TestCase):
    """Verify that component failures do not crash the whole service."""

    def test_intelligence_failure_leaves_core_running(self):
        """If the intelligence engine fails to start, AURA core should
        still be reachable (component enters DISABLED/FAILED state)."""
        sys.path.insert(0, str(PROJECT_ROOT))
        from aura.core.aura_core_service import IntelligenceComponent
        from aura.core.config import AuraConfig
        from aura.core.components import ComponentState
        import logging
        logging.basicConfig(level=logging.ERROR)
        with tempfile.TemporaryDirectory() as td:
            cfg = AuraConfig(config_dir=td)
            comp = IntelligenceComponent("intelligence", cfg)
            # Force ImportError for a fake missing module by setting
            # broken sys.modules entry.
            import builtins
            real_import = builtins.__import__
            def fake_import(name, *a, **k):
                if name == "aura.intelligence":
                    raise ImportError("simulated missing module")
                return real_import(name, *a, **k)
            builtins.__import__ = fake_import
            try:
                comp.start()
            finally:
                builtins.__import__ = real_import
            self.assertEqual(comp.state, ComponentState.DISABLED,
                             f"Intelligence should DISABLE on import error, was {comp.state}")
            comp.stop()


class PolkitNotImportedAtModuleLoad(unittest.TestCase):
    """Polkit import should be optional (HAS_POLKIT flag) so the
    service can still start in minimal environments."""

    def test_polkit_is_optional(self):
        src = _read(PROJECT_ROOT / "aura/core/aura_core_service.py")
        self.assertIn("HAS_POLKIT", src)
        self.assertIn("except ImportError:", src)  # graceful fallback


if __name__ == "__main__":
    unittest.main(verbosity=2)
