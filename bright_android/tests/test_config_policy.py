"""Allowlist tests for runtime configuration changes (SetConfig).

Every permitted key is accepted with each legal value. Every rejection category
is tested, and rejected changes must never reach the config writer.
"""
import unittest
from unittest import mock

from bright_android.core import config_policy as cp


PERMITTED = [(s, k) for s, kinds in cp.RUNTIME_WRITABLE.items() for k in kinds]


class PermittedKeyTests(unittest.TestCase):

    def test_allowlist_is_exactly_the_gui_keys(self):
        # The GUI reads/writes these 12 keys and nothing else.
        self.assertEqual(len(PERMITTED), 12)
        self.assertEqual(set(PERMITTED), {
            ("runtime", "auto_start"), ("runtime", "start_on_demand"),
            ("integration", "clipboard_share"), ("integration", "notification_forward"),
            ("integration", "app_integration"),
            ("storage", "shared_downloads"), ("storage", "shared_documents"),
            ("storage", "shared_pictures"),
            ("developer", "adb_enabled"), ("developer", "show_logs"),
            ("developer", "nogpu_mode"),
            ("appearance", "freeform_windows"),
        })

    def test_each_permitted_key_accepts_true_and_false(self):
        for section, key in PERMITTED:
            for value in ("true", "false"):
                with self.subTest(key=f"{section}/{key}", value=value):
                    got = cp.validate_setting(f"{section}/{key}", value)
                    self.assertEqual(got, (section, key, value))

    def test_set_setting_writes_permitted_change(self):
        with mock.patch.object(cp, "ba_config") as cfg:
            cp.set_setting("developer/show_logs", "true")
        # Writes go through the atomic batch path, as a one-entry batch.
        cfg.set_values.assert_called_once_with([("developer", "show_logs", "true")])


class RejectionTests(unittest.TestCase):

    def assertRejected(self, path, value, reason_part):
        with mock.patch.object(cp, "ba_config") as cfg:
            with self.assertRaises(cp.ConfigPolicyError) as ctx:
                cp.set_setting(path, value)
        self.assertIn(reason_part, str(ctx.exception))
        cfg.set_values.assert_not_called()  # rejected changes never reach the writer

    # --- unknown sections and keys --------------------------------------
    def test_unknown_section(self):
        self.assertRejected("evil/show_logs", "true", "unknown section")

    def test_unknown_key_in_known_section(self):
        self.assertRejected("developer/made_up", "true", "not a runtime-writable")

    def test_schema_only_keys_are_not_writable(self):
        # Present in config.DEFAULTS but never read by code: not runtime-writable.
        for section, key in [("runtime", "stop_on_idle"), ("runtime", "idle_timeout_minutes"),
                             ("runtime", "suspend_when_inactive"),
                             ("integration", "shared_clipboard_bidirectional"),
                             ("integration", "window_integration"),
                             ("storage", "shared_music"), ("storage", "shared_videos"),
                             ("developer", "adb_port"), ("developer", "debug_mode"),
                             ("appearance", "force_landscape"), ("appearance", "dpi")]:
            with self.subTest(key=f"{section}/{key}"):
                self.assertRejected(f"{section}/{key}", "true", "not a runtime-writable")

    # --- protected settings ----------------------------------------------
    def test_data_path_is_protected(self):
        self.assertRejected("storage/data_path", "/tmp/evil", "protected setting")

    def test_protected_setting_rejected_even_with_valid_value(self):
        self.assertRejected("storage/data_path", "/var/lib/waydroid", "protected setting")

    # --- key format --------------------------------------------------------
    def test_key_without_separator(self):
        self.assertRejected("developer", "true", "section/key format")

    def test_key_with_extra_separators(self):
        self.assertRejected("developer/show_logs/extra", "true", "section/key format")

    def test_path_traversal_attempts(self):
        for path in ("../developer/show_logs", "developer/../show_logs", "/developer/show_logs"):
            with self.subTest(path=path):
                with mock.patch.object(cp, "ba_config") as cfg:
                    with self.assertRaises(cp.ConfigPolicyError):
                        cp.set_setting(path, "true")
                cfg.set_values.assert_not_called()

    def test_names_must_be_lowercase_letters_and_underscores(self):
        for path in ("Developer/show_logs", "developer/SHOW_LOGS", "developer/show-logs",
                     "developer/show_logs1", "developer/show logs", "developer/;rm",
                     "", "/", "developer/"):
            with self.subTest(path=path):
                with mock.patch.object(cp, "ba_config") as cfg:
                    with self.assertRaises(cp.ConfigPolicyError):
                        cp.set_setting(path, "true")
                cfg.set_values.assert_not_called()

    def test_key_too_long(self):
        self.assertRejected("developer/" + "a" * 60, "true", "too long")

    # --- value types --------------------------------------------------------
    def test_boolean_values_are_strict(self):
        for bad in ("yes", "no", "on", "off", "1", "0", "True", "FALSE", " true", "true ", ""):
            with self.subTest(value=bad):
                self.assertRejected("developer/show_logs", bad, "'true' or 'false'")

    def test_non_string_values_rejected(self):
        for bad in (True, 1, None, ["true"]):
            with self.subTest(value=repr(bad)):
                with mock.patch.object(cp, "ba_config") as cfg:
                    with self.assertRaises(cp.ConfigPolicyError):
                        cp.set_setting("developer/show_logs", bad)
                cfg.set_values.assert_not_called()

    def test_value_too_long(self):
        self.assertRejected("developer/show_logs", "t" * 17, "too long")

    def test_non_string_key_rejected(self):
        with mock.patch.object(cp, "ba_config") as cfg:
            with self.assertRaises(cp.ConfigPolicyError):
                cp.set_setting(None, "true")
        cfg.set_values.assert_not_called()


class SetConfigWiringTests(unittest.TestCase):
    """SetConfig must route every write through the allowlist (source check,
    because the D-Bus service class is not importable without dbus-python)."""

    def _set_config_body(self):
        import pathlib as _p
        src = (_p.Path(__file__).resolve().parents[1] / "core" / "android_service.py").read_text()
        start = src.index("def SetConfig(self, key: str, value: str, sender=None):")
        end = src.index("@method", start)
        return src[start:end]

    def test_set_config_uses_allowlist(self):
        body = self._set_config_body()
        self.assertIn("config_policy.set_setting(key, value)", body)
        self.assertIn("ConfigPolicyError", body)

    def test_set_config_does_not_write_directly(self):
        body = self._set_config_body()
        self.assertNotIn("ba_config.set_value", body)
        self.assertNotIn("set_value(section", body)


if __name__ == "__main__":
    unittest.main()
