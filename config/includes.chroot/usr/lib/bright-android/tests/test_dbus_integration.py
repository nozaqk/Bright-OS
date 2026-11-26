"""End-to-end tests over a real D-Bus session bus.

The real Bright Android service (bright_android/core/android_service.py) runs
as a subprocess on a private session bus, with a fake Waydroid backend (see
_service_harness.py). The client is the real BrightAndroidClient, and the
checks use the real signal path.

These tests need dbus-python, PyGObject and the dbus-daemon binary. They are
skipped elsewhere. Run them under the interpreter that has dbus-python:
    /usr/bin/python3.12 -m pytest bright_android/tests/test_dbus_integration.py

Polkit is not available in this environment, so non-root state changes are
denied (fail closed). Tests run as root, so the root policy applies. Live
Polkit prompts are not tested here.
"""

import os
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
HARNESS = Path(__file__).resolve().parent / "_service_harness.py"

from bright_android.core import service_client as sc  # noqa: E402
from bright_android.core import config_policy  # noqa: E402

BUS_NAME = sc.BUS_NAME
OBJECT_PATH = sc.OBJECT_PATH
INTERFACE = sc.INTERFACE


def _dbus_stack_available() -> bool:
    try:
        import dbus  # noqa: F401
        import dbus.mainloop.glib  # noqa: F401
        from gi.repository import GLib  # noqa: F401
    except ImportError:
        return False
    return shutil.which("dbus-daemon") is not None


AVAILABLE = _dbus_stack_available()
SKIP_REASON = "needs dbus-python, PyGObject and dbus-daemon (run under python3.12)"

def setUpModule():
    # The session bus is started once per run by conftest.py.
    pass


def session_bus(private=False):
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    return dbus.SessionBus(private=private, mainloop=DBusGMainLoop(set_as_default=False))


def pump(bus, predicate, timeout=15.0):
    """Dispatch D-Bus messages until predicate() is true."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for D-Bus signal or reply")
        sc.dispatch_pending(0.05)


class Harness:
    """One service subprocess with its own temporary home and call log."""

    def __init__(self, **env):
        self.env = {k: str(v) for k, v in env.items()}
        self.home = tempfile.mkdtemp(prefix="ba-home-")
        self.log = os.path.join(self.home, "backend-calls.log")
        self.proc = None

    @property
    def config_file(self) -> Path:
        return Path(self.home) / ".config" / "bright-android" / "config.ini"

    def start(self):
        if self.env.get("BLOCK_CONFIG_DIR") == "1":
            blocked = Path(self.home) / ".config" / "bright-android"
            blocked.parent.mkdir(parents=True, exist_ok=True)
            blocked.write_text("not a directory")
        env = dict(os.environ)
        env.update({
            "HOME": self.home,
            "BA_PROJECT_ROOT": str(PROJECT_ROOT),
            "FAKE_LOG": self.log,
            "DBUS_SESSION_BUS_ADDRESS": os.environ["DBUS_SESSION_BUS_ADDRESS"],
        })
        env.update(self.env)
        self.proc = subprocess.Popen([sys.executable, str(HARNESS)], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True)
        ready, _, _ = select.select([self.proc.stdout], [], [], 30)
        line = self.proc.stdout.readline() if ready else ""
        if "READY" not in line:
            err = self.proc.stderr.read() if self.proc.poll() is not None else ""
            self.stop()
            raise RuntimeError(f"service harness did not start: {err[-2000:]}")
        pump(session_bus(), lambda: session_bus().name_has_owner(BUS_NAME), timeout=10)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.home, ignore_errors=True)

    def backend_calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [line.strip() for line in f if line.strip()]


def _plain(value):
    """Convert dbus-python values to str or bool for comparison."""
    if isinstance(value, str):
        return str(value)
    if type(value).__name__ in ("Boolean", "bool"):
        return bool(value)
    return value


class Collector:
    """Records every service signal in arrival order."""

    def __init__(self, bus):
        self.events = []
        self._bus = bus
        self._lock = threading.Lock()
        for signal in ("OperationProgress", "OperationComplete", "RuntimeStateChanged"):
            bus.add_signal_receiver(self._record(signal), signal_name=signal,
                                    dbus_interface=INTERFACE, bus_name=BUS_NAME,
                                    path=OBJECT_PATH)

    def _record(self, name):
        def handler(*args):
            with self._lock:
                self.events.append((name, tuple(_plain(a) for a in args)))
        return handler

    def find(self, name, operation=None):
        with self._lock:
            return [args for n, args in self.events
                    if n == name and (operation is None or args[0] == operation)]


def proxy(bus=None):
    import dbus
    bus = bus or session_bus()
    return dbus.Interface(bus.get_object(BUS_NAME, OBJECT_PATH), INTERFACE)


def private_client():
    """A client with its own bus connection, for use from a worker thread."""
    bus = session_bus(private=True)
    import dbus
    iface = dbus.Interface(bus.get_object(BUS_NAME, OBJECT_PATH), INTERFACE)
    return sc.BrightAndroidClient(connection_factory=lambda: (iface, bus))


def ensure_stopped(client):
    bus = session_bus()
    running = bool(proxy(bus).GetStatus().get("running", False))
    if running:
        client.stop_runtime()


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class HappyPathTests(unittest.TestCase):
    DELAY = 1.0

    @classmethod
    def setUpClass(cls):
        cls.h = Harness(FAKE_DELAY=cls.DELAY)
        cls.h.start()

    @classmethod
    def tearDownClass(cls):
        cls.h.stop()

    def setUp(self):
        self.bus = session_bus()
        self.client = sc.BrightAndroidClient()
        ensure_stopped(self.client)

    def test_start_call_returns_before_the_operation_finishes(self):
        collector = Collector(self.bus)
        t0 = time.monotonic()
        proxy(self.bus).StartRuntime()
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, self.DELAY / 2, f"StartRuntime blocked for {elapsed:.2f}s")
        pump(self.bus, lambda: collector.find("OperationComplete", "start"))
        self.assertEqual(collector.find("OperationComplete", "start"), [("start", "", True)])
        self.assertEqual(collector.find("RuntimeStateChanged"), [(True,)])
        self.client.stop_runtime()

    def test_signals_arrive_in_order_progress_then_state_then_completion(self):
        collector = Collector(self.bus)
        proxy(self.bus).StartRuntime()
        pump(self.bus, lambda: collector.find("OperationComplete", "start"))
        names = [n for n, _ in collector.events]
        self.assertIn("OperationProgress", names)
        self.assertLess(names.index("OperationProgress"), names.index("RuntimeStateChanged"))
        self.assertLess(names.index("RuntimeStateChanged"), names.index("OperationComplete"))
        self.client.stop_runtime()

    def test_client_start_forwards_progress_and_returns_on_success(self):
        seen = []
        self.client.start_runtime(progress_cb=seen.append)
        self.assertIn("Starting Android container", seen)
        self.assertIn("Android is ready", seen)
        self.assertTrue(proxy(self.bus).GetStatus()["running"])
        self.client.stop_runtime()

    def test_status_query_is_not_blocked_during_start(self):
        proxy(self.bus).StartRuntime()
        t0 = time.monotonic()
        status = proxy(self.bus).GetStatus()
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, self.DELAY / 2, f"GetStatus waited {elapsed:.2f}s")
        self.assertFalse(bool(status["running"]))  # still starting
        pump(self.bus, lambda: bool(proxy(self.bus).GetStatus()["running"]))
        self.client.stop_runtime()

    def test_second_start_while_busy_is_refused(self):
        import dbus
        collector = Collector(self.bus)
        proxy(self.bus).StartRuntime()
        with self.assertRaises(dbus.exceptions.DBusException) as ctx:
            proxy(self.bus).StartRuntime()
        self.assertEqual(ctx.exception.get_dbus_name(), sc.ERR_BUSY)
        with self.assertRaises(dbus.exceptions.DBusException) as ctx:
            proxy(self.bus).StopRuntime()
        self.assertEqual(ctx.exception.get_dbus_name(), sc.ERR_BUSY)
        # The refused calls must not have disturbed the running start.
        pump(self.bus, lambda: collector.find("OperationComplete", "start"))
        self.assertEqual(collector.find("OperationComplete", "start"), [("start", "", True)])
        self.client.stop_runtime()

    def test_stop_after_start_stops_the_runtime(self):
        self.client.start_runtime()
        self.client.stop_runtime()
        self.assertFalse(bool(proxy(self.bus).GetStatus()["running"]))

    def test_concurrent_start_requests_run_at_most_once(self):
        ensure_stopped(self.client)
        starts_before = len([c for c in self.h.backend_calls() if c == "start_session"])
        results = []
        barrier = threading.Barrier(2)

        def attempt():
            client = private_client()
            barrier.wait()
            try:
                client.start_runtime()
                results.append("ok")
            except sc.ServiceBusy:
                results.append("busy")

        threads = [threading.Thread(target=attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(sorted(results), ["busy", "ok"])
        starts = [c for c in self.h.backend_calls() if c == "start_session"]
        self.assertEqual(len(starts) - starts_before, 1)
        self.client.stop_runtime()

    def test_launch_rejects_invalid_package_name(self):
        self.assertFalse(proxy(self.bus).LaunchApp("--help"))

    def test_launch_of_valid_name_fails_without_waydroid(self):
        self.assertFalse(proxy(self.bus).LaunchApp("com.example.app"))

    def test_batch_settings_write_every_value(self):
        count = self.client.set_configs([("runtime/auto_start", True),
                                         ("storage/shared_pictures", True)])
        self.assertEqual(count, 2)
        text = self.h.config_file.read_text()
        self.assertIn("auto_start = true", text)
        self.assertIn("shared_pictures = true", text)

    def test_batch_with_invalid_entry_changes_nothing(self):
        self.client.set_configs([("developer/show_logs", True)])
        before = self.h.config_file.read_bytes()
        with self.assertRaises(sc.RequestRejected) as ctx:
            self.client.set_configs([("runtime/auto_start", True), ("evil/x", True)])
        self.assertIn("setting 2", str(ctx.exception))
        self.assertEqual(self.h.config_file.read_bytes(), before)

    def test_batch_with_protected_key_changes_nothing(self):
        self.client.set_configs([("developer/show_logs", True)])
        before = self.h.config_file.read_bytes()
        with self.assertRaises(sc.RequestRejected):
            self.client.set_configs([("runtime/auto_start", True),
                                     ("storage/data_path", "/tmp/x")])
        self.assertEqual(self.h.config_file.read_bytes(), before)

    def test_concurrent_batches_keep_every_update(self):
        keys = [(f"{s}/{k}", True) for s, ks in config_policy.RUNTIME_WRITABLE.items() for k in ks]
        errors = []

        def write(pair):
            try:
                private_client().set_configs([pair])
            except Exception as e:  # reported below
                errors.append(e)

        threads = [threading.Thread(target=write, args=(p,)) for p in keys]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        text = self.h.config_file.read_text()
        for path, _ in keys:
            section, key = path.split("/")
            self.assertIn(f"{key} = true", text, path)


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class FailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = Harness(FAKE_DELAY="0.2", FAKE_FAIL="start,init")
        cls.h.start()

    @classmethod
    def tearDownClass(cls):
        cls.h.stop()

    def test_start_failure_is_reported_on_completion(self):
        client = sc.BrightAndroidClient()
        with self.assertRaises(sc.OperationFailed) as ctx:
            client.start_runtime()
        self.assertIn("container failed to boot", str(ctx.exception))

    def test_worker_is_idle_after_a_failure(self):
        # A failed operation must not leave the worker busy. The next start is
        # attempted and fails on its own merits, not with Busy.
        client = sc.BrightAndroidClient()
        with self.assertRaises(sc.OperationFailed) as ctx:
            client.start_runtime()
        self.assertNotIsInstance(ctx.exception, sc.ServiceBusy)

    def test_init_failure_is_reported_with_service_message(self):
        with self.assertRaises(sc.OperationFailed) as ctx:
            sc.BrightAndroidClient().initialize_runtime()
        self.assertIn("network unreachable", str(ctx.exception))

    def test_status_still_answers_after_failures(self):
        status = proxy().GetStatus()
        self.assertFalse(bool(status["running"]))


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class DeniedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = Harness(FAKE_DELAY="0.2", FAKE_DENY="1")
        cls.h.start()

    @classmethod
    def tearDownClass(cls):
        cls.h.stop()

    def test_denied_start_does_not_reach_the_backend(self):
        with self.assertRaises(sc.AuthorizationDenied):
            sc.BrightAndroidClient().start_runtime()
        self.assertNotIn("start_session", self.h.backend_calls())

    def test_denied_stop_and_init_are_refused(self):
        with self.assertRaises(sc.AuthorizationDenied):
            sc.BrightAndroidClient().stop_runtime()
        with self.assertRaises(sc.AuthorizationDenied):
            sc.BrightAndroidClient().initialize_runtime()
        self.assertEqual(self.h.backend_calls(), [])

    def test_denied_batch_changes_nothing(self):
        with self.assertRaises(sc.AuthorizationDenied):
            sc.BrightAndroidClient().set_configs([("runtime/auto_start", True)])
        self.assertFalse(self.h.config_file.exists())


@unittest.skipUnless(AVAILABLE, SKIP_REASON)
class ConfigWriteFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = Harness(FAKE_DELAY="0.2", BLOCK_CONFIG_DIR="1")
        cls.h.start()

    @classmethod
    def tearDownClass(cls):
        cls.h.stop()

    def test_write_failure_keeps_previous_settings_and_reports_it(self):
        with self.assertRaises(sc.OperationFailed) as ctx:
            sc.BrightAndroidClient().set_configs([("runtime/auto_start", True)])
        self.assertIn("previous settings kept", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
