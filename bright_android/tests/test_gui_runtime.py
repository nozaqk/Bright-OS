"""GUI runtime tests: real PyQt6 pages driving the real service over D-Bus.

Runs under an offscreen Qt platform, against the service subprocess from
_service_harness.py on a private session bus. Needs PyQt6, dbus-python,
PyGObject and dbus-daemon, so it runs under python3.12 (see
test_dbus_integration.py for the environment notes). Skipped otherwise.

Message boxes are patched so the tests can read what the user would see, and
the tests do not block on a modal dialog.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from PyQt6.QtWidgets import QApplication, QMessageBox
    HAS_QT = True
except ImportError:
    HAS_QT = False

from bright_android.core import config as ba_config  # noqa: E402
from bright_android.tests import test_dbus_integration as integ  # noqa: E402

AVAILABLE = HAS_QT and integ.AVAILABLE
SKIP_REASON = "needs PyQt6, dbus-python, PyGObject and dbus-daemon (run under python3.12)"

_app = None


def setUpModule():
    # The session bus is started once per run by conftest.py.
    global _app
    if AVAILABLE:
        _app = QApplication.instance() or QApplication([])


def pump_qt(predicate, timeout=20.0):
    """Process Qt events until predicate() is true (lets worker signals arrive)."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the GUI to finish")
        _app.processEvents()
        time.sleep(0.01)
    _app.processEvents()


def _wait_for_threads():
    import gc
    from PyQt6.QtCore import QThread

    def running():
        return [o for o in gc.get_objects() if isinstance(o, QThread) and o.isRunning()]

    pump_qt(lambda: not running())


def idle(worker_attr, page):
    worker = getattr(page, worker_attr, None)
    return worker is None or not worker.isRunning()


class _Dialogs:
    """Replaces the message boxes, recording what the user would see."""

    def __init__(self, question_answer=None):
        from PyQt6.QtWidgets import QMessageBox as QMB
        yes = QMB.StandardButton.Yes
        self.question_answer = question_answer if question_answer is not None else yes
        self.info, self.critical, self.asked = [], [], []
        self._patches = [
            mock.patch.object(QMB, "information", side_effect=lambda p, t, m, *a, **k: self.info.append((t, m))),
            mock.patch.object(QMB, "critical", side_effect=lambda p, t, m, *a, **k: self.critical.append((t, m))),
            mock.patch.object(QMB, "question", side_effect=lambda p, t, m, *a, **k: (self.asked.append(t), self.question_answer)[1]),
        ]

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


class _HarnessCase(unittest.TestCase):
    ENV = {}

    @classmethod
    def setUpClass(cls):
        if not AVAILABLE:
            return
        cls.h = integ.Harness(FAKE_DELAY="0.3", **cls.ENV)
        cls.h.start()

    @classmethod
    def tearDownClass(cls):
        if AVAILABLE:
            cls.h.stop()

    def setUp(self):
        # The GUI reads settings in this process, and the service writes them.
        # Point both at the same temporary config file.
        cfg_dir = Path(self.h.home) / ".config" / "bright-android"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        self._cfg = [
            mock.patch.object(ba_config, "CONFIG_DIR", str(cfg_dir)),
            mock.patch.object(ba_config, "CONFIG_FILE", str(cfg_dir / "config.ini")),
            mock.patch.object(ba_config, "SYSTEM_CONFIG", str(cfg_dir / "no-system.ini")),
        ]
        for p in self._cfg:
            p.start()

    def tearDown(self):
        # Wait for the page's worker threads before the page is destroyed.
        # Destroying a running QThread aborts the process.
        _wait_for_threads()
        self.page = None
        for p in self._cfg:
            p.stop()


def _gui():
    from bright_android import gui
    return gui


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class SettingsPageTests(_HarnessCase):
    def _page(self):
        self.page = _gui().SettingsPage()
        return self.page

    def _wait_saved(self, page):
        pump_qt(lambda: idle("save_worker", page))

    def test_save_writes_changed_settings_in_one_call(self):
        page = self._page()
        page.share_pictures_cb.setChecked(True)
        page.adb_cb.setChecked(False)
        with _Dialogs() as d:
            page.save_settings()
            self._wait_saved(page)
        self.assertEqual(d.critical, [])
        self.assertIn(("Settings Saved", "Android settings have been saved."), d.info)
        text = (Path(self.h.home) / ".config" / "bright-android" / "config.ini").read_text()
        self.assertIn("shared_pictures = true", text)

    def test_save_with_no_changes_sends_nothing(self):
        page = self._page()
        config_file = Path(self.h.home) / ".config" / "bright-android" / "config.ini"
        with _Dialogs() as d:
            page.save_settings()
        # Checkboxes match the defaults, so nothing is sent and nothing is written.
        self.assertEqual(d.info, [("Settings Saved", "No changes to save.")])
        self.assertFalse(config_file.exists())

    def test_restart_stops_then_starts_through_service(self):
        page = self._page()
        before = len(self.h.backend_calls())
        with _Dialogs() as d:
            page.restart_runtime()
            pump_qt(lambda: idle("restart_worker", page))
        self.assertEqual(d.critical, [])
        self.assertIn(("Restarted", "Android runtime restarted."), d.info)
        new_calls = self.h.backend_calls()[before:]
        self.assertEqual(new_calls[-1], "start_session")


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class SettingsDeniedTests(_HarnessCase):
    ENV = {"FAKE_DENY": "1"}

    def test_denied_save_reports_error_and_writes_nothing(self):
        page = self.page = _gui().SettingsPage()
        page.share_pictures_cb.setChecked(True)
        with _Dialogs() as d:
            page.save_settings()
            pump_qt(lambda: idle("save_worker", page))
        self.assertEqual(d.info, [])
        self.assertEqual(len(d.critical), 1)
        title, message = d.critical[0]
        self.assertEqual(title, "Settings Not Saved")
        self.assertIn("denied by test policy", message)
        self.assertFalse((Path(self.h.home) / ".config" / "bright-android" / "config.ini").exists())


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class RuntimeControlTests(_HarnessCase):
    def test_start_then_stop_from_home_page(self):
        page = self.page = _gui().HomePage()
        with _Dialogs() as d:
            page.start_android()
            pump_qt(lambda: idle("worker", page))
            self.assertEqual(d.critical, [])
            self.assertIn("start_session", self.h.backend_calls())
            page.stop_android()
            pump_qt(lambda: idle("worker", page))
        self.assertEqual(d.critical, [])
        self.assertIn("stop_session", self.h.backend_calls())

    def test_init_from_home_page_runs_through_service(self):
        page = self.page = _gui().HomePage()
        with _Dialogs() as d:
            page.init_android()
            pump_qt(lambda: idle("worker", page))
        self.assertEqual(d.critical, [])
        self.assertIn("init", self.h.backend_calls())


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class RuntimeFailureTests(_HarnessCase):
    ENV = {"FAKE_FAIL": "start,init"}

    def test_failed_start_shows_service_message(self):
        page = self.page = _gui().HomePage()
        with _Dialogs() as d:
            page.start_android()
            pump_qt(lambda: idle("worker", page))
        self.assertEqual(len(d.critical), 1)
        title, message = d.critical[0]
        self.assertEqual(title, "Operation Failed")
        self.assertIn("container failed to boot", message)


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class ApplicationsPageTests(_HarnessCase):
    ENV = {"FAKE_FAIL": "install"}

    def test_uninstall_asks_then_calls_service(self):
        page = self.page = _gui().ApplicationsPage()
        with _Dialogs() as d:
            page.uninstall_app("com.example.app", "Example")
        self.assertEqual(d.asked, ["Uninstall Application"])
        self.assertIn(("Uninstalled", "Example has been uninstalled."), d.info)
        self.assertIn("uninstall_app:com.example.app", self.h.backend_calls())

    def test_launch_of_missing_app_reports_failure(self):
        page = self.page = _gui().ApplicationsPage()
        with _Dialogs() as d:
            page.launch_app("com.example.missing")
        self.assertEqual(len(d.critical), 1)
        self.assertEqual(d.critical[0][0], "Launch Failed")

    def test_install_failure_is_reported(self):
        page = self.page = _gui().ApplicationsPage()
        apk = Path(tempfile.mkdtemp()) / "example.apk"
        apk.write_bytes(b"x")
        try:
            with _Dialogs() as d:
                page._do_install_apk(str(apk))
                pump_qt(lambda: idle("worker", page))
        finally:
            shutil.rmtree(apk.parent, ignore_errors=True)
        self.assertEqual(len(d.critical), 1)
        self.assertEqual(d.critical[0][0], "Installation Failed")
        self.assertIn("INSTALL_FAILED", d.critical[0][1])


if __name__ == "__main__":
    unittest.main()
