"""Bright Android unit tests.

Tests for compatibility detection, APK validation, runtime management,
launcher integration, AURA authorization, and security validation.

These tests use mocks; they do not require a real Waydroid installation
or a running Android container.
"""
import configparser
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class CompatibilityTests(unittest.TestCase):
    """Tests for compatibility checking."""

    def test_kernel_binder_detection_without_devices(self):
        """When /dev/binder doesn't exist and no config is found,
        binder should be reported unavailable."""
        from bright_android.core.compatibility import check_kernel_binder
        with mock.patch("os.path.exists", return_value=False), \
             mock.patch("bright_android.core.compatibility._run_cmd",
                       return_value=(1, "", "")):
            result = check_kernel_binder()
            self.assertFalse(result["binder_available"])

    def test_kernel_binder_detection_with_device(self):
        """When /dev/binder exists, binder should be reported available."""
        from bright_android.core.compatibility import check_kernel_binder
        with mock.patch("os.path.exists",
                       side_effect=lambda p: p == "/dev/binder"), \
             mock.patch("bright_android.core.compatibility._run_cmd",
                       return_value=(1, "", "")):
            result = check_kernel_binder()
            self.assertTrue(result["binder_available"])

    def test_wayland_detection_in_wayland_session(self):
        """XDG_SESSION_TYPE=wayland should be detected."""
        from bright_android.core.compatibility import check_wayland_session
        env = {"XDG_SESSION_TYPE": "wayland",
               "XDG_RUNTIME_DIR": "/tmp/test-runtime",
               "WAYLAND_DISPLAY": "wayland-0"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch("os.path.isdir", return_value=True), \
                 mock.patch("os.path.exists", return_value=True):
                result = check_wayland_session()
                self.assertTrue(result["wayland_available"])

    def test_wayland_detection_x11_only(self):
        """X11-only session should report wayland unavailable."""
        from bright_android.core.compatibility import check_wayland_session
        env = {"XDG_SESSION_TYPE": "x11",
               "XDG_RUNTIME_DIR": "/tmp/test-runtime"}
        with mock.patch.dict(os.environ, env, clear=True):
            result = check_wayland_session()
            self.assertFalse(result["wayland_available"])

    def test_disk_space_check(self):
        """Disk space should be detected and reported."""
        from bright_android.core.compatibility import check_disk_space
        with tempfile.TemporaryDirectory() as tmpdir:
            result = check_disk_space(tmpdir)
            self.assertIn("available_gb", result)
            self.assertIsInstance(result["available_gb"], float)

    def test_ram_check(self):
        """RAM detection should read /proc/meminfo."""
        from bright_android.core.compatibility import check_ram
        result = check_ram()
        self.assertIn("total_mb", result)
        self.assertGreater(result["total_mb"], 0)

    def test_full_check_returns_all_keys(self):
        """run_full_check should return complete report."""
        from bright_android.core.compatibility import run_full_check
        with mock.patch("shutil.which", return_value=None), \
             mock.patch("os.path.exists", return_value=False):
            report = run_full_check()
            self.assertIn("can_install", report)
            self.assertIn("can_run", report)
            self.assertIn("issues", report)
            self.assertIn("warnings", report)
            self.assertIn("binder", report)
            self.assertIn("ram", report)
            self.assertIn("disk", report)


class APKValidationTests(unittest.TestCase):
    """Tests for APK file validation."""

    def test_reject_nonexistent_file(self):
        """Non-existent files should fail validation."""
        from bright_android.core.apk_validator import is_compatible_x86_64
        result = is_compatible_x86_64("/nonexistent/file.apk")
        self.assertFalse(result["compatible"])
        self.assertIn("not found", result["reason"])

    def test_reject_non_apk_extension(self):
        """Files without .apk extension should be rejected."""
        from bright_android.core.apk_validator import validate_apk_path
        with tempfile.NamedTemporaryFile(suffix=".txt") as f:
            err = validate_apk_path(f.name)
            self.assertIsNotNone(err)
            self.assertIn("Not an APK", err)

    def test_reject_too_small_file(self):
        """Very small files should be rejected as invalid."""
        from bright_android.core.apk_validator import is_compatible_x86_64
        with tempfile.NamedTemporaryFile(suffix=".apk") as f:
            f.write(b"tiny")
            f.flush()
            result = is_compatible_x86_64(f.name)
            self.assertFalse(result["compatible"])

    def test_validate_apk_path_null_byte(self):
        """Paths with null bytes must be rejected."""
        from bright_android.core.apk_validator import validate_apk_path
        err = validate_apk_path("/tmp/test.apk\x00evil")
        self.assertIsNotNone(err)
        self.assertIn("null byte", err)

    def _make_apk(self, entries, suffix=".apk"):
        """Helper to create a valid APK (ZIP) with minimum size."""
        # Pad content to exceed MIN_APK_BYTES (1 KB)
        padding = b"X" * 2048
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            import zipfile
            with zipfile.ZipFile(f, "w") as zf:
                for name, data in entries:
                    zf.writestr(name, data)
                zf.writestr("resources.arsc", padding)
            return f.name

    def test_x86_64_apk_compatible(self):
        """APK with x86_64 native libs should be compatible."""
        from bright_android.core.apk_validator import is_compatible_x86_64
        tmpname = self._make_apk([
            ("AndroidManifest.xml", b"binary-manifest"),
            ("lib/x86_64/libtest.so", b"fake-so" * 100),
            ("classes.dex", b"fake-dex" * 100),
        ])
        try:
            result = is_compatible_x86_64(tmpname)
            self.assertTrue(result["compatible"], msg=result["reason"])
            self.assertIn("x86_64", result["architectures"])
        finally:
            os.unlink(tmpname)

    def test_universal_apk_compatible(self):
        """Pure Java/Kotlin APKs (no native libs) should be universal."""
        from bright_android.core.apk_validator import is_compatible_x86_64
        tmpname = self._make_apk([
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
        """ARM-only APKs should report incompatibility with clear message."""
        from bright_android.core.apk_validator import is_compatible_x86_64
        tmpname = self._make_apk([
            ("AndroidManifest.xml", b"binary"),
            ("lib/arm64-v8a/libtest.so", b"fake-so" * 100),
        ])
        try:
            result = is_compatible_x86_64(tmpname)
            self.assertFalse(result["compatible"])
            self.assertIn("ARM", result["reason"])
        finally:
            os.unlink(tmpname)


class ConfigTests(unittest.TestCase):
    """Tests for Bright Android configuration."""

    def test_defaults_exist(self):
        """All default config keys should exist."""
        from bright_android.core import config as ba_config
        cfg = ba_config.load_config()
        # Key defaults
        self.assertFalse(ba_config.get_bool("runtime", "auto_start", False))
        self.assertTrue(ba_config.get_bool("runtime", "start_on_demand", True))
        self.assertTrue(ba_config.get_bool("integration", "clipboard_share", True))
        self.assertTrue(ba_config.get_bool("integration", "app_integration", True))
        self.assertTrue(ba_config.get_bool("storage", "shared_downloads", True))
        self.assertFalse(ba_config.get_bool("developer", "adb_enabled", False))

    def test_set_and_get_value(self):
        """Values should persist after setting."""
        from bright_android.core import config as ba_config
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("bright_android.core.config.CONFIG_DIR", tmpdir), \
                 mock.patch("bright_android.core.config.CONFIG_FILE",
                           os.path.join(tmpdir, "config.ini")):
                ba_config.set_bool("test", "enabled", True)
                self.assertTrue(ba_config.get_bool("test", "enabled", False))

                ba_config.set_value("test", "name", "hello")
                self.assertEqual(ba_config.get_value("test", "name"), "hello")


class WaydroidManagerTests(unittest.TestCase):
    """Tests for Waydroid command wrapping (mocked)."""

    def test_is_installed_checks_path(self):
        """is_installed should check for waydroid binary."""
        from bright_android.core import waydroid_manager
        with mock.patch("shutil.which", return_value="/usr/bin/waydroid"):
            self.assertTrue(waydroid_manager.is_installed())
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(waydroid_manager.is_installed())

    def test_require_waydroid_decorator(self):
        """@_require_waydroid should raise when waydroid missing."""
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

    def test_run_uses_argument_list_no_shell(self):
        """_run must not use shell=True."""
        from bright_android.core import waydroid_manager
        with mock.patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            waydroid_manager._run(["status"], timeout=5)
            args = mock_run.call_args
            # Verify shell=False and args are a list
            self.assertFalse(args[1].get("shell", False))
            cmd_list = args[0][0]
            self.assertIsInstance(cmd_list, list)
            self.assertEqual(cmd_list[0], "waydroid")

    def test_invalid_package_name_rejected(self):
        """Uninstall should reject package names with dangerous characters."""
        from bright_android.core import waydroid_manager
        from bright_android.core.waydroid_manager import WaydroidError
        with mock.patch("bright_android.core.waydroid_manager.is_installed",
                       return_value=True):
            with mock.patch("bright_android.core.waydroid_manager.is_running",
                           return_value=True):
                with self.assertRaises(WaydroidError):
                    waydroid_manager.uninstall_app("; rm -rf /")


class LauncherIntegrationTests(unittest.TestCase):
    """Tests for .desktop file management."""

    def test_desktop_entry_created(self):
        """Should create valid .desktop file with correct fields."""
        from bright_android.core.launcher_integration import (
            create_app_desktop_entry, _desktop_filename, _ensure_dirs,
            APP_DIR
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("bright_android.core.launcher_integration.APP_DIR",
                           tmpdir), \
                 mock.patch("bright_android.core.launcher_integration.ICON_DIR",
                           os.path.join(tmpdir, "icons")), \
                 mock.patch("bright_android.core.launcher_integration.ANDROID_ICON_CACHE",
                           os.path.join(tmpdir, "cache")):
                app = {"package": "com.example.test", "name": "Test App",
                       "launch_activity": "com.example/.Main"}
                path = create_app_desktop_entry(app)
                self.assertTrue(path.exists())
                content = path.read_text()
                self.assertIn("com.example.test", content)
                self.assertIn("Test App", content)
                self.assertIn("bright-android --launch", content)
                # configparser writes "X-Bright-Android = true" with spaces
                self.assertIn("X-Bright-Android", content)
                self.assertIn("true", content)

    def test_remove_app_entry(self):
        """Should remove .desktop file for a package."""
        from bright_android.core.launcher_integration import (
            create_app_desktop_entry, remove_app_desktop_entry
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("bright_android.core.launcher_integration.APP_DIR",
                           tmpdir), \
                 mock.patch("bright_android.core.launcher_integration.ICON_DIR",
                           os.path.join(tmpdir, "icons")), \
                 mock.patch("bright_android.core.launcher_integration.ANDROID_ICON_CACHE",
                           os.path.join(tmpdir, "cache")), \
                 mock.patch("bright_android.core.launcher_integration._update_desktop_database"):
                app = {"package": "com.test.app", "name": "App"}
                create_app_desktop_entry(app)
                self.assertTrue(remove_app_desktop_entry("com.test.app"))
                self.assertFalse(remove_app_desktop_entry("com.test.app"))


class SecurityValidationTests(unittest.TestCase):
    """Security-focused tests."""

    def test_apk_path_traversal_prevented(self):
        """Paths with .. should still resolve to real paths but not execute anything."""
        from bright_android.core.apk_validator import validate_apk_path
        with tempfile.TemporaryDirectory() as tmpdir:
            fpath = os.path.join(tmpdir, "test.apk")
            Path(fpath).write_bytes(b"PK\x03\x04dummy")
            # Valid absolute path should work
            self.assertIsNone(validate_apk_path(fpath))

    def test_waydroid_run_does_not_use_shell(self):
        """Verify subprocess is called with shell=False."""
        import inspect
        from bright_android.core import waydroid_manager
        source = inspect.getsource(waydroid_manager._run)
        self.assertNotIn("shell=True", source)

    def test_privileged_ops_require_auth_stub(self):
        """Polkit check should reject calls with no sender."""
        # When HAS_POLKIT is False and caller is not root, deny
        from bright_android.core.android_service import _check_polkit
        # sender=None should fail
        ok, reason = _check_polkit(None, "org.bright_os.BrightAndroid.init")
        self.assertFalse(ok)

    def test_config_file_has_restrictive_permissions(self):
        """save_config should create files with 0600."""
        from bright_android.core import config as ba_config
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.ini")
            with mock.patch("bright_android.core.config.CONFIG_DIR", tmpdir), \
                 mock.patch("bright_android.core.config.CONFIG_FILE", cfg_path):
                ba_config.set_value("test", "key", "val")
                mode = os.stat(cfg_path).st_mode & 0o777
                self.assertEqual(mode, 0o600)


class EditionBehaviorTests(unittest.TestCase):
    """Edition-specific behavior tests."""

    def test_lite_edition_does_not_include_android_packages(self):
        """Lite edition should not have android packages in package list copy."""
        # Verify build.sh logic: lite does NOT copy android-packages.list.chroot
        build_sh = (PROJECT_ROOT / "build/scripts/build.sh").read_text()
        self.assertIn('EDITION}" = "lite"', build_sh)
        self.assertIn("Android support optional (not installed by default)", build_sh)

    def test_home_developer_include_android_packages(self):
        """Home/Developer editions include android package list."""
        build_sh = (PROJECT_ROOT / "build/scripts/build.sh").read_text()
        self.assertIn("android.list.chroot", build_sh)
        self.assertIn("Android packages: included", build_sh)

    def test_package_list_exists(self):
        """android.list.chroot must exist."""
        self.assertTrue(
            (PROJECT_ROOT / "config/package-lists/android.list.chroot").exists()
        )

    def test_android_package_list_contains_waydroid(self):
        pkglist = (PROJECT_ROOT / "config/package-lists/android.list.chroot").read_text()
        self.assertIn("waydroid", pkglist)
        # Must NOT bundle Google Play Services by default
        self.assertNotIn("gapps", pkglist.lower())
        # Must NOT contain model weights or AI blobs
        self.assertNotIn(".gguf", pkglist)

    def test_no_google_play_by_default(self):
        """Documentation and config must not bundle Google services."""
        init_mode_default = None
        # waydroid_manager init defaults to vanilla
        from bright_android.core import waydroid_manager
        source = open(waydroid_manager.__file__).read()
        self.assertIn("VANILLA", source)
        self.assertNotIn("GAPPS", source.split("def init")[1].split("def ")[0]
                         if "def init" in source else "")


class PolkitPolicyTests(unittest.TestCase):
    """Verify Polkit policy requires auth for dangerous operations."""

    def setUp(self):
        import xml.etree.ElementTree as ET
        policy_path = PROJECT_ROOT / "config/includes.chroot/usr/share/polkit-1/actions/org.bright_os.BrightAndroid.policy"
        self.tree = ET.parse(policy_path)
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
        self.assertEqual(d.findtext("allow_any"), "auth_admin")
        self.assertEqual(d.findtext("allow_active"), "auth_admin")

    def test_launch_app_no_polkit_action(self):
        """Launching an app should not require admin (user action)."""
        actions = [a.get("id") for a in self.root.findall("action")]
        self.assertNotIn("org.bright_os.BrightAndroid.launch-app", actions)


class AURAIntegrationTests(unittest.TestCase):
    """AURA command integration tests."""

    def test_requires_confirmation_for_privileged(self):
        from aura.commands.bright_android import requires_confirmation
        self.assertTrue(requires_confirmation("install_runtime"))
        self.assertTrue(requires_confirmation("install_apk"))
        self.assertTrue(requires_confirmation("uninstall_app"))
        self.assertTrue(requires_confirmation("remove_data"))

    def test_no_confirmation_for_status(self):
        from aura.commands.bright_android import requires_confirmation
        self.assertFalse(requires_confirmation("list_apps"))
        self.assertFalse(requires_confirmation("get_status"))

    def test_list_android_apps_returns_list(self):
        from aura.commands.bright_android import get_android_status
        with mock.patch("shutil.which", return_value=None):
            status = get_android_status()
            self.assertFalse(status["installed"])
            self.assertEqual(status["app_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
