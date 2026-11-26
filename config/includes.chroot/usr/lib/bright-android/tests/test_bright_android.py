"""Bright Android unit tests.

Tests are organized into categories:
  - CompatibilityTests: kernel, memfd, wayland, graphics, RAM, disk, packages
  - APKValidationTests: file validation, ABI detection, path safety
  - ConfigTests: config persistence, permissions, defaults
  - WaydroidManagerTests: subprocess safety, status parsing, name validation
  - RuntimeStatusTests: state machine (not-installed/not-init/stopped/starting/running)
  - LauncherIntegrationTests: .desktop file creation, removal, sync
  - SecurityValidationTests: shell=False, polkit enforcement, path safety, permissions
  - EditionBehaviorTests: package inclusion/exclusion for Home/Developer/Lite
  - PolkitPolicyTests: XML validation, authorization requirements
  - AURAIntegrationTests: command handler confirmation gates
  - HardwareReadinessTests: resource assessment tiers (supported/limited/unsupported)
  - SystemdServiceTests: unit file correctness

All tests use mocks; no real Waydroid installation or Android container is
required. Integration tests that require real Waydroid are separated into a
different class and are skipped unless WAYDROID_INTEGRATION=1 is set.
"""
import configparser
import io
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Detect if we can run real Waydroid integration tests
RUN_INTEGRATION = os.environ.get("WAYDROID_INTEGRATION", "") == "1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_apk(entries, suffix=".apk", padding_size=4096):
    """Helper to create a valid APK (ZIP) of reasonable size."""
    padding = b"X" * padding_size
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        with zipfile.ZipFile(f, "w") as zf:
            for name, data in entries:
                zf.writestr(name, data)
            zf.writestr("resources.arsc", padding)
        return f.name


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------

class CompatibilityTests(unittest.TestCase):
    """Tests for the fixed compatibility detection."""

    def test_binder_not_available_when_no_devices_and_no_module(self):
        """When /dev/binder doesn't exist and kernel config doesn't show binder,
        and binder_linux module isn't on disk, binder_available must be False."""
        from bright_android.core.compatibility import check_binder
        with mock.patch("os.path.exists", return_value=False), \
             mock.patch("bright_android.core.compatibility._read_kernel_config",
                        return_value={}), \
             mock.patch("bright_android.core.compatibility._run_cmd",
                        return_value=(1, "", "")), \
             mock.patch("shutil.which", return_value=None):
            result = check_binder()
            self.assertFalse(result["binder_available"])
            self.assertFalse(result["kernel_supported"])

    def test_binder_available_when_dev_binder_exists(self):
        """When /dev/binder exists, binder is available regardless of config."""
        from bright_android.core.compatibility import check_binder
        exists_map = {"/dev/binder": True}
        with mock.patch("os.path.exists",
                        side_effect=lambda p: exists_map.get(p, False)), \
             mock.patch("bright_android.core.compatibility._read_kernel_config",
                        return_value={}), \
             mock.patch("bright_android.core.compatibility._run_cmd",
                        return_value=(1, "", "")):
            result = check_binder()
            self.assertTrue(result["binder_available"])
            self.assertIn("/dev/binder", " ".join(result["details"]))

    def test_binder_distinguishes_kernel_support_from_loaded_module(self):
        """Kernel supports binder (CONFIG_ANDROID_BINDER_IPC=m) but module is
        not loaded — should report module_needs_loading, not binder_available."""
        from bright_android.core.compatibility import check_binder
        # No /dev/binder, but kernel config shows binder=m and module is on disk
        with mock.patch("os.path.exists", return_value=False), \
             mock.patch("bright_android.core.compatibility._read_kernel_config",
                        return_value={"CONFIG_ANDROID_BINDER_IPC": "m",
                                     "CONFIG_ANDROID_BINDERFS": "m"}), \
             mock.patch("bright_android.core.compatibility._run_cmd",
                        return_value=(0, "", "")), \
             mock.patch("shutil.which", return_value="/sbin/modinfo"):
            result = check_binder()
            self.assertFalse(result["binder_available"])
            self.assertTrue(result["kernel_supported"])
            self.assertTrue(result["module_installable"])
            self.assertTrue(result["module_needs_loading"])
            # Must NOT attempt modprobe from a GUI process
            # (we verify _run_cmd was never called with "modprobe" below)

    def test_memfd_detection_does_not_always_return_true(self):
        """Regression test: memfd_available must NOT unconditionally be True
        (the bug was `result["memfd_available"] = ... or True`)."""
        from bright_android.core.compatibility import check_memfd
        # Patch ctypes to simulate memfd_create failing
        ctypes_mock = mock.MagicMock()
        ctypes_mock.CDLL.side_effect = OSError("no libc")
        with mock.patch("os.path.exists", return_value=False), \
             mock.patch.dict("sys.modules", {"ctypes": ctypes_mock}), \
             mock.patch("os.uname", return_value=mock.MagicMock(release="2.6.0")), \
             mock.patch("builtins.open", mock.mock_open(read_data="")):
            # Old kernel (2.6 < 3.17), no tmpfs, no ashmem — should be False
            result = check_memfd()
            self.assertIsInstance(result["memfd_available"], bool)
            self.assertFalse(result["memfd_available"])

    def test_memfd_detected_via_ctypes(self):
        """memfd_create returns a valid fd when libc supports it."""
        from bright_android.core.compatibility import check_memfd
        # Create a real ctypes call that simulates memfd_create working.
        # We'll mock os.close and the syscall.
        fake_fd = 5
        libc_mock = mock.MagicMock()
        libc_mock.syscall.return_value = fake_fd
        ctypes_mod = mock.MagicMock()
        ctypes_mod.CDLL.return_value = libc_mock
        with mock.patch.dict("sys.modules", {"ctypes": ctypes_mod}), \
             mock.patch("os.close") as mock_close, \
             mock.patch("os.path.exists", return_value=False):
            result = check_memfd()
            self.assertTrue(result["memfd_available"])
            mock_close.assert_called_with(fake_fd)

    def test_no_modprobe_called_from_check(self):
        """The compatibility checker must NOT attempt to load the binder module.
        Module loading requires root and must be authorized via Polkit/pkexec."""
        from bright_android.core import compatibility
        # Ensure _run_cmd is never called with "modprobe" as first arg
        with mock.patch("os.path.exists", return_value=False), \
             mock.patch("bright_android.core.compatibility._read_kernel_config",
                        return_value={}), \
             mock.patch("shutil.which", return_value=None), \
             mock.patch("bright_android.core.compatibility._run_cmd",
                        return_value=(1, "", "")) as mock_run:
            compatibility.check_binder()
            for call in mock_run.call_args_list:
                cmd = call[0][0]
                self.assertNotIn("modprobe", cmd,
                    "check_binder() must not invoke modprobe; loading kernel "
                    "modules requires root and must go through pkexec")

    def test_wayland_detection_wayland_session(self):
        from bright_android.core.compatibility import check_wayland_session
        env = {"XDG_SESSION_TYPE": "wayland",
               "XDG_RUNTIME_DIR": "/tmp/test-runtime",
               "WAYLAND_DISPLAY": "wayland-0"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("os.path.isdir", return_value=True), \
             mock.patch("os.path.exists", return_value=True):
            result = check_wayland_session()
            self.assertTrue(result["wayland_available"])

    def test_wayland_detection_x11_only(self):
        from bright_android.core.compatibility import check_wayland_session
        env = {"XDG_SESSION_TYPE": "x11",
               "XDG_RUNTIME_DIR": "/tmp/test-runtime"}
        with mock.patch.dict(os.environ, env, clear=True):
            result = check_wayland_session()
            self.assertFalse(result["wayland_available"])

    def test_disk_space_check(self):
        from bright_android.core.compatibility import check_disk_space
        with tempfile.TemporaryDirectory() as tmpdir:
            result = check_disk_space(tmpdir)
            self.assertIn("available_gb", result)
            self.assertIsInstance(result["available_gb"], float)

    def test_ram_check_reads_meminfo(self):
        from bright_android.core.compatibility import check_ram
        fake_meminfo = (
            "MemTotal:        8000000 kB\n"
            "MemFree:         2000000 kB\n"
            "MemAvailable:    4000000 kB\n"
            "SwapTotal:       2097148 kB\n"
            "SwapFree:        1048572 kB\n"
        )
        with mock.patch("builtins.open", mock.mock_open(read_data=fake_meminfo)):
            result = check_ram()
            self.assertEqual(result["total_mb"], 8000000 // 1024)
            self.assertEqual(result["available_mb"], 4000000 // 1024)

    def test_swap_check(self):
        from bright_android.core.compatibility import check_swap
        fake_meminfo = (
            "MemTotal:       8000000 kB\n"
            "MemAvailable:   4000000 kB\n"
            "SwapTotal:      2097148 kB\n"
            "SwapFree:       2097148 kB\n"
        )
        with mock.patch("builtins.open", mock.mock_open(read_data=fake_meminfo)):
            result = check_swap()
            self.assertTrue(result["swap_available"])
            self.assertEqual(result["swap_total_mb"], 2097148 // 1024)

    def test_cpu_check_x86_64(self):
        from bright_android.core.compatibility import check_cpu
        with mock.patch("platform.machine", return_value="x86_64"), \
             mock.patch("os.cpu_count", return_value=4):
            result = check_cpu()
            self.assertTrue(result["compatible"])
            self.assertEqual(result["arch"], "x86_64")

    def test_full_check_returns_running_key(self):
        """run_full_check() must return a 'running' key with bool."""
        from bright_android.core import compatibility, waydroid_manager
        with mock.patch.object(compatibility, "check_binder",
                              return_value={"binder_available": True, "kernel_supported": True,
                                           "details": [], "devices_present": True,
                                           "binderfs_mounted": False,
                                           "module_needs_loading": False,
                                           "module_installable": False}), \
             mock.patch.object(compatibility, "check_memfd",
                              return_value={"memfd_available": True,
                                           "ashmem_available": False, "details": []}), \
             mock.patch.object(compatibility, "check_wayland_session",
                              return_value={"wayland_available": True, "details": [],
                                           "session_type": "wayland"}), \
             mock.patch.object(compatibility, "check_graphics",
                              return_value={"graphics_ok": True, "details": [],
                                           "software_rendering": False,
                                           "renderer": "Mesa", "vendor": "AMD",
                                           "gl_version": "4.6", "gles": True,
                                           "driver": "amdgpu", "render_node": "/dev/dri/renderD128"}), \
             mock.patch.object(compatibility, "check_disk_space",
                              return_value={"available_gb": 500.0, "total_gb": 932.0,
                                           "sufficient": True, "details": [], "path": "/"}), \
             mock.patch.object(compatibility, "check_ram",
                              return_value={"total_mb": 8192, "available_mb": 4096,
                                           "sufficient": True, "recommended": True,
                                           "low_resource": False, "details": []}), \
             mock.patch.object(compatibility, "check_swap",
                              return_value={"swap_total_mb": 2048, "swap_free_mb": 2048,
                                           "swap_available": True, "details": []}), \
             mock.patch.object(compatibility, "check_cpu",
                              return_value={"arch": "x86_64", "cores": 4, "model": "AMD A10-8700P",
                                           "compatible": True, "details": []}), \
             mock.patch.object(compatibility, "check_packages",
                              return_value={"waydroid_installed": True, "waydroid_version": "1.4.0",
                                           "lxc_installed": True, "missing_packages": [],
                                           "details": ["waydroid 1.4.0"]}), \
             mock.patch.object(compatibility, "check_waydroid_initialized",
                              return_value={"initialized": True, "images_present": True,
                                           "prop_present": True, "details": []}), \
             mock.patch.object(waydroid_manager, "is_running", return_value=True):
            report = compatibility.run_full_check()
            self.assertIn("running", report)
            self.assertTrue(report["running"])
            self.assertIn("hardware_readiness", report)


# ---------------------------------------------------------------------------
# APK Validation
# ---------------------------------------------------------------------------

class APKValidationTests(unittest.TestCase):

    def test_reject_nonexistent_file(self):
        from bright_android.core.apk_validator import is_compatible_x86_64
        result = is_compatible_x86_64("/nonexistent/file.apk")
        self.assertFalse(result["compatible"])
        self.assertIn("not found", result["reason"])

    def test_reject_non_apk_extension(self):
        from bright_android.core.apk_validator import validate_apk_path
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            f.write(b"PK\x03\x04dummy")
            f.flush()
            err = validate_apk_path(f.name)
            self.assertIsNotNone(err)
            self.assertIn("APK", err)

    def test_reject_too_small_file(self):
        from bright_android.core.apk_validator import is_compatible_x86_64
        with tempfile.NamedTemporaryFile(suffix=".apk") as f:
            f.write(b"tiny")
            f.flush()
            result = is_compatible_x86_64(f.name)
            self.assertFalse(result["compatible"])

    def test_validate_apk_path_null_byte(self):
        from bright_android.core.apk_validator import validate_apk_path
        err = validate_apk_path("/tmp/test.apk\x00evil")
        self.assertIsNotNone(err)
        self.assertIn("null byte", err)

    def test_x86_64_apk_compatible(self):
        from bright_android.core.apk_validator import is_compatible_x86_64
        tmpname = _make_apk([
            ("AndroidManifest.xml", b"binary-manifest"),
            ("lib/x86_64/libtest.so", b"fake-so" * 200),
            ("classes.dex", b"fake-dex" * 200),
        ])
        try:
            result = is_compatible_x86_64(tmpname)
            self.assertTrue(result["compatible"], msg=result["reason"])
            self.assertIn("x86_64", result["architectures"])
        finally:
            os.unlink(tmpname)

    def test_universal_apk_compatible(self):
        from bright_android.core.apk_validator import is_compatible_x86_64
        tmpname = _make_apk([
            ("AndroidManifest.xml", b"binary"),
            ("classes.dex", b"fake-dex" * 200),
        ])
        try:
            result = is_compatible_x86_64(tmpname)
            self.assertTrue(result["compatible"], msg=result["reason"])
            self.assertTrue(result["is_universal"])
        finally:
            os.unlink(tmpname)

    def test_arm_only_apk_incompatible(self):
        from bright_android.core.apk_validator import is_compatible_x86_64
        tmpname = _make_apk([
            ("AndroidManifest.xml", b"binary"),
            ("lib/arm64-v8a/libtest.so", b"fake-so" * 200),
        ])
        try:
            result = is_compatible_x86_64(tmpname)
            self.assertFalse(result["compatible"])
            self.assertIn("ARM", result["reason"])
        finally:
            os.unlink(tmpname)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class ConfigTests(unittest.TestCase):

    def test_defaults_have_no_autostart(self):
        """Bright Android must NOT auto-start by default per requirements."""
        from bright_android.core import config as ba_config
        self.assertFalse(ba_config.get_bool("runtime", "auto_start", False))
        self.assertTrue(ba_config.get_bool("runtime", "start_on_demand", True))

    def test_set_and_get(self):
        from bright_android.core import config as ba_config
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("bright_android.core.config.CONFIG_DIR", tmpdir), \
                 mock.patch("bright_android.core.config.CONFIG_FILE",
                           os.path.join(tmpdir, "config.ini")):
                ba_config.set_bool("test", "enabled", True)
                self.assertTrue(ba_config.get_bool("test", "enabled", False))

    def test_config_file_permissions_0600(self):
        from bright_android.core import config as ba_config
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.ini")
            with mock.patch("bright_android.core.config.CONFIG_DIR", tmpdir), \
                 mock.patch("bright_android.core.config.CONFIG_FILE", cfg_path):
                ba_config.set_value("test", "k", "v")
                mode = os.stat(cfg_path).st_mode & 0o777
                self.assertEqual(mode, 0o600)


# ---------------------------------------------------------------------------
# Waydroid Manager
# ---------------------------------------------------------------------------

class WaydroidManagerTests(unittest.TestCase):

    def test_is_installed_checks_path(self):
        from bright_android.core import waydroid_manager
        with mock.patch("shutil.which", return_value="/usr/bin/waydroid"):
            self.assertTrue(waydroid_manager.is_installed())
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(waydroid_manager.is_installed())

    def test_require_waydroid_decorator(self):
        from bright_android.core.waydroid_manager import WaydroidError, _require_waydroid

        @_require_waydroid
        def dummy():
            return True

        with mock.patch("bright_android.core.waydroid_manager.is_installed",
                       return_value=False):
            with self.assertRaises(WaydroidError):
                dummy()
        with mock.patch("bright_android.core.waydroid_manager.is_installed",
                       return_value=True):
            self.assertTrue(dummy())

    def test_run_uses_argument_list_never_shell(self):
        from bright_android.core import waydroid_manager
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            waydroid_manager._run(["status"], timeout=5)
            args = mock_run.call_args
            self.assertFalse(args[1].get("shell", False))
            cmd_list = args[0][0]
            self.assertIsInstance(cmd_list, list)
            self.assertEqual(cmd_list[0], "waydroid")

    def test_run_as_root_prepends_pkexec(self):
        from bright_android.core import waydroid_manager
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            waydroid_manager._run(["init"], as_root=True)
            cmd_list = mock_run.call_args[0][0]
            self.assertEqual(cmd_list[0], "pkexec")
            self.assertEqual(cmd_list[1], "waydroid")
            self.assertEqual(cmd_list[2], "init")

    def test_invalid_package_name_rejected(self):
        from bright_android.core import waydroid_manager
        from bright_android.core.waydroid_manager import WaydroidError
        with mock.patch("bright_android.core.waydroid_manager.is_installed",
                       return_value=True), \
             mock.patch("bright_android.core.waydroid_manager.is_running",
                       return_value=True), \
             mock.patch("bright_android.core.waydroid_manager.is_initialized",
                       return_value=True):
            with self.assertRaises(WaydroidError):
                waydroid_manager.uninstall_app("; rm -rf /")
            # Legitimate package name should pass validation
            with mock.patch("bright_android.core.waydroid_manager._run",
                           return_value=(0, "Success", "")):
                result = waydroid_manager.uninstall_app("com.example.app")
                self.assertTrue(result["success"])

    def test_parse_status_running(self):
        from bright_android.core.waydroid_manager import _parse_status_output
        out = "Session:\tRUNNING\nContainer:\tRUNNING\nVendor type:\tMAINLINE\n"
        parsed = _parse_status_output(out)
        self.assertEqual(parsed["session"], "RUNNING")
        self.assertEqual(parsed["container"], "RUNNING")

    def test_parse_status_stopped(self):
        from bright_android.core.waydroid_manager import _parse_status_output
        out = "Session:\tSTOPPED\nContainer:\tSTOPPED\n"
        parsed = _parse_status_output(out)
        self.assertEqual(parsed["session"], "STOPPED")
        self.assertEqual(parsed["container"], "STOPPED")

    def test_get_status_returns_running_state(self):
        """get_status() must correctly return running=True when waydroid
        reports RUNNING."""
        from bright_android.core import waydroid_manager
        status_output = "Session:\tRUNNING\nContainer:\tRUNNING\n"
        with mock.patch("bright_android.core.waydroid_manager.is_installed",
                       return_value=True), \
             mock.patch("bright_android.core.waydroid_manager.is_initialized",
                       return_value=True), \
             mock.patch("bright_android.core.waydroid_manager._run",
                       return_value=(0, status_output, "")):
            # Invalidate cache
            waydroid_manager._invalidate_status_cache()
            status = waydroid_manager.get_status(force_refresh=True)
            self.assertTrue(status["running"])
            self.assertEqual(status["session"], "RUNNING")
            self.assertEqual(status["container"], "RUNNING")


# ---------------------------------------------------------------------------
# Runtime Status state machine (regression for the `if False` bug)
# ---------------------------------------------------------------------------

class RuntimeStatusTests(unittest.TestCase):
    """Verify runtime state detection works correctly (not-installed /
    not-initialized / stopped / starting / running)."""

    def test_gui_running_detected_as_running(self):
        """Regression test: running runtime must be displayed as running,
        not always stopped (the `if False else False` bug)."""
        from bright_android.core import compatibility, waydroid_manager
        with mock.patch.object(compatibility, "check_binder",
                return_value={"binder_available": True, "kernel_supported": True,
                              "details": [], "devices_present": True,
                              "binderfs_mounted": True,
                              "module_needs_loading": False,
                              "module_installable": False}), \
             mock.patch.object(compatibility, "check_memfd",
                return_value={"memfd_available": True, "ashmem_available": False, "details": []}), \
             mock.patch.object(compatibility, "check_wayland_session",
                return_value={"wayland_available": True, "details": [], "session_type": "wayland"}), \
             mock.patch.object(compatibility, "check_graphics",
                return_value={"graphics_ok": True, "details": [],
                              "software_rendering": False, "renderer": "Mesa",
                              "vendor": "AMD", "gl_version": "4.6", "gles": True,
                              "driver": "amdgpu", "render_node": "/dev/dri/renderD128"}), \
             mock.patch.object(compatibility, "check_disk_space",
                return_value={"available_gb": 500.0, "total_gb": 932.0,
                              "sufficient": True, "details": [], "path": "/"}), \
             mock.patch.object(compatibility, "check_ram",
                return_value={"total_mb": 8192, "available_mb": 4096,
                              "sufficient": True, "recommended": True,
                              "low_resource": False, "details": []}), \
             mock.patch.object(compatibility, "check_swap",
                return_value={"swap_total_mb": 2048, "swap_free_mb": 2048,
                              "swap_available": True, "details": []}), \
             mock.patch.object(compatibility, "check_cpu",
                return_value={"arch": "x86_64", "cores": 4, "model": "AMD A10",
                              "compatible": True, "details": []}), \
             mock.patch.object(compatibility, "check_packages",
                return_value={"waydroid_installed": True, "waydroid_version": "1.4.0",
                              "lxc_installed": True, "missing_packages": [],
                              "details": ["waydroid 1.4.0"]}), \
             mock.patch.object(compatibility, "check_waydroid_initialized",
                return_value={"initialized": True, "images_present": True,
                              "prop_present": True, "details": []}), \
             mock.patch.object(waydroid_manager, "is_running", return_value=True):
            report = compatibility.run_full_check()
            # Regression: 'running' must be True when is_running() returns True
            self.assertTrue(report["running"],
                "run_full_check() must set 'running' to True when runtime is up")


# ---------------------------------------------------------------------------
# Launcher Integration
# ---------------------------------------------------------------------------

class LauncherIntegrationTests(unittest.TestCase):

    def test_desktop_entry_created(self):
        from bright_android.core.launcher_integration import (
            create_app_desktop_entry
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            icons = os.path.join(tmpdir, "icons")
            cache = os.path.join(tmpdir, "cache")
            os.makedirs(icons)
            os.makedirs(cache)
            with mock.patch("bright_android.core.launcher_integration.APP_DIR", tmpdir), \
                 mock.patch("bright_android.core.launcher_integration.ICON_DIR", icons), \
                 mock.patch("bright_android.core.launcher_integration.ANDROID_ICON_CACHE", cache), \
                 mock.patch("bright_android.core.launcher_integration._update_desktop_database"):
                app = {"package": "com.example.test", "name": "Test App",
                       "launch_activity": "com.example/.Main"}
                path = create_app_desktop_entry(app)
                self.assertTrue(path.exists())
                content = path.read_text()
                self.assertIn("com.example.test", content)
                self.assertIn("Test App", content)
                self.assertIn("bright-android --launch", content)
                self.assertIn("X-Bright-Android", content)

    def test_remove_app_entry(self):
        from bright_android.core.launcher_integration import (
            create_app_desktop_entry, remove_app_desktop_entry
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            icons = os.path.join(tmpdir, "icons")
            cache = os.path.join(tmpdir, "cache")
            os.makedirs(icons); os.makedirs(cache)
            with mock.patch("bright_android.core.launcher_integration.APP_DIR", tmpdir), \
                 mock.patch("bright_android.core.launcher_integration.ICON_DIR", icons), \
                 mock.patch("bright_android.core.launcher_integration.ANDROID_ICON_CACHE", cache), \
                 mock.patch("bright_android.core.launcher_integration._update_desktop_database"):
                app = {"package": "com.test.app", "name": "App"}
                create_app_desktop_entry(app)
                self.assertTrue(remove_app_desktop_entry("com.test.app"))
                self.assertFalse(remove_app_desktop_entry("com.test.app"))


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

class SecurityValidationTests(unittest.TestCase):

    def test_apk_path_traversal_resolved(self):
        from bright_android.core.apk_validator import validate_apk_path
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "test.apk")
            Path(fpath).write_bytes(b"PK\x03\x04" + b"X" * 2000)
            self.assertIsNone(validate_apk_path(fpath))

    def test_waydroid_run_does_not_use_shell_true(self):
        """Verify subprocess.run is called with shell=False (or no shell kwarg)."""
        from bright_android.core import waydroid_manager
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value = mock.MagicMock(
                returncode=0, stdout="", stderr=""
            )
            waydroid_manager._run(["status"], timeout=5)
            kwargs = mock_run.call_args[1]
            self.assertFalse(kwargs.get("shell", False),
                "_run must never pass shell=True to subprocess.run")

    def test_polkit_check_rejects_no_sender(self):
        """When a real bus is present, sender=None must be denied (fail-closed).
        bus=None is also denied (see FailClosedTests)."""
        from bright_android.core.android_service import _check_authorization
        import bright_android.core.android_service as svc
        bus_mock = mock.MagicMock()
        with mock.patch.object(svc, "HAS_DBUS", True):
            ok, reason = _check_authorization(
                None, "org.bright_os.BrightAndroid.init", bus=bus_mock
            )
        self.assertFalse(ok, f"Expected denial for None sender, got: {reason}")

    def test_polkit_check_rejects_invalid_pid(self):
        from bright_android.core.android_service import _check_authorization
        import bright_android.core.android_service as svc
        bus_mock = mock.MagicMock()
        bus_mock.get_connection_unix_process_id.side_effect = Exception("no such sender")
        with mock.patch.object(svc, "HAS_DBUS", True), \
             mock.patch.object(svc, "HAS_POLKIT", False):
            ok, reason = _check_authorization(
                ":1.0", "org.bright_os.BrightAndroid.init", bus=bus_mock
            )
        self.assertFalse(ok, f"Expected denial on credential failure, got: {reason}")

    def test_polkit_check_allows_root(self):
        from bright_android.core.android_service import _check_authorization
        import bright_android.core.android_service as svc
        bus_mock = mock.MagicMock()
        bus_mock.get_connection_unix_process_id.return_value = 100
        bus_mock.get_connection_unix_user.return_value = 0  # root
        with mock.patch.object(svc, "HAS_DBUS", True), \
             mock.patch.object(svc, "HAS_POLKIT", False):
            ok, reason = _check_authorization(
                ":1.0", "org.bright_os.BrightAndroid.init", bus=bus_mock
            )
        self.assertTrue(ok, f"Expected root to be allowed, got: {reason}")
        self.assertIn("root", reason)

    def test_config_permissions_0600(self):
        from bright_android.core import config as ba_config
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.ini")
            with mock.patch("bright_android.core.config.CONFIG_DIR", tmpdir), \
                 mock.patch("bright_android.core.config.CONFIG_FILE", cfg_path):
                ba_config.set_value("x", "y", "z")
                mode = os.stat(cfg_path).st_mode & 0o777
                self.assertEqual(mode, 0o600)


# ---------------------------------------------------------------------------
# Edition Behavior
# ---------------------------------------------------------------------------

class EditionBehaviorTests(unittest.TestCase):

    def test_lite_does_not_include_android_packages(self):
        """The build script must not copy android.list.chroot for Lite."""
        build_sh = (PROJECT_ROOT / "build/scripts/build.sh").read_text()
        # The logic must be: lite -> do NOT copy; else -> copy
        self.assertIn('"${EDITION}" = "lite"', build_sh)
        self.assertIn("Android support optional (not installed by default)", build_sh)
        # Outside the lite branch, android list IS copied
        self.assertIn("android.list.chroot", build_sh)
        self.assertIn("android-packages.list.chroot", build_sh)

    def test_home_developer_include_android_packages(self):
        build_sh = (PROJECT_ROOT / "build/scripts/build.sh").read_text()
        self.assertIn("Android packages: included", build_sh)

    def test_package_list_exists_and_no_google_services(self):
        pkglist = (PROJECT_ROOT / "config/package-lists/android.list.chroot").read_text()
        self.assertIn("waydroid", pkglist)
        self.assertNotIn("gapps", pkglist.lower())
        self.assertNotIn("google-play", pkglist.lower())

    def test_no_gapps_init_by_default(self):
        from bright_android.core import waydroid_manager
        self.assertEqual(waydroid_manager.DEFAULT_MODE, "vanilla")
        import inspect
        init_src = inspect.getsource(waydroid_manager.init)
        self.assertIn("VANILLA", init_src)
        # The init function must not default to gapps
        self.assertNotIn('"GAPPS"', init_src.split('if mode == "gapps"')[0])


# ---------------------------------------------------------------------------
# Polkit policy
# ---------------------------------------------------------------------------

class PolkitPolicyTests(unittest.TestCase):

    def setUp(self):
        import xml.etree.ElementTree as ET
        p = PROJECT_ROOT / "config/includes.chroot/usr/share/polkit-1/actions/org.bright_os.BrightAndroid.policy"
        self.tree = ET.parse(p)
        self.root = self.tree.getroot()

    def _action(self, aid):
        for a in self.root.findall("action"):
            if a.get("id") == aid:
                return a.find("defaults")
        self.fail(f"action {aid} not found")

    def test_init_requires_admin(self):
        d = self._action("org.bright_os.BrightAndroid.init")
        self.assertEqual(d.findtext("allow_any"), "auth_admin")
        self.assertEqual(d.findtext("allow_active"), "auth_admin_keep")

    def test_install_apk_requires_admin(self):
        d = self._action("org.bright_os.BrightAndroid.install-apk")
        self.assertEqual(d.findtext("allow_any"), "auth_admin")
        self.assertEqual(d.findtext("allow_active"), "auth_admin_keep")

    def test_remove_data_requires_admin(self):
        d = self._action("org.bright_os.BrightAndroid.remove-data")
        self.assertEqual(d.findtext("allow_active"), "auth_admin")

    def test_stop_allows_active_user(self):
        d = self._action("org.bright_os.BrightAndroid.stop")
        self.assertEqual(d.findtext("allow_active"), "yes")


# ---------------------------------------------------------------------------
# Systemd unit file
# ---------------------------------------------------------------------------

class SystemdServiceTests(unittest.TestCase):

    def setUp(self):
        self.unit_path = PROJECT_ROOT / "config/includes.chroot/usr/lib/systemd/user/bright-android.service"
        self.unit = self.unit_path.read_text()

    def test_service_runs_on_session_bus(self):
        """ExecStart must include --session to connect to session bus."""
        self.assertIn("--service --session", self.unit)
        self.assertNotIn("ExecStart=/usr/bin/bright-android --service\n", self.unit)

    def test_service_does_not_block_pkexec(self):
        """NoNewPrivileges=yes must NOT be an active directive
        (would block pkexec setuid). Comments mentioning the setting are fine."""
        active = [l for l in self.unit.splitlines()
                  if l.strip() and not l.strip().startswith('#')]
        self.assertFalse(
            any(l.strip() == "NoNewPrivileges=yes" for l in active),
            "NoNewPrivileges=yes must not be active (blocks pkexec setuid)"
        )

    def test_readwrite_paths_for_waydroid(self):
        """Must allow writes to /var/lib/waydroid and /etc/waydroid."""
        self.assertIn("/var/lib/waydroid", self.unit)
        self.assertIn("/etc/waydroid", self.unit)

    def test_uses_dbus_activation(self):
        self.assertIn("Type=dbus", self.unit)
        self.assertIn("BusName=org.bright_os.BrightAndroid", self.unit)


# ---------------------------------------------------------------------------
# AURA integration
# ---------------------------------------------------------------------------

class AURAIntegrationTests(unittest.TestCase):

    def test_requires_confirmation_for_privileged(self):
        from aura.commands.bright_android import requires_confirmation
        for act in ("install_runtime", "init_runtime", "install_apk",
                    "uninstall_app", "remove_data", "stop_runtime"):
            self.assertTrue(requires_confirmation(act),
                            f"{act} must require confirmation")

    def test_no_confirmation_for_readonly(self):
        from aura.commands.bright_android import requires_confirmation
        for act in ("list_apps", "get_status", "diagnose", "get_recommendation"):
            self.assertFalse(requires_confirmation(act),
                            f"{act} must NOT require confirmation")

    def test_get_status_returns_dict(self):
        from aura.commands.bright_android import get_android_status
        with mock.patch("shutil.which", return_value=None):
            s = get_android_status()
            self.assertFalse(s["installed"])
            self.assertEqual(s["app_count"], 0)


# ---------------------------------------------------------------------------
# Hardware readiness tiers
# ---------------------------------------------------------------------------

class HardwareReadinessTests(unittest.TestCase):

    def _make_report(self, **overrides):
        base = {
            "can_install": True,
            "binder": {"binder_available": True, "kernel_supported": True,
                      "module_installable": False, "module_needs_loading": False},
            "memfd": {"memfd_available": True},
            "wayland": {"wayland_available": True},
            "graphics": {"graphics_ok": True, "software_rendering": False,
                        "renderer": "AMD Radeon R6", "vendor": "AMD"},
            "disk": {"sufficient": True, "available_gb": 500.0},
            "ram": {"total_mb": 8192, "available_mb": 4096, "sufficient": True,
                   "recommended": True, "low_resource": True},
            "swap": {"swap_available": True, "swap_total_mb": 2048},
            "cpu": {"compatible": True, "arch": "x86_64", "cores": 4},
            "packages": {"waydroid_installed": True},
            "initialized": {"initialized": True},
            "issues": [], "warnings": [],
        }
        base.update(overrides)
        return base

    def test_supported_system(self):
        from bright_android.core.compatibility import assess_hardware_readiness
        report = self._make_report(
            ram={"total_mb": 16384, "available_mb": 10000, "sufficient": True,
                 "recommended": True, "low_resource": False},
            graphics={"graphics_ok": True, "software_rendering": False,
                     "renderer": "NVIDIA GeForce RTX 3060", "vendor": "NVIDIA"},
        )
        hw = assess_hardware_readiness(report)
        self.assertEqual(hw["status"], "supported")

    def test_8gb_ram_is_limited(self):
        """8 GB RAM with Radeon R6 iGPU = supported_with_limitations."""
        from bright_android.core.compatibility import assess_hardware_readiness
        report = self._make_report()
        hw = assess_hardware_readiness(report)
        self.assertEqual(hw["status"], "supported_with_limitations")
        self.assertTrue(any("8 GB" in w or "resource-intensive" in w
                           for w in hw["warnings"]),
                       f"Expected 8GB warning, got: {hw['warnings']}")

    def test_unsupported_no_binder(self):
        from bright_android.core.compatibility import assess_hardware_readiness
        report = self._make_report(
            binder={"binder_available": False, "kernel_supported": False,
                   "module_installable": False, "module_needs_loading": False},
        )
        hw = assess_hardware_readiness(report)
        self.assertEqual(hw["status"], "unsupported")
        self.assertTrue(hw["blockers"])

    def test_unsupported_wrong_arch(self):
        from bright_android.core.compatibility import assess_hardware_readiness
        report = self._make_report(cpu={"compatible": False, "arch": "armv7l", "cores": 4})
        hw = assess_hardware_readiness(report)
        self.assertEqual(hw["status"], "unsupported")

    def test_no_swap_warning_on_low_ram(self):
        from bright_android.core.compatibility import assess_hardware_readiness
        report = self._make_report(swap={"swap_available": False, "swap_total_mb": 0})
        hw = assess_hardware_readiness(report)
        self.assertIn("supported_with_limitations", hw["status"])
        self.assertTrue(any("swap" in w.lower() for w in hw["warnings"]),
                       f"Expected swap warning, got: {hw['warnings']}")


# ---------------------------------------------------------------------------
# Real Waydroid integration tests (skipped unless WAYDROID_INTEGRATION=1)
# ---------------------------------------------------------------------------

@unittest.skipUnless(RUN_INTEGRATION, "Set WAYDROID_INTEGRATION=1 to run real tests")
class RealWaydroidIntegrationTests(unittest.TestCase):
    """Integration tests that require a real Waydroid installation."""

    def test_waydroid_binary_exists(self):
        self.assertIsNotNone(shutil.which("waydroid"))

    def test_status_command_works(self):
        from bright_android.core import waydroid_manager
        status = waydroid_manager.get_status(force_refresh=True)
        self.assertIn("running", status)


class BackgroundWorkerSignalTests(unittest.TestCase):
    """OperationComplete is declared (operation s, message s, success b).

    Completion arguments must follow that order, or D-Bus marshalling fails
    and clients never see the completion signal.
    """

    class _FakeService:
        def __init__(self):
            self.complete = []

        def OperationProgress(self, *args):
            pass

        def OperationComplete(self, *args):
            self.complete.append(args)

    def _run_op(self, func):
        from bright_android.core import android_service as svc
        fake = self._FakeService()
        with mock.patch.object(svc, "HAS_DBUS", True):
            svc.BackgroundWorker(fake)._run(func, "init")
        self.assertEqual(len(fake.complete), 1)
        return fake.complete[0]

    def test_success_arguments_match_declaration(self):
        op, message, success = self._run_op(lambda progress_cb=None: None)
        self.assertEqual(op, "init")
        self.assertIsInstance(message, str)
        self.assertIs(success, True)

    def test_failure_arguments_match_declaration(self):
        def boom(progress_cb=None):
            raise RuntimeError("download failed")
        op, message, success = self._run_op(boom)
        self.assertEqual(op, "init")
        self.assertEqual(message, "download failed")
        self.assertIs(success, False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
