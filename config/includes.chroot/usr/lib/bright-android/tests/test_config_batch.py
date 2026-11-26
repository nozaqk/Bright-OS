"""Batch configuration writes: validation, atomicity, concurrency.

Each test points the config module at a temporary directory, so the real user
config is never touched.
"""

import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bright_android.core import config as ba_config  # noqa: E402
from bright_android.core import config_policy as policy  # noqa: E402

ALL_KEYS = [
    (f"{section}/{key}", "true")
    for section, keys in policy.RUNTIME_WRITABLE.items() for key in keys
]


class TempConfigMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "bright-android"
        self.file = self.dir / "config.ini"
        self._patches = [
            mock.patch.object(ba_config, "CONFIG_DIR", str(self.dir)),
            mock.patch.object(ba_config, "CONFIG_FILE", str(self.file)),
            mock.patch.object(ba_config, "SYSTEM_CONFIG", str(self.dir / "no-system.ini")),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def write_initial(self, text="[runtime]\nauto_start = false\n"):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file.write_text(text)

    def leftover_temp_files(self):
        if not self.dir.exists():
            return []
        return [p.name for p in self.dir.iterdir() if p.name.endswith(".tmp")]


class ValidBatchTests(TempConfigMixin, unittest.TestCase):
    def test_valid_batch_writes_every_setting(self):
        self.write_initial()
        count = policy.set_settings([
            ("runtime/auto_start", "true"),
            ("storage/shared_pictures", "true"),
            ("developer/adb_enabled", "false"),
        ])
        self.assertEqual(count, 3)
        cfg = ba_config.load_config()
        self.assertEqual(cfg.get("runtime", "auto_start"), "true")
        self.assertEqual(cfg.get("storage", "shared_pictures"), "true")
        self.assertEqual(cfg.get("developer", "adb_enabled"), "false")

    def test_every_allowlisted_key_is_accepted_in_one_batch(self):
        self.write_initial()
        self.assertEqual(policy.set_settings(ALL_KEYS), len(ALL_KEYS))
        self.assertEqual(len(ALL_KEYS), 12)

    def test_file_permissions_are_owner_only(self):
        self.write_initial()
        policy.set_settings([("runtime/auto_start", "true")])
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_no_temp_files_left_after_success(self):
        self.write_initial()
        policy.set_settings([("runtime/auto_start", "true")])
        self.assertEqual(self.leftover_temp_files(), [])


class InvalidBatchTests(TempConfigMixin, unittest.TestCase):
    """Any invalid entry rejects the whole batch, and the file is unchanged."""

    def assertRejectedUnchanged(self, pairs, message_part):
        self.write_initial()
        before = self.file.read_bytes()
        with self.assertRaises(policy.ConfigPolicyError) as ctx:
            policy.set_settings(pairs)
        self.assertIn(message_part, str(ctx.exception))
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(self.leftover_temp_files(), [])

    def test_empty_batch_rejected(self):
        self.assertRejectedUnchanged([], "no settings")

    def test_unknown_section_rejects_whole_batch(self):
        self.assertRejectedUnchanged(
            [("runtime/auto_start", "true"), ("evil/key", "true")],
            "setting 2: unknown section")

    def test_unknown_key_rejects_whole_batch(self):
        self.assertRejectedUnchanged(
            [("runtime/auto_start", "true"), ("runtime/not_a_key", "true")],
            "setting 2")

    def test_protected_key_rejects_whole_batch(self):
        self.assertRejectedUnchanged(
            [("runtime/auto_start", "true"), ("storage/data_path", "/tmp/x")],
            "protected")

    def test_invalid_bool_value_rejects_whole_batch(self):
        self.assertRejectedUnchanged(
            [("runtime/auto_start", "true"), ("integration/clipboard_share", "True")],
            "must be 'true' or 'false'")

    def test_non_string_value_rejected(self):
        self.assertRejectedUnchanged([("runtime/auto_start", True)], "strings")

    def test_overlong_value_rejected(self):
        self.assertRejectedUnchanged([("runtime/auto_start", "t" * 17)], "too long")

    def test_duplicate_key_rejected(self):
        self.assertRejectedUnchanged(
            [("runtime/auto_start", "true"), ("runtime/auto_start", "false")],
            "appears twice")

    def test_oversized_batch_rejected(self):
        pairs = [("runtime/auto_start", "true")] * (policy.MAX_BATCH + 1)
        self.assertRejectedUnchanged(pairs, "too many settings")

    def test_malformed_entry_rejected(self):
        self.assertRejectedUnchanged([("runtime/auto_start",)], "(key, value) pair")

    def test_non_iterable_rejected(self):
        self.write_initial()
        with self.assertRaises(policy.ConfigPolicyError):
            policy.set_settings(42)


class PartialWritePreventionTests(TempConfigMixin, unittest.TestCase):
    def test_failed_rename_keeps_previous_config(self):
        self.write_initial("[runtime]\nauto_start = false\n")
        before = self.file.read_bytes()
        with mock.patch.object(ba_config.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                policy.set_settings([("runtime/auto_start", "true")])
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(self.leftover_temp_files(), [])

    def test_failure_while_writing_keeps_previous_config(self):
        self.write_initial("[runtime]\nauto_start = false\n")
        before = self.file.read_bytes()

        real_write = ba_config.configparser.ConfigParser.write

        def broken_write(self, fp, *a, **k):
            fp.write("[runtime]\nauto_st")  # partial output, then fail
            raise OSError("write interrupted")

        with mock.patch.object(ba_config.configparser.ConfigParser, "write", broken_write):
            with self.assertRaises(OSError):
                policy.set_settings([("runtime/auto_start", "true"),
                                     ("integration/clipboard_share", "false")])
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(self.leftover_temp_files(), [])
        self.assertIs(ba_config.configparser.ConfigParser.write, real_write)

    def test_failed_batch_writes_none_of_its_settings(self):
        self.write_initial()
        with self.assertRaises(policy.ConfigPolicyError):
            policy.set_settings([("runtime/auto_start", "true"), ("bad/key", "true")])
        cfg = ba_config.load_config()
        self.assertEqual(cfg.get("runtime", "auto_start"), "false")


class ConcurrencyTests(TempConfigMixin, unittest.TestCase):
    def test_concurrent_batches_do_not_lose_updates(self):
        self.write_initial()
        errors = []

        def write_one(pair):
            try:
                policy.set_settings([pair])
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)

        threads = [threading.Thread(target=write_one, args=(p,)) for p in ALL_KEYS]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(errors, [])
        cfg = ba_config.load_config()
        for path, value in ALL_KEYS:
            section, key = path.split("/")
            self.assertEqual(cfg.get(section, key), value, path)


if __name__ == "__main__":
    unittest.main()
